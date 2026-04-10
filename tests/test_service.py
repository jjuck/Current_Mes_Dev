import logging
from decimal import Decimal

import pytest

from src.current_daemon.domain import CurrentReading, MeasurementMode, MeasurementResult, MeasurementThreshold, SerialNumber
from src.current_daemon.service import MeasurementExecutionError, MeasurementRecorder, MeasurementSessionCancelledError


class FakeInstrumentReader:
    def __init__(self, current_reading: CurrentReading | None = None, should_fail: bool = False, sequence=None) -> None:
        self._current_reading = current_reading or CurrentReading(Decimal("2000"), "2000")
        self._should_fail = should_fail
        self._port_name = "COM4"
        self._sequence = list(sequence) if sequence is not None else None
        self.read_count = 0

    def read_current(self) -> CurrentReading:
        self.read_count += 1
        if self._should_fail:
            from src.current_daemon.serial_reader import SerialCommunicationError

            raise SerialCommunicationError("boom")

        if self._sequence is not None:
            if self._sequence:
                return self._sequence.pop(0)

            return self._current_reading

        return self._current_reading

    def get_active_port_name(self) -> str:
        return self._port_name


class FakeMeasurementLogger:
    def __init__(self) -> None:
        self.records = []

    def append(self, record) -> None:
        self.records.append(record)


class FakeStatusService:
    def __init__(self) -> None:
        self.connected = None
        self.records = []
        self.last_download = None
        self.selected_mode = MeasurementMode.SIGMASTUDIO.value
        self.session_active = False
        self.cancel_requested = False
        self.phase = "idle"
        self.remaining_seconds = None
        self.current_serial = None
        self.history = []

    def _capture(self) -> None:
        self.history.append(
            {
                "phase": self.phase,
                "remainingSeconds": self.remaining_seconds,
                "sessionActive": self.session_active,
                "selectedMode": self.selected_mode,
                "lastDownload": self.last_download,
                "currentSerial": self.current_serial,
            }
        )

    def set_com_connection(self, is_connected: bool, port_name: str | None = None) -> None:
        self.connected = is_connected

    def record_measurement(self, record) -> None:
        self.records.append(record)
        self.phase = "completed"
        self.session_active = False
        self.cancel_requested = False
        self.remaining_seconds = None
        self.current_serial = record.serial_number.as_text()
        self._capture()

    def mark_download_started(self) -> None:
        self.phase = "downloading"
        self._capture()

    def mark_download_completed(self, message: str = "✅ 다운로드 완료", mode: str | None = None) -> None:
        self.last_download = {
            "success": True,
            "message": message,
            "mode": mode or self.selected_mode,
            "status": "completed",
        }
        self._capture()

    def mark_download_failed(self, message: str = "⚠ 다운로드 실패", mode: str | None = None) -> None:
        self.last_download = {
            "success": False,
            "message": message,
            "mode": mode or self.selected_mode,
            "status": "failed",
        }
        self.phase = "error"
        self.session_active = False
        self.cancel_requested = False
        self.remaining_seconds = None
        self._capture()

    def mark_download_skipped(self) -> None:
        self.last_download = {
            "success": True,
            "message": None,
            "mode": self.selected_mode,
            "status": "skipped",
        }
        self._capture()

    def set_selected_mode(self, mode) -> None:
        self.selected_mode = str(mode)
        self._capture()

    def begin_session(self, mode, serial_number=None) -> None:
        self.selected_mode = str(mode)
        self.session_active = True
        self.cancel_requested = False
        self.phase = "waiting_for_trigger"
        self.remaining_seconds = None
        self.current_serial = serial_number.as_text() if serial_number is not None else None
        self.last_download = None
        self._capture()

    def mark_waiting_for_trigger(self, serial_number=None) -> None:
        self.phase = "waiting_for_trigger"
        if serial_number is not None:
            self.current_serial = serial_number.as_text()
        self._capture()

    def mark_measurement_delay_started(self, remaining_seconds: int) -> None:
        self.phase = "waiting_for_measurement"
        self.remaining_seconds = remaining_seconds
        self._capture()

    def update_measurement_delay(self, remaining_seconds: int) -> None:
        self.phase = "waiting_for_measurement"
        self.remaining_seconds = remaining_seconds
        self._capture()

    def mark_measurement_started(self) -> None:
        self.phase = "measuring"
        self.remaining_seconds = None
        self._capture()

    def finish_session(self) -> None:
        self.session_active = False
        self.cancel_requested = False
        self.remaining_seconds = None
        if self.phase in {"waiting_for_trigger", "downloading", "waiting_for_measurement", "measuring"}:
            self.phase = "idle"
        self._capture()

    def request_session_cancel(self) -> bool:
        if not self.session_active:
            return False

        self.cancel_requested = True
        self._capture()
        return True

    def is_session_cancel_requested(self) -> bool:
        return self.cancel_requested

    def mark_session_cancelled(self, message: str = "측정이 취소되었습니다.") -> None:
        self.phase = "cancelled"
        self.session_active = False
        self.cancel_requested = False
        self.remaining_seconds = None
        self._capture()

    def mark_error(self, message: str) -> None:
        self.phase = "error"
        self.session_active = False
        self.cancel_requested = False
        self.remaining_seconds = None
        self._capture()


class FakeSigmaStudioDownloader:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls = 0

    def trigger_sigma_studio_download(self):
        self.calls += 1
        if self.should_fail:
            raise RuntimeError("sigma fail")

        class Result:
            success = True
            message = "✅ 측정 및 다운로드 완료"
            mode = "pythonnet"

        return Result()


class FakeSleeper:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, seconds: int) -> None:
        self.calls.append(seconds)


def test_measurement_recorder_returns_record_with_pass_result() -> None:
    sigma_downloader = FakeSigmaStudioDownloader()
    sleeper = FakeSleeper()
    instrument_reader = FakeInstrumentReader(CurrentReading(Decimal("2000"), "2000"))
    status_service = FakeStatusService()
    recorder = MeasurementRecorder(
        instrument_reader=instrument_reader,
        measurement_logger=FakeMeasurementLogger(),
        measurement_threshold_by_mode={
            MeasurementMode.SIGMASTUDIO: MeasurementThreshold(Decimal("10"), Decimal("2000")),
            MeasurementMode.ANALOG: MeasurementThreshold(Decimal("10"), Decimal("1000")),
        },
        application_logger=logging.getLogger("test.measurement_recorder.pass"),
        status_service=status_service,
        sigma_studio_downloader=sigma_downloader,
        measurement_delay_by_mode={
            MeasurementMode.SIGMASTUDIO: 8,
            MeasurementMode.ANALOG: 1,
        },
        sleeper=sleeper,
    )

    record = recorder.measure_and_log(SerialNumber("SN-001"), trigger="test")

    assert record.result == MeasurementResult.PASS
    assert record.current_reading.as_display_text() == "20.00"
    assert sigma_downloader.calls == 1
    assert sleeper.calls[:2] == [0.2, 0.2]
    assert sum(sleeper.calls[2:]) == pytest.approx(8)
    assert instrument_reader.read_count == 4
    assert record.mode == MeasurementMode.SIGMASTUDIO
    assert status_service.last_download["message"] == "✅ 다운로드 완료"
    assert "downloading" in [item["phase"] for item in status_service.history]
    assert "waiting_for_measurement" in [item["phase"] for item in status_service.history]
    assert "measuring" in [item["phase"] for item in status_service.history]
    assert status_service.phase == "completed"


def test_measurement_recorder_raises_when_serial_measurement_fails() -> None:
    status_service = FakeStatusService()
    recorder = MeasurementRecorder(
        instrument_reader=FakeInstrumentReader(should_fail=True),
        measurement_logger=FakeMeasurementLogger(),
        measurement_threshold_by_mode={
            MeasurementMode.SIGMASTUDIO: MeasurementThreshold(Decimal("10"), Decimal("2000")),
            MeasurementMode.ANALOG: MeasurementThreshold(Decimal("10"), Decimal("1000")),
        },
        application_logger=logging.getLogger("test.measurement_recorder.fail"),
        status_service=status_service,
        measurement_delay_by_mode={
            MeasurementMode.SIGMASTUDIO: 8,
            MeasurementMode.ANALOG: 1,
        },
        sleeper=FakeSleeper(),
    )

    with pytest.raises(MeasurementExecutionError):
        recorder.measure_and_log(SerialNumber("SN-ERR"), trigger="test")

    assert status_service.phase == "error"


def test_measurement_recorder_sets_download_failure_feedback_when_sigma_download_fails() -> None:
    status_service = FakeStatusService()
    measurement_logger = FakeMeasurementLogger()
    recorder = MeasurementRecorder(
        instrument_reader=FakeInstrumentReader(CurrentReading(Decimal("1784"), "1784")),
        measurement_logger=measurement_logger,
        measurement_threshold_by_mode={
            MeasurementMode.SIGMASTUDIO: MeasurementThreshold(Decimal("10"), Decimal("2000")),
            MeasurementMode.ANALOG: MeasurementThreshold(Decimal("10"), Decimal("1000")),
        },
        application_logger=logging.getLogger("test.measurement_recorder.download"),
        status_service=status_service,
        sigma_studio_downloader=FakeSigmaStudioDownloader(should_fail=True),
        measurement_delay_by_mode={
            MeasurementMode.SIGMASTUDIO: 8,
            MeasurementMode.ANALOG: 1,
        },
        sleeper=FakeSleeper(),
    )

    with pytest.raises(MeasurementExecutionError):
        recorder.measure_and_log(SerialNumber("SN-DL"), trigger="test")

    assert status_service.last_download["success"] is False
    assert status_service.last_download["message"] == "⚠ 다운로드 실패"
    assert status_service.phase == "error"
    assert measurement_logger.records == []


def test_measurement_recorder_waits_until_trigger_threshold_before_download() -> None:
    sleeper = FakeSleeper()
    sigma_downloader = FakeSigmaStudioDownloader()
    instrument_reader = FakeInstrumentReader(
        current_reading=CurrentReading(Decimal("1784"), "1784"),
        sequence=[
            CurrentReading(Decimal("50"), "50"),
            CurrentReading(Decimal("100"), "100"),
            CurrentReading(Decimal("100"), "100"),
            CurrentReading(Decimal("100"), "100"),
            CurrentReading(Decimal("1784"), "1784"),
        ],
    )
    recorder = MeasurementRecorder(
        instrument_reader=instrument_reader,
        measurement_logger=FakeMeasurementLogger(),
        measurement_threshold_by_mode={
            MeasurementMode.SIGMASTUDIO: MeasurementThreshold(Decimal("10"), Decimal("2000")),
            MeasurementMode.ANALOG: MeasurementThreshold(Decimal("10"), Decimal("1000")),
        },
        application_logger=logging.getLogger("test.measurement_recorder.trigger"),
        status_service=FakeStatusService(),
        sigma_studio_downloader=sigma_downloader,
        download_trigger_raw_value=100,
        download_trigger_confirm_count=3,
        trigger_poll_interval_seconds=0.2,
        measurement_delay_by_mode={
            MeasurementMode.SIGMASTUDIO: 8,
            MeasurementMode.ANALOG: 1,
        },
        sleeper=sleeper,
    )

    record = recorder.measure_and_log(SerialNumber("SN-TRIGGER"), trigger="test")

    assert record.current_reading.as_text() == "1784"
    assert sigma_downloader.calls == 1
    assert sleeper.calls[:3] == [0.2, 0.2, 0.2]
    assert sum(sleeper.calls[3:]) == pytest.approx(8)
    assert instrument_reader.read_count == 5


def test_measurement_recorder_resets_trigger_confirmation_when_value_drops_below_threshold() -> None:
    sleeper = FakeSleeper()
    sigma_downloader = FakeSigmaStudioDownloader()
    instrument_reader = FakeInstrumentReader(
        current_reading=CurrentReading(Decimal("1900"), "1900"),
        sequence=[
            CurrentReading(Decimal("100"), "100"),
            CurrentReading(Decimal("90"), "90"),
            CurrentReading(Decimal("110"), "110"),
            CurrentReading(Decimal("120"), "120"),
            CurrentReading(Decimal("130"), "130"),
            CurrentReading(Decimal("1900"), "1900"),
        ],
    )
    recorder = MeasurementRecorder(
        instrument_reader=instrument_reader,
        measurement_logger=FakeMeasurementLogger(),
        measurement_threshold_by_mode={
            MeasurementMode.SIGMASTUDIO: MeasurementThreshold(Decimal("10"), Decimal("2000")),
            MeasurementMode.ANALOG: MeasurementThreshold(Decimal("10"), Decimal("1000")),
        },
        application_logger=logging.getLogger("test.measurement_recorder.confirmation"),
        status_service=FakeStatusService(),
        sigma_studio_downloader=sigma_downloader,
        download_trigger_raw_value=100,
        download_trigger_confirm_count=3,
        trigger_poll_interval_seconds=0.2,
        measurement_delay_by_mode={
            MeasurementMode.SIGMASTUDIO: 8,
            MeasurementMode.ANALOG: 1,
        },
        sleeper=sleeper,
    )

    recorder.measure_and_log(SerialNumber("SN-CONFIRM"), trigger="test")

    assert sigma_downloader.calls == 1
    assert sleeper.calls[:4] == [0.2, 0.2, 0.2, 0.2]
    assert sum(sleeper.calls[4:]) == pytest.approx(8)


def test_measurement_recorder_skips_sigma_studio_in_analog_mode_and_uses_analog_delay() -> None:
    sigma_downloader = FakeSigmaStudioDownloader()
    sleeper = FakeSleeper()
    status_service = FakeStatusService()
    instrument_reader = FakeInstrumentReader(
        current_reading=CurrentReading(Decimal("1000"), "1000"),
        sequence=[
            CurrentReading(Decimal("100"), "100"),
            CurrentReading(Decimal("100"), "100"),
            CurrentReading(Decimal("100"), "100"),
            CurrentReading(Decimal("1000"), "1000"),
        ],
    )
    recorder = MeasurementRecorder(
        instrument_reader=instrument_reader,
        measurement_logger=FakeMeasurementLogger(),
        measurement_threshold_by_mode={
            MeasurementMode.SIGMASTUDIO: MeasurementThreshold(Decimal("10"), Decimal("2000")),
            MeasurementMode.ANALOG: MeasurementThreshold(Decimal("10"), Decimal("1000")),
        },
        application_logger=logging.getLogger("test.measurement_recorder.analog"),
        status_service=status_service,
        sigma_studio_downloader=sigma_downloader,
        download_trigger_raw_value=100,
        download_trigger_confirm_count=3,
        trigger_poll_interval_seconds=0.2,
        measurement_delay_by_mode={
            MeasurementMode.SIGMASTUDIO: 8,
            MeasurementMode.ANALOG: 1,
        },
        sleeper=sleeper,
    )

    record = recorder.measure_and_log(
        SerialNumber("SN-ANALOG"),
        trigger="test",
        measurement_mode=MeasurementMode.ANALOG,
    )

    assert record.result == MeasurementResult.PASS
    assert record.mode == MeasurementMode.ANALOG
    assert sigma_downloader.calls == 0
    assert sleeper.calls[:2] == [0.2, 0.2]
    assert sum(sleeper.calls[2:]) == pytest.approx(1)
    assert status_service.last_download["status"] == "skipped"
    assert "downloading" not in [item["phase"] for item in status_service.history]


def test_measurement_recorder_stops_when_session_cancel_requested_during_trigger_wait() -> None:
    status_service = FakeStatusService()
    sigma_downloader = FakeSigmaStudioDownloader()

    class CancelAfterFirstSleep:
        def __init__(self) -> None:
            self.calls = []

        def __call__(self, seconds: int) -> None:
            self.calls.append(seconds)
            if len(self.calls) == 1:
                status_service.request_session_cancel()

    sleeper = CancelAfterFirstSleep()
    instrument_reader = FakeInstrumentReader(
        current_reading=CurrentReading(Decimal("50"), "50"),
        sequence=[
            CurrentReading(Decimal("50"), "50"),
            CurrentReading(Decimal("50"), "50"),
        ],
    )
    recorder = MeasurementRecorder(
        instrument_reader=instrument_reader,
        measurement_logger=FakeMeasurementLogger(),
        measurement_threshold_by_mode={
            MeasurementMode.SIGMASTUDIO: MeasurementThreshold(Decimal("10"), Decimal("2000")),
            MeasurementMode.ANALOG: MeasurementThreshold(Decimal("10"), Decimal("1000")),
        },
        application_logger=logging.getLogger("test.measurement_recorder.cancel"),
        status_service=status_service,
        sigma_studio_downloader=sigma_downloader,
        download_trigger_raw_value=100,
        download_trigger_confirm_count=3,
        trigger_poll_interval_seconds=0.2,
        measurement_delay_by_mode={
            MeasurementMode.SIGMASTUDIO: 8,
            MeasurementMode.ANALOG: 1,
        },
        sleeper=sleeper,
    )

    with pytest.raises(MeasurementSessionCancelledError):
        recorder.measure_and_log(SerialNumber("SN-CANCEL"), trigger="test")

    assert sigma_downloader.calls == 0
    assert instrument_reader.read_count == 1
    assert sleeper.calls == [0.2]
    assert status_service.session_active is False
    assert status_service.cancel_requested is False
    assert status_service.phase == "cancelled"
