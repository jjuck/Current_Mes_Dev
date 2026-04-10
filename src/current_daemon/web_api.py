from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import AppConfig
from .domain import MeasurementMode, SerialNumber
from .serial_reader import WatanabeA7212Reader
from .service import (
    MeasurementExecutionError,
    MeasurementRecorder,
    MeasurementSessionCancelledError,
    build_measurement_recorder,
    build_measurement_threshold,
)
from .status_service import MeasurementStatusService


class MeasurementRequest(BaseModel):
    qr_code: str
    mode: MeasurementMode = MeasurementMode.SIGMASTUDIO


class MeasurementModeRequest(BaseModel):
    mode: MeasurementMode


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
    resolved_status_service.set_selected_mode(config.default_measurement_mode)

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
        return _build_enriched_status_payload(config, resolved_status_service.build_status_payload())

    @app.post("/api/status/mode")
    def update_selected_mode(request: MeasurementModeRequest) -> dict[str, object]:
        resolved_status_service.set_selected_mode(request.mode)
        return {
            "status": _build_enriched_status_payload(config, resolved_status_service.build_status_payload()),
        }

    @app.websocket("/ws/status")
    async def stream_status(websocket: WebSocket) -> None:
        await websocket.accept()
        port_status = resolved_instrument_reader.probe_connection_status()
        resolved_status_service.set_com_connection(port_status.is_connected, port_status.port_name)
        subscriber_queue = resolved_status_service.register_subscriber()

        try:
            while True:
                payload = await subscriber_queue.get()
                await websocket.send_json(_build_enriched_status_payload(config, payload))
        except WebSocketDisconnect:
            return
        finally:
            resolved_status_service.unregister_subscriber(subscriber_queue)

    @app.get("/api/measurements/recent")
    def read_recent_measurements() -> dict[str, object]:
        return {"items": resolved_status_service.get_recent_measurements()}

    @app.post("/api/session/cancel")
    def cancel_session() -> dict[str, object]:
        cancel_requested = resolved_measurement_recorder.cancel_current_session()
        return {
            "cancelRequested": cancel_requested,
            "status": _build_enriched_status_payload(config, resolved_status_service.build_status_payload()),
        }

    @app.post("/api/measurements")
    def create_measurement(request: MeasurementRequest) -> dict[str, object]:
        normalized_qr_code = request.qr_code.strip()
        if not normalized_qr_code:
            raise HTTPException(status_code=400, detail="QR code is required.")

        try:
            serial_number = SerialNumber(normalized_qr_code)
            measurement = resolved_measurement_recorder.measure_and_log(
                serial_number,
                trigger="web_ui",
                measurement_mode=request.mode,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except MeasurementSessionCancelledError as error:
            application_logger.info("Measurement request cancelled: %s", error)
            raise HTTPException(status_code=409, detail=str(error)) from error
        except MeasurementExecutionError as error:
            application_logger.exception("Measurement request failed: %s", error)
            raise HTTPException(status_code=503, detail=str(error)) from error

        return {
            "measurement": measurement.to_payload(),
            "recent": resolved_status_service.get_recent_measurements(),
            "status": _build_enriched_status_payload(config, resolved_status_service.build_status_payload()),
        }

    return app


def _build_process_range_text(config: AppConfig, measurement_mode: MeasurementMode) -> str:
    minimum_display_value = Decimal(str(config.pass_min_raw_value)) / Decimal("100")
    if measurement_mode == MeasurementMode.ANALOG:
        maximum_raw_value = config.analog_pass_max_raw_value
    else:
        maximum_raw_value = config.sigmastudio_pass_max_raw_value

    maximum_display_value = Decimal(str(maximum_raw_value)) / Decimal("100")
    return f"공정 한계 : {minimum_display_value:.2f}mA ~ {maximum_display_value:.2f}mA"


def _build_enriched_status_payload(
    config: AppConfig,
    payload: dict[str, object],
) -> dict[str, object]:
    payload["inputRefocusDelaySeconds"] = config.input_refocus_delay_seconds
    payload["processRangeText"] = _build_process_range_text(
        config,
        MeasurementMode(payload["selectedMode"]),
    )
    return payload
