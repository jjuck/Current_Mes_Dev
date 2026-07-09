import csv
from datetime import datetime
from decimal import Decimal

from src.current_daemon.domain import CurrentReading, MeasurementMode, MeasurementRecord, MeasurementResult, MeasurementThreshold, SerialNumber
from src.current_daemon.logger import MeasurementCsvLogger


def test_measurement_csv_logger_writes_date_and_type_specific_log_file(tmp_path) -> None:
    logger = MeasurementCsvLogger(
        log_csv_path=tmp_path / "logs" / "current_measurement_log.csv",
        encoding="utf-8-sig",
        measurement_threshold=MeasurementThreshold(Decimal("10"), Decimal("2500")),
    )
    record = MeasurementRecord(
        measured_at=datetime(2026, 6, 15, 9, 30, 0),
        serial_number=SerialNumber("SN-ANCR-SENSOR"),
        current_reading=CurrentReading(Decimal("5000"), "5000"),
        result=MeasurementResult.PASS,
        mode=MeasurementMode.ANCR_SENSOR,
        calculation_factor=Decimal("0.5"),
        spec_text="25.00mA",
        vop_text="8",
    )

    logger.append(record)

    log_path = tmp_path / "logs" / "ANCRSensor" / "260615" / "260615_Current_ANCRSensor.csv"
    assert log_path.exists()
    with log_path.open("r", encoding="utf-8-sig", newline="") as log_file:
        reader = csv.DictReader(log_file)
        rows = list(reader)

    assert reader.fieldnames == [
        "datetime",
        "SN",
        "result",
        "raw_current",
        "current_mA",
        "type",
        "spec",
        "Vop",
    ]
    assert rows == [
        {
            "datetime": "2026-06-15T09:30:00",
            "SN": "SN-ANCR-SENSOR",
            "result": "PASS",
            "raw_current": "5000",
            "current_mA": "25.00",
            "type": "ANCR Sensor",
            "spec": "25.00mA",
            "Vop": "8",
        }
    ]


def test_measurement_csv_logger_rolls_over_by_measurement_date(tmp_path) -> None:
    logger = MeasurementCsvLogger(
        log_csv_path=tmp_path / "logs" / "current_measurement_log.csv",
        encoding="utf-8-sig",
        measurement_threshold=MeasurementThreshold(Decimal("10"), Decimal("2500")),
    )

    logger.append(
        MeasurementRecord(
            measured_at=datetime(2026, 6, 15, 23, 59, 59),
            serial_number=SerialNumber("SN-ONE"),
            current_reading=CurrentReading(Decimal("1000"), "1000"),
            result=MeasurementResult.PASS,
            mode=MeasurementMode.ANALOG,
            spec_text="10.00mA",
        )
    )
    logger.append(
        MeasurementRecord(
            measured_at=datetime(2026, 6, 16, 0, 0, 0),
            serial_number=SerialNumber("SN-TWO"),
            current_reading=CurrentReading(Decimal("1000"), "1000"),
            result=MeasurementResult.PASS,
            mode=MeasurementMode.ANALOG,
            spec_text="10.00mA",
        )
    )

    assert (tmp_path / "logs" / "Analog" / "260615" / "260615_Current_Analog.csv").exists()
    assert (tmp_path / "logs" / "Analog" / "260616" / "260616_Current_Analog.csv").exists()
