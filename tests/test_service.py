import logging
from decimal import Decimal

import pytest

from src.current_daemon.domain import CurrentReading, MeasurementResult, MeasurementThreshold, SerialNumber
from src.current_daemon.service import MeasurementExecutionError, MeasurementRecorder


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
        self.download_feedback = None

    def set_com_connection(self, is_connected: bool, port_name: str | None = None) -> None:
        self.connected = is_connected

    def record_measurement(self, record) -> None:
        self.records.append(record)

    def set_download_feedback(self, success: bool, message: str, mode: str) -> None:
        self.download_feedback = {"success": success, "message": message, "mode": mode}


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
    recorder = MeasurementRecorder(
        instrument_reader=instrument_reader,
        measurement_logger=FakeMeasurementLogger(),
        measurement_threshold=MeasurementThreshold(Decimal("10"), Decimal("2000")),
        application_logger=logging.getLogger("test.measurement_recorder.pass"),
        status_service=FakeStatusService(),
        sigma_studio_downloader=sigma_downloader,
        measurement_delay_seconds=8,
        sleeper=sleeper,
    )

    record = recorder.measure_and_log(SerialNumber("SN-001"), trigger="test")

    assert record.result == MeasurementResult.PASS
    assert record.current_reading.as_display_text() == "20.00"
    assert sigma_downloader.calls == 1
    assert sleeper.calls == [0.2, 0.2, 8]
    assert instrument_reader.read_count == 4


def test_measurement_recorder_raises_when_serial_measurement_fails() -> None:
    recorder = MeasurementRecorder(
        instrument_reader=FakeInstrumentReader(should_fail=True),
        measurement_logger=FakeMeasurementLogger(),
        measurement_threshold=MeasurementThreshold(Decimal("10"), Decimal("2000")),
        application_logger=logging.getLogger("test.measurement_recorder.fail"),
        status_service=FakeStatusService(),
        sleeper=FakeSleeper(),
    )

    with pytest.raises(MeasurementExecutionError):
        recorder.measure_and_log(SerialNumber("SN-ERR"), trigger="test")


def test_measurement_recorder_sets_download_failure_feedback_when_sigma_download_fails() -> None:
    status_service = FakeStatusService()
    measurement_logger = FakeMeasurementLogger()
    recorder = MeasurementRecorder(
        instrument_reader=FakeInstrumentReader(CurrentReading(Decimal("1784"), "1784")),
        measurement_logger=measurement_logger,
        measurement_threshold=MeasurementThreshold(Decimal("10"), Decimal("2000")),
        application_logger=logging.getLogger("test.measurement_recorder.download"),
        status_service=status_service,
        sigma_studio_downloader=FakeSigmaStudioDownloader(should_fail=True),
        sleeper=FakeSleeper(),
    )

    with pytest.raises(MeasurementExecutionError):
        recorder.measure_and_log(SerialNumber("SN-DL"), trigger="test")

    assert status_service.download_feedback["success"] is False
    assert status_service.download_feedback["message"] == "⚠ 측정 완료 / 다운로드 실패"
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
        measurement_threshold=MeasurementThreshold(Decimal("10"), Decimal("2000")),
        application_logger=logging.getLogger("test.measurement_recorder.trigger"),
        status_service=FakeStatusService(),
        sigma_studio_downloader=sigma_downloader,
        download_trigger_raw_value=100,
        download_trigger_confirm_count=3,
        trigger_poll_interval_seconds=0.2,
        measurement_delay_seconds=8,
        sleeper=sleeper,
    )

    record = recorder.measure_and_log(SerialNumber("SN-TRIGGER"), trigger="test")

    assert record.current_reading.as_text() == "1784"
    assert sigma_downloader.calls == 1
    assert sleeper.calls == [0.2, 0.2, 0.2, 8]
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
        measurement_threshold=MeasurementThreshold(Decimal("10"), Decimal("2000")),
        application_logger=logging.getLogger("test.measurement_recorder.confirmation"),
        status_service=FakeStatusService(),
        sigma_studio_downloader=sigma_downloader,
        download_trigger_raw_value=100,
        download_trigger_confirm_count=3,
        trigger_poll_interval_seconds=0.2,
        measurement_delay_seconds=8,
        sleeper=sleeper,
    )

    recorder.measure_and_log(SerialNumber("SN-CONFIRM"), trigger="test")

    assert sigma_downloader.calls == 1
    assert sleeper.calls == [0.2, 0.2, 0.2, 0.2, 8]
