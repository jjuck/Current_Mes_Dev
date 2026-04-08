from decimal import Decimal
from pathlib import Path

from src.current_daemon.domain import MeasurementThreshold
from src.current_daemon.status_service import MeasurementStatusService


def test_status_service_loads_legacy_log_and_normalizes_recent_rows(tmp_path: Path) -> None:
    log_path = tmp_path / "current_measurement_log.csv"
    log_path.write_text(
        "measured_at,qr_code,current_mA\n"
        "2026-04-01T10:00:00,SN-001,2000\n"
        "2026-04-01T10:00:01,SN-002,2001\n",
        encoding="utf-8-sig",
    )

    service = MeasurementStatusService(
        log_csv_path=log_path,
        log_encoding="utf-8-sig",
        measurement_threshold=MeasurementThreshold(Decimal("10"), Decimal("2000")),
        recent_limit=10,
    )

    recent_items = service.get_recent_measurements()

    assert recent_items[0]["qr_code"] == "SN-002"
    assert recent_items[0]["current_mA"] == "20.01"
    assert recent_items[0]["result"] == "FAIL"
    assert recent_items[1]["result"] == "PASS"


def test_status_service_builds_port_specific_com_label(tmp_path: Path) -> None:
    service = MeasurementStatusService(
        log_csv_path=tmp_path / "logs" / "current_measurement_log.csv",
        log_encoding="utf-8-sig",
        measurement_threshold=MeasurementThreshold(Decimal("10"), Decimal("2000")),
        recent_limit=10,
    )

    service.set_com_connection(True, "COM4")

    payload = service.build_status_payload()

    assert payload["comLabel"] == "COM4 CONNECTED"
