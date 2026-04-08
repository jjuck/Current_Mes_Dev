from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import AppConfig
from .domain import SerialNumber
from .serial_reader import WatanabeA7212Reader
from .service import MeasurementExecutionError, MeasurementRecorder, build_measurement_recorder, build_measurement_threshold
from .status_service import MeasurementStatusService


class MeasurementRequest(BaseModel):
    qr_code: str


NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def create_web_app(
    config: AppConfig,
    application_logger: logging.Logger,
    measurement_recorder: MeasurementRecorder | None = None,
    status_service: MeasurementStatusService | None = None,
    instrument_reader: WatanabeA7212Reader | None = None,
    web_root: Path | None = None,
) -> FastAPI:
    project_root = Path(__file__).resolve().parents[2]
    resolved_web_root = web_root or project_root / "web"
    measurement_threshold = build_measurement_threshold(config)
    resolved_instrument_reader = instrument_reader or WatanabeA7212Reader(config.serial_settings)
    resolved_status_service = status_service or MeasurementStatusService(
        log_csv_path=config.log_csv_path,
        log_encoding=config.log_encoding,
        measurement_threshold=measurement_threshold,
        recent_limit=config.recent_measurement_limit,
        legacy_log_csv_path=config.legacy_log_csv_path,
    )
    resolved_measurement_recorder = measurement_recorder or build_measurement_recorder(
        config=config,
        application_logger=application_logger,
        status_service=resolved_status_service,
        instrument_reader=resolved_instrument_reader,
    )

    app = FastAPI(title="Precision Lab Measurement Station")
    process_range_text = _build_process_range_text(config)

    @app.get("/")
    def read_index() -> FileResponse:
        return FileResponse(resolved_web_root / "index.html", headers=NO_CACHE_HEADERS)

    @app.get("/styles.css")
    def read_styles() -> FileResponse:
        return FileResponse(
            resolved_web_root / "styles.css",
            media_type="text/css",
            headers=NO_CACHE_HEADERS,
        )

    @app.get("/app.js")
    def read_script() -> FileResponse:
        return FileResponse(
            resolved_web_root / "app.js",
            media_type="application/javascript",
            headers=NO_CACHE_HEADERS,
        )

    @app.get("/assets/logo.png")
    def read_logo_asset() -> FileResponse:
        if config.logo_asset_path is None:
            raise HTTPException(status_code=404, detail="Logo asset is not configured.")

        return FileResponse(
            config.logo_asset_path,
            media_type="image/png",
            headers=NO_CACHE_HEADERS,
        )

    @app.get("/api/status")
    def read_status() -> dict[str, object]:
        port_status = resolved_instrument_reader.probe_connection_status()
        resolved_status_service.set_com_connection(port_status.is_connected, port_status.port_name)
        payload = resolved_status_service.build_status_payload()
        payload["inputRefocusDelaySeconds"] = config.input_refocus_delay_seconds
        payload["processRangeText"] = process_range_text
        return payload

    @app.get("/api/measurements/recent")
    def read_recent_measurements() -> dict[str, object]:
        return {"items": resolved_status_service.get_recent_measurements()}

    @app.post("/api/measurements")
    def create_measurement(request: MeasurementRequest) -> dict[str, object]:
        normalized_qr_code = request.qr_code.strip()
        if not normalized_qr_code:
            raise HTTPException(status_code=400, detail="QR code is required.")

        try:
            serial_number = SerialNumber(normalized_qr_code)
            measurement = resolved_measurement_recorder.measure_and_log(serial_number, trigger="web_ui")
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except MeasurementExecutionError as error:
            application_logger.exception("Measurement request failed: %s", error)
            raise HTTPException(status_code=503, detail=str(error)) from error

        return {
            "measurement": measurement.to_payload(),
            "recent": resolved_status_service.get_recent_measurements(),
            "status": {
                **resolved_status_service.build_status_payload(),
                "inputRefocusDelaySeconds": config.input_refocus_delay_seconds,
                "processRangeText": process_range_text,
            },
        }

    return app


def _build_process_range_text(config: AppConfig) -> str:
    minimum_display_value = Decimal(str(config.pass_min_raw_value)) / Decimal("100")
    maximum_display_value = Decimal(str(config.pass_max_raw_value)) / Decimal("100")
    return f"공정 한계 : {minimum_display_value:.2f}mA ~ {maximum_display_value:.2f}mA"
