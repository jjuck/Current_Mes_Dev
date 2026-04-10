import asyncio
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from src.current_daemon.domain import CurrentReading, MeasurementMode, MeasurementRecord, MeasurementResult, MeasurementThreshold, SerialNumber
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
    assert payload["modeLabel"] == "Digital"
    assert payload["activity"]["title"] == "WAITING"


def test_status_service_tracks_digital_session_feedback_and_completed_payload(tmp_path: Path) -> None:
    service = MeasurementStatusService(
        log_csv_path=tmp_path / "logs" / "current_measurement_log.csv",
        log_encoding="utf-8-sig",
        measurement_threshold=MeasurementThreshold(Decimal("10"), Decimal("2000")),
        recent_limit=10,
    )

    service.begin_session(MeasurementMode.SIGMASTUDIO, SerialNumber("SN-DIGITAL"))
    service.mark_download_started()
    service.mark_download_completed(mode="pythonnet")
    service.mark_measurement_delay_started(8)
    service.update_measurement_delay(7)
    service.record_measurement(
        MeasurementRecord(
            measured_at=datetime(2026, 4, 1, 10, 0, 0),
            serial_number=SerialNumber("SN-DIGITAL"),
            current_reading=CurrentReading(Decimal("1784"), "1784"),
            result=MeasurementResult.PASS,
            mode=MeasurementMode.SIGMASTUDIO,
        )
    )

    payload = service.build_status_payload()

    assert payload["selectedMode"] == MeasurementMode.SIGMASTUDIO.value
    assert payload["phase"] == "completed"
    assert payload["sessionActive"] is False
    assert payload["feedbackMessages"] == []
    assert payload["activity"]["message"] is None
    assert payload["displayMeasurement"]["serialNumber"] == "SN-DIGITAL"
    assert payload["displayMeasurement"]["resultTone"] == "pass"


def test_status_service_tracks_analog_session_without_download_feedback(tmp_path: Path) -> None:
    service = MeasurementStatusService(
        log_csv_path=tmp_path / "logs" / "current_measurement_log.csv",
        log_encoding="utf-8-sig",
        measurement_threshold=MeasurementThreshold(Decimal("10"), Decimal("2000")),
        recent_limit=10,
    )

    service.begin_session(MeasurementMode.ANALOG, SerialNumber("SN-ANALOG"))
    service.mark_download_skipped()
    service.mark_measurement_delay_started(1)
    service.record_measurement(
        MeasurementRecord(
            measured_at=datetime(2026, 4, 1, 10, 0, 1),
            serial_number=SerialNumber("SN-ANALOG"),
            current_reading=CurrentReading(Decimal("1000"), "1000"),
            result=MeasurementResult.PASS,
            mode=MeasurementMode.ANALOG,
        )
    )

    payload = service.build_status_payload()

    assert payload["phase"] == "completed"
    assert payload["downloadStep"]["status"] == "skipped"
    assert payload["feedbackMessages"] == []
    assert payload["activity"]["message"] is None


def test_status_service_broadcasts_initial_and_updated_payloads_to_subscribers(tmp_path: Path) -> None:
    service = MeasurementStatusService(
        log_csv_path=tmp_path / "logs" / "current_measurement_log.csv",
        log_encoding="utf-8-sig",
        measurement_threshold=MeasurementThreshold(Decimal("10"), Decimal("2000")),
        recent_limit=10,
    )

    async def scenario() -> None:
        queue = service.register_subscriber()
        initial_payload = await asyncio.wait_for(queue.get(), timeout=0.2)
        assert initial_payload["phase"] == "idle"

        service.set_selected_mode(MeasurementMode.ANALOG)
        updated_payload = await asyncio.wait_for(queue.get(), timeout=0.2)
        assert updated_payload["selectedMode"] == MeasurementMode.ANALOG.value

        service.unregister_subscriber(queue)

    asyncio.run(scenario())
