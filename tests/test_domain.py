from datetime import datetime
from decimal import Decimal

from src.current_daemon.domain import CurrentReading, MeasurementRecord, MeasurementResult, MeasurementThreshold, SerialNumber


def test_current_reading_formats_display_value_from_raw_current() -> None:
    reading = CurrentReading(Decimal("2000"), "2000")

    assert reading.as_text() == "2000"
    assert reading.as_display_text() == "20.00"


def test_measurement_threshold_classifies_boundaries() -> None:
    threshold = MeasurementThreshold(Decimal("10"), Decimal("2000"))

    assert threshold.classify(CurrentReading(Decimal("10"), "10")) == MeasurementResult.PASS
    assert threshold.classify(CurrentReading(Decimal("2000"), "2000")) == MeasurementResult.PASS
    assert threshold.classify(CurrentReading(Decimal("9"), "9")) == MeasurementResult.FAIL
    assert threshold.classify(CurrentReading(Decimal("2001"), "2001")) == MeasurementResult.FAIL


def test_measurement_record_serializes_result_and_display_value() -> None:
    record = MeasurementRecord(
        measured_at=datetime(2026, 4, 1, 10, 0, 0),
        serial_number=SerialNumber("SN-2024-0812-0042"),
        current_reading=CurrentReading(Decimal("1784"), "1784"),
        result=MeasurementResult.PASS,
    )

    assert record.to_row()["current_mA"] == "17.84"
    assert record.to_row()["result"] == "PASS"
