from datetime import datetime
from decimal import Decimal

from src.current_daemon.domain import (
    CurrentReading,
    MeasurementMode,
    MeasurementRecord,
    MeasurementResult,
    MeasurementThreshold,
    SerialNumber,
    resolve_effective_calculation_factor,
)


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
        mode=MeasurementMode.SIGMASTUDIO,
    )

    assert record.to_row()["current_mA"] == "17.84"
    assert record.to_row()["result"] == "PASS"
    assert record.to_row()["SN"] == "SN-2024-0812-0042"
    assert record.to_row()["type"] == "Digital"


def test_measurement_record_serializes_csv_columns_in_log_order() -> None:
    record = MeasurementRecord(
        measured_at=datetime(2026, 4, 24, 12, 34, 56),
        serial_number=SerialNumber("SN-DATETIME"),
        current_reading=CurrentReading(Decimal("1594"), "1594"),
        result=MeasurementResult.PASS,
        mode=MeasurementMode.SIGMASTUDIO,
        spec_text="25.00mA",
    )

    row = record.to_row()

    assert list(row.keys()) == [
        "datetime",
        "SN",
        "result",
        "raw_current",
        "current_mA",
        "type",
        "spec",
        "Vop",
    ]
    assert row["datetime"] == "2026-04-24T12:34:56"


def test_measurement_threshold_applies_calculation_factor_for_ancr_sensor() -> None:
    threshold = MeasurementThreshold(
        minimum_raw_value=Decimal("10"),
        maximum_raw_value=Decimal("2500"),
        calculation_factor=Decimal("0.5"),
    )

    assert threshold.classify(CurrentReading(Decimal("5000"), "5000")) == MeasurementResult.PASS
    assert threshold.classify(CurrentReading(Decimal("5002"), "5002")) == MeasurementResult.FAIL


def test_measurement_record_serializes_ancr_sensor_with_half_scaled_display_and_label() -> None:
    record = MeasurementRecord(
        measured_at=datetime(2026, 4, 1, 10, 0, 0),
        serial_number=SerialNumber("SN-ANCR-SENSOR"),
        current_reading=CurrentReading(Decimal("5000"), "5000"),
        result=MeasurementResult.PASS,
        mode=MeasurementMode.ANCR_SENSOR,
        calculation_factor=Decimal("0.5"),
    )

    assert record.to_payload()["current_mA"] == "25.00"
    assert record.to_payload()["mode"] == "ANCR Sensor"


def test_ancr_sensor_uses_unscaled_factor_below_raw_current_3000() -> None:
    factor = resolve_effective_calculation_factor(
        MeasurementMode.ANCR_SENSOR,
        CurrentReading(Decimal("2999"), "2999"),
        Decimal("0.5"),
    )

    assert factor == Decimal("1")


def test_ancr_sensor_uses_half_factor_at_raw_current_3000() -> None:
    factor = resolve_effective_calculation_factor(
        MeasurementMode.ANCR_SENSOR,
        CurrentReading(Decimal("3000"), "3000"),
        Decimal("0.5"),
    )

    assert factor == Decimal("0.5")
