import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from src.current_daemon.config import AppConfig, SerialSettings
from src.current_daemon.domain import CurrentReading, MeasurementMode, MeasurementRecord, MeasurementResult, SerialNumber
from src.current_daemon.service import MeasurementExecutionError
from src.current_daemon.web_api import create_web_app


class FakeMeasurementRecorder:
    def __init__(
        self,
        record: MeasurementRecord | None = None,
        should_fail: bool = False,
        cancel_handler=None,
    ) -> None:
        self._record = record
        self._should_fail = should_fail
        self._cancel_handler = cancel_handler
        self.calls = []
        self.cancel_calls = 0

    def measure_and_log(self, serial_number: SerialNumber, trigger: str, measurement_mode=None) -> MeasurementRecord:
        self.calls.append((serial_number.as_text(), trigger, measurement_mode))
        if self._should_fail:
            raise MeasurementExecutionError("Serial measurement failed.")

        return self._record

    def cancel_current_session(self) -> bool:
        self.cancel_calls += 1
        if self._cancel_handler is not None:
            return self._cancel_handler()

        return True


class FakeStatusService:
    def __init__(self) -> None:
        self.com_connected = False
        self.items = []
        self.last_measurement = None
        self.last_download = None
        self.selected_mode = MeasurementMode.SIGMASTUDIO.value
        self.session_active = False
        self.session_cancellation_requested = False
        self.phase = "idle"
        self.remaining_seconds = None
        self.current_serial = None
        self._subscribers = []

    def get_recent_measurements(self):
        return self.items

    def _mode_label(self) -> str:
        return "Analog" if self.selected_mode == MeasurementMode.ANALOG.value else "Digital"

    def _idle_feedback(self) -> str:
        if self.selected_mode == MeasurementMode.ANALOG.value:
            return "Analog 측정 상태가 여기에 표시됩니다."

        return "Digital 다운로드/측정 상태가 여기에 표시됩니다."

    def _broadcast(self) -> None:
        payload = self.build_status_payload()
        for loop, queue in self._subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, payload)

    def set_com_connection(self, is_connected: bool, port_name: str | None = None) -> None:
        self.com_connected = is_connected
        self._broadcast()

    def set_selected_mode(self, mode) -> None:
        self.selected_mode = str(mode)
        self._broadcast()

    def begin_session(self, mode, serial_number=None) -> None:
        self.selected_mode = str(mode)
        self.session_active = True
        self.session_cancellation_requested = False
        self.phase = "waiting_for_trigger"
        self.current_serial = serial_number.as_text() if serial_number is not None else None
        self._broadcast()

    def finish_session(self) -> None:
        self.session_active = False
        self.session_cancellation_requested = False
        self._broadcast()

    def request_session_cancel(self) -> bool:
        if not self.session_active:
            return False

        self.session_cancellation_requested = True
        self._broadcast()
        return True

    def register_subscriber(self):
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        self._subscribers.append((loop, queue))
        queue.put_nowait(self.build_status_payload())
        return queue

    def unregister_subscriber(self, queue) -> None:
        self._subscribers = [subscriber for subscriber in self._subscribers if subscriber[1] is not queue]

    def build_status_payload(self):
        latest_feedback_message = self._idle_feedback()
        feedback_messages = []
        if self.last_download and self.last_download.get("message"):
            feedback_messages.append(self.last_download["message"])
            latest_feedback_message = self.last_download["message"]

        return {
            "comConnected": self.com_connected,
            "comLabel": "COM4 CONNECTED" if self.com_connected else "COM DISCONNECTED",
            "comPortName": "COM4" if self.com_connected else None,
            "lastMeasurement": self.last_measurement,
            "lastDownload": self.last_download,
            "recentMeasurements": self.items,
            "selectedMode": self.selected_mode,
            "modeLabel": self._mode_label(),
            "phase": self.phase,
            "phaseLabel": self.phase.replace("_", " ").upper(),
            "remainingSeconds": self.remaining_seconds,
            "currentSerial": self.current_serial,
            "retainLastMeasurement": True,
            "sessionActive": self.session_active,
            "sessionCancellationRequested": self.session_cancellation_requested,
            "lastError": None,
            "downloadStep": {"status": self.last_download["status"], "message": self.last_download["message"]} if self.last_download else {"status": "idle", "message": None},
            "measurementStep": {"status": "completed", "message": "✅ 측정 완료"} if self.last_measurement else {"status": "idle", "message": None},
            "feedbackMessages": feedback_messages,
            "latestFeedbackMessage": latest_feedback_message,
            "activity": {
                "title": "WAITING" if self.phase == "idle" else self.phase.replace("_", " ").upper(),
                "message": "스캔 대기 중 / Ready for next measurement",
                "symbol": "⌛",
                "tone": "idle",
                "phaseLabel": self.phase.replace("_", " ").upper(),
            },
            "displayMeasurement": {
                "serialNumber": self.current_serial or (self.last_measurement["qr_code"] if self.last_measurement else "-"),
                "currentMilliampere": self.last_measurement["current_mA"] if self.last_measurement else "0.00",
                "resultText": self.last_measurement["result"] if self.last_measurement else "WAITING",
                "resultTone": "pass" if self.last_measurement and self.last_measurement["result"] == "PASS" else ("fail" if self.last_measurement else "idle"),
            },
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
        default_measurement_mode=MeasurementMode.SIGMASTUDIO,
        web_host="127.0.0.1",
        web_port=8000,
        pass_min_raw_value=10,
        sigmastudio_pass_max_raw_value=2000,
        analog_pass_max_raw_value=1000,
        download_trigger_raw_value=100,
        download_trigger_confirm_count=3,
        trigger_poll_interval_seconds=0.2,
        recent_measurement_limit=10,
        input_refocus_delay_seconds=1,
        sigmastudio_measurement_delay_seconds=8,
        analog_measurement_delay_seconds=1,
        legacy_log_csv_path=tmp_path / "current_measurement_log.csv",
        logo_asset_path=tmp_path / "web" / "assets" / "logo.png",
        sigma_studio_dll_path=tmp_path / "Analog.SigmaStudioServer.dll",
        sigma_downloader_executable_path=tmp_path / "SigmaDownloader.exe",
        prefer_pythonnet_sigma_download=True,
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
        mode=MeasurementMode.SIGMASTUDIO,
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
    assert response.json()["selectedMode"] == "sigmastudio"
    assert response.json()["inputRefocusDelaySeconds"] == 1
    assert response.json()["processRangeText"] == "공정 한계 : 0.10mA ~ 20.00mA"


def test_measurement_response_includes_download_feedback_from_status(tmp_path: Path) -> None:
    measurement_record = MeasurementRecord(
        measured_at=datetime(2026, 4, 1, 10, 0, 0),
        serial_number=SerialNumber("SN-001"),
        current_reading=CurrentReading(Decimal("1784"), "1784"),
        result=MeasurementResult.PASS,
        mode=MeasurementMode.SIGMASTUDIO,
    )
    fake_status_service = FakeStatusService()
    fake_status_service.items = [measurement_record.to_payload()]
    fake_status_service.last_measurement = measurement_record.to_payload()
    fake_status_service.last_download = {
        "success": True,
        "message": "✅ 다운로드 완료",
        "mode": "pythonnet",
        "status": "completed",
    }
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
    assert response.json()["status"]["latestFeedbackMessage"] == "✅ 다운로드 완료"


def test_measurement_endpoint_accepts_analog_mode_and_returns_analog_range_text(tmp_path: Path) -> None:
    measurement_record = MeasurementRecord(
        measured_at=datetime(2026, 4, 1, 10, 0, 0),
        serial_number=SerialNumber("SN-ANALOG"),
        current_reading=CurrentReading(Decimal("1000"), "1000"),
        result=MeasurementResult.PASS,
        mode=MeasurementMode.ANALOG,
    )
    fake_status_service = FakeStatusService()
    fake_status_service.items = [measurement_record.to_payload()]
    fake_status_service.last_measurement = measurement_record.to_payload()
    fake_status_service.selected_mode = MeasurementMode.ANALOG.value
    measurement_recorder = FakeMeasurementRecorder(record=measurement_record)
    app = create_web_app(
        config=build_config(tmp_path),
        application_logger=logging.getLogger("test.web_api.analog"),
        measurement_recorder=measurement_recorder,
        status_service=fake_status_service,
        instrument_reader=FakeInstrumentReader(connected=True),
        web_root=build_web_root(tmp_path),
    )
    fake_status_service.selected_mode = MeasurementMode.ANALOG.value
    client = TestClient(app)

    response = client.post("/api/measurements", json={"qr_code": "SN-ANALOG", "mode": "analog"})

    assert response.status_code == 200
    assert measurement_recorder.calls[0][2] == MeasurementMode.ANALOG
    assert response.json()["status"]["processRangeText"] == "공정 한계 : 0.10mA ~ 10.00mA"


def test_mode_update_endpoint_updates_selected_mode_and_returns_status(tmp_path: Path) -> None:
    fake_status_service = FakeStatusService()
    app = create_web_app(
        config=build_config(tmp_path),
        application_logger=logging.getLogger("test.web_api.mode"),
        measurement_recorder=FakeMeasurementRecorder(),
        status_service=fake_status_service,
        instrument_reader=FakeInstrumentReader(connected=True),
        web_root=build_web_root(tmp_path),
    )
    client = TestClient(app)

    response = client.post("/api/status/mode", json={"mode": "analog"})

    assert response.status_code == 200
    assert fake_status_service.selected_mode == MeasurementMode.ANALOG.value
    assert response.json()["status"]["processRangeText"] == "공정 한계 : 0.10mA ~ 10.00mA"


def test_cancel_session_endpoint_requests_cancellation_and_returns_status(tmp_path: Path) -> None:
    measurement_record = MeasurementRecord(
        measured_at=datetime(2026, 4, 1, 10, 0, 0),
        serial_number=SerialNumber("SN-CANCEL"),
        current_reading=CurrentReading(Decimal("1200"), "1200"),
        result=MeasurementResult.PASS,
        mode=MeasurementMode.SIGMASTUDIO,
    )
    fake_status_service = FakeStatusService()
    fake_status_service.begin_session(MeasurementMode.SIGMASTUDIO)
    measurement_recorder = FakeMeasurementRecorder(
        record=measurement_record,
        cancel_handler=fake_status_service.request_session_cancel,
    )
    app = create_web_app(
        config=build_config(tmp_path),
        application_logger=logging.getLogger("test.web_api.cancel"),
        measurement_recorder=measurement_recorder,
        status_service=fake_status_service,
        instrument_reader=FakeInstrumentReader(connected=True),
        web_root=build_web_root(tmp_path),
    )
    client = TestClient(app)

    response = client.post("/api/session/cancel")

    assert response.status_code == 200
    assert measurement_recorder.cancel_calls == 1
    assert response.json()["cancelRequested"] is True
    assert response.json()["status"]["sessionCancellationRequested"] is True


def test_status_websocket_sends_initial_status_and_broadcast_updates(tmp_path: Path) -> None:
    fake_status_service = FakeStatusService()
    app = create_web_app(
        config=build_config(tmp_path),
        application_logger=logging.getLogger("test.web_api.websocket"),
        measurement_recorder=FakeMeasurementRecorder(),
        status_service=fake_status_service,
        instrument_reader=FakeInstrumentReader(connected=True),
        web_root=build_web_root(tmp_path),
    )
    client = TestClient(app)

    with client.websocket_connect("/ws/status") as websocket:
        initial_payload = websocket.receive_json()
        assert initial_payload["comConnected"] is True
        assert initial_payload["phase"] == "idle"

        fake_status_service.begin_session(MeasurementMode.ANALOG, SerialNumber("SN-WS"))
        updated_payload = websocket.receive_json()

        assert updated_payload["selectedMode"] == MeasurementMode.ANALOG.value
        assert updated_payload["phase"] == "waiting_for_trigger"
        assert updated_payload["currentSerial"] == "SN-WS"


def test_web_assets_include_cancel_controls_and_reset_flow() -> None:
    index_html = Path("web/index.html").read_text(encoding="utf-8")
    script = Path("web/app.js").read_text(encoding="utf-8")

    assert 'id="cancel-session-button"' in index_html
    assert 'id="reset-session-button"' in index_html
    assert 'id="ws-badge"' in index_html
    assert "/api/session/cancel" in script
    assert "/ws/status" in script
    assert "connectStatusSocket" in script
    assert "/api/status/mode" in script
