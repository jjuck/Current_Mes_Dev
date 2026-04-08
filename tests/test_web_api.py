import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from src.current_daemon.config import AppConfig, SerialSettings
from src.current_daemon.domain import CurrentReading, MeasurementRecord, MeasurementResult, SerialNumber
from src.current_daemon.service import MeasurementExecutionError
from src.current_daemon.web_api import create_web_app


class FakeMeasurementRecorder:
    def __init__(self, record: MeasurementRecord | None = None, should_fail: bool = False) -> None:
        self._record = record
        self._should_fail = should_fail
        self.calls = []

    def measure_and_log(self, serial_number: SerialNumber, trigger: str) -> MeasurementRecord:
        self.calls.append((serial_number.as_text(), trigger))
        if self._should_fail:
            raise MeasurementExecutionError("Serial measurement failed.")

        return self._record


class FakeStatusService:
    def __init__(self) -> None:
        self.com_connected = False
        self.items = []
        self.last_measurement = None

    def get_recent_measurements(self):
        return self.items

    def set_com_connection(self, is_connected: bool, port_name: str | None = None) -> None:
        self.com_connected = is_connected

    def build_status_payload(self):
        return {
            "comConnected": self.com_connected,
            "comLabel": "COM4 CONNECTED" if self.com_connected else "COM DISCONNECTED",
            "comPortName": "COM4" if self.com_connected else None,
            "lastMeasurement": self.last_measurement,
        }


class FakeInstrumentReader:
    def __init__(self, connected: bool, port_name: str | None = "COM4") -> None:
        self._connected = connected
        self._port_name = port_name

    def probe_connection(self) -> bool:
        return self._connected

    def probe_connection_status(self):
        class Status:
            def __init__(self, is_connected, port_name):
                self.is_connected = is_connected
                self.port_name = port_name

        return Status(self._connected, self._port_name)


def build_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        log_csv_path=tmp_path / "logs" / "current_measurement_log.csv",
        log_encoding="utf-8-sig",
        serial_settings=SerialSettings(),
        web_host="127.0.0.1",
        web_port=8000,
        pass_min_raw_value=10,
        pass_max_raw_value=2000,
        recent_measurement_limit=10,
        input_refocus_delay_seconds=1,
        legacy_log_csv_path=tmp_path / "current_measurement_log.csv",
        logo_asset_path=tmp_path / "web" / "assets" / "logo.png",
    )


def build_web_root(tmp_path: Path) -> Path:
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (web_root / "styles.css").write_text("body{}", encoding="utf-8")
    (web_root / "app.js").write_text("console.log('ok')", encoding="utf-8")
    assets_root = web_root / "assets"
    assets_root.mkdir()
    (assets_root / "logo.png").write_bytes(b"logo")
    return web_root


def test_create_measurement_endpoint_returns_measurement_payload(tmp_path: Path) -> None:
    measurement_record = MeasurementRecord(
        measured_at=datetime(2026, 4, 1, 10, 0, 0),
        serial_number=SerialNumber("SN-001"),
        current_reading=CurrentReading(Decimal("1784"), "1784"),
        result=MeasurementResult.PASS,
    )
    fake_status_service = FakeStatusService()
    fake_status_service.items = [measurement_record.to_payload()]
    app = create_web_app(
        config=build_config(tmp_path),
        application_logger=logging.getLogger("test.web_api.measurement"),
        measurement_recorder=FakeMeasurementRecorder(record=measurement_record),
        status_service=fake_status_service,
        instrument_reader=FakeInstrumentReader(connected=True),
        web_root=build_web_root(tmp_path),
    )
    client = TestClient(app)

    response = client.post("/api/measurements", json={"qr_code": " SN-001 "})

    assert response.status_code == 200
    assert response.json()["measurement"]["current_mA"] == "17.84"
    assert response.json()["measurement"]["result"] == "PASS"


def test_create_measurement_endpoint_rejects_blank_qr_code(tmp_path: Path) -> None:
    app = create_web_app(
        config=build_config(tmp_path),
        application_logger=logging.getLogger("test.web_api.blank"),
        measurement_recorder=FakeMeasurementRecorder(),
        status_service=FakeStatusService(),
        instrument_reader=FakeInstrumentReader(connected=True),
        web_root=build_web_root(tmp_path),
    )
    client = TestClient(app)

    response = client.post("/api/measurements", json={"qr_code": "   "})

    assert response.status_code == 400


def test_status_endpoint_reports_com_connection_and_refocus_delay(tmp_path: Path) -> None:
    app = create_web_app(
        config=build_config(tmp_path),
        application_logger=logging.getLogger("test.web_api.status"),
        measurement_recorder=FakeMeasurementRecorder(),
        status_service=FakeStatusService(),
        instrument_reader=FakeInstrumentReader(connected=True),
        web_root=build_web_root(tmp_path),
    )
    client = TestClient(app)

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["comConnected"] is True
    assert response.json()["comLabel"] == "COM4 CONNECTED"
    assert response.json()["inputRefocusDelaySeconds"] == 1
    assert response.json()["processRangeText"] == "공정 한계 : 0.10mA ~ 20.00mA"


def test_measurement_response_includes_download_feedback_from_status(tmp_path: Path) -> None:
    measurement_record = MeasurementRecord(
        measured_at=datetime(2026, 4, 1, 10, 0, 0),
        serial_number=SerialNumber("SN-001"),
        current_reading=CurrentReading(Decimal("1784"), "1784"),
        result=MeasurementResult.PASS,
    )
    fake_status_service = FakeStatusService()
    fake_status_service.items = [measurement_record.to_payload()]
    fake_status_service.last_measurement = measurement_record.to_payload()
    app = create_web_app(
        config=build_config(tmp_path),
        application_logger=logging.getLogger("test.web_api.download"),
        measurement_recorder=FakeMeasurementRecorder(record=measurement_record),
        status_service=fake_status_service,
        instrument_reader=FakeInstrumentReader(connected=True),
        web_root=build_web_root(tmp_path),
    )
    client = TestClient(app)

    response = client.post("/api/measurements", json={"qr_code": "SN-001"})

    assert response.status_code == 200
    assert "status" in response.json()
    assert response.json()["status"]["inputRefocusDelaySeconds"] == 1
    assert response.json()["status"]["processRangeText"] == "공정 한계 : 0.10mA ~ 20.00mA"
