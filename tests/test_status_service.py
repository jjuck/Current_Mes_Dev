import asyncio
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from src.current_daemon.config import AppConfig, SerialSettings, build_measurement_mode_specs
from src.current_daemon.domain import CurrentReading, MeasurementMode, MeasurementRecord, MeasurementResult, SerialNumber
from src.current_daemon.service import build_threshold_by_mode
from src.current_daemon.status_service import MeasurementStatusService


def build_status_service(tmp_path: Path, log_name: str = "current_measurement_log.csv") -> MeasurementStatusService:
    config = AppConfig(
        log_csv_path=tmp_path / log_name,
        log_encoding="utf-8-sig",
        serial_settings=SerialSettings(),
        pass_min_raw_value=10,
        measurement_mode_specs=build_measurement_mode_specs(),
    )
    return MeasurementStatusService(
        log_csv_path=config.log_csv_path,
        log_encoding=config.log_encoding,
        measurement_threshold_by_mode=build_threshold_by_mode(config),
        measurement_mode_specs=config.measurement_mode_specs,
        recent_limit=10,
        default_measurement_mode=config.default_measurement_mode,
    )


def test_status_service_loads_legacy_log_and_normalizes_recent_rows(tmp_path: Path) -> None:
    log_path = tmp_path / "current_measurement_log.csv"
    log_path.write_text(
        "measured_at,qr_code,current_mA\n"
        "2026-04-01T10:00:00,SN-001,2000\n"
        "2026-04-01T10:00:01,SN-002,2501\n",
        encoding="utf-8-sig",
    )

    service = build_status_service(tmp_path)

    recent_items = service.get_recent_measurements()

    assert recent_items[0]["qr_code"] == "SN-002"
    assert recent_items[0]["current_mA"] == "25.01"
    assert recent_items[0]["result"] == "FAIL"
    assert recent_items[1]["result"] == "PASS"
    assert recent_items[1]["mode"] == "Digital"


def test_status_service_preserves_datetime_from_current_csv_schema(tmp_path: Path) -> None:
    log_path = tmp_path / "current_measurement_log.csv"
    log_path.write_text(
        "datetime,SN,type,spec,Vop,raw_current,current_mA,result\n"
        "2026-04-24T12:34:56,SN-DATETIME,Digital,25.00mA,8,1594,15.94,PASS\n",
        encoding="utf-8-sig",
    )

    service = build_status_service(tmp_path)

    recent_item = service.get_recent_measurements()[0]

    assert recent_item["measured_at"] == "2026-04-24T12:34:56"
    assert recent_item["SN"] == "SN-DATETIME"


def test_status_service_loads_type_and_date_partitioned_logs(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "ANCRSensor" / "260615" / "260615_Current_ANCRSensor.csv"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        "datetime,SN,result,raw_current,current_mA,type,spec,Vop\n"
        "2026-06-15T09:30:00,SN-ANCR-SENSOR,PASS,5000,25.00,ANCR Sensor,25.00mA,8\n",
        encoding="utf-8-sig",
    )

    service = build_status_service(tmp_path, "logs/current_measurement_log.csv")

    recent_item = service.get_recent_measurements()[0]

    assert recent_item["measured_at"] == "2026-06-15T09:30:00"
    assert recent_item["SN"] == "SN-ANCR-SENSOR"
    assert recent_item["type"] == "ANCR Sensor"
    assert recent_item["current_mA"] == "25.00"


def test_status_service_normalizes_ancr_sensor_rows_with_half_scaled_display(tmp_path: Path) -> None:
    log_path = tmp_path / "current_measurement_log.csv"
    log_path.write_text(
        "measured_at,qr_code,raw_current,result,mode\n"
        "2026-04-01T10:00:00,SN-ANCR-SENSOR,5000,PASS,ANCR Sensor\n",
        encoding="utf-8-sig",
    )

    service = build_status_service(tmp_path)

    recent_items = service.get_recent_measurements()

    assert recent_items[0]["mode"] == "ANCR Sensor"
    assert recent_items[0]["current_mA"] == "25.00"
    assert recent_items[0]["result"] == "PASS"


def test_status_service_restores_analog_spec_from_legacy_row_with_trailing_mode(tmp_path: Path) -> None:
    log_path = tmp_path / "current_measurement_log.csv"
    log_path.write_text(
        "measured_at,qr_code,raw_current,current_mA,result\n"
        "2026-04-10T14:42:47+09:00,SN-ANALOG,1000,10.00,PASS,analog\n",
        encoding="utf-8-sig",
    )

    service = build_status_service(tmp_path)

    recent_item = service.get_recent_measurements()[0]

    assert recent_item["mode"] == "Analog"
    assert recent_item["type"] == "Analog"
    assert recent_item["spec"] == "10.00mA"
    assert recent_item["current_mA"] == "10.00"


def test_status_service_restores_ancr_mic_spec_from_legacy_row_with_trailing_mode(tmp_path: Path) -> None:
    log_path = tmp_path / "current_measurement_log.csv"
    log_path.write_text(
        "measured_at,qr_code,raw_current,current_mA,result\n"
        "2026-04-10T15:11:18+09:00,SN-ANCR-MIC,1900,19.00,PASS,ancr_mic\n",
        encoding="utf-8-sig",
    )

    service = build_status_service(tmp_path)

    recent_item = service.get_recent_measurements()[0]

    assert recent_item["mode"] == "ANCR MIC"
    assert recent_item["type"] == "ANCR MIC"
    assert recent_item["spec"] == "19.00mA"
    assert recent_item["current_mA"] == "19.00"


def test_status_service_restores_ancr_sensor_scaling_from_legacy_row_with_trailing_mode(tmp_path: Path) -> None:
    log_path = tmp_path / "current_measurement_log.csv"
    log_path.write_text(
        "measured_at,qr_code,raw_current,current_mA,result\n"
        "2026-04-10T15:11:18+09:00,SN-ANCR-SENSOR,5000,50.00,PASS,ancr_sensor\n",
        encoding="utf-8-sig",
    )

    service = build_status_service(tmp_path)

    recent_item = service.get_recent_measurements()[0]

    assert recent_item["mode"] == "ANCR Sensor"
    assert recent_item["type"] == "ANCR Sensor"
    assert recent_item["spec"] == "25.00mA"
    assert recent_item["current_mA"] == "25.00"


def test_status_service_does_not_half_scale_ancr_sensor_rows_below_raw_current_3000(tmp_path: Path) -> None:
    log_path = tmp_path / "current_measurement_log.csv"
    log_path.write_text(
        "measured_at,qr_code,raw_current,mode\n"
        "2026-04-10T15:11:18+09:00,SN-ANCR-SENSOR-LOW,2999,ancr_sensor\n",
        encoding="utf-8-sig",
    )

    service = build_status_service(tmp_path)

    recent_item = service.get_recent_measurements()[0]

    assert recent_item["mode"] == "ANCR Sensor"
    assert recent_item["current_mA"] == "29.99"
    assert recent_item["result"] == "FAIL"


def test_status_service_builds_port_specific_com_label(tmp_path: Path) -> None:
    service = build_status_service(tmp_path, "logs/current_measurement_log.csv")

    service.set_com_connection(True, "COM4")

    payload = service.build_status_payload()

    assert payload["comLabel"] == "COM4 CONNECTED"
    assert payload["modeLabel"] == "Digital"
    assert payload["selectedModeRequiresDownload"] is True
    assert [item["label"] for item in payload["availableModes"]] == [
        "Digital",
        "Analog",
        "ANCR MIC",
        "ANCR Sensor",
    ]
    assert payload["activity"]["title"] == "WAITING"


def test_status_service_tracks_digital_session_feedback_and_completed_payload(tmp_path: Path) -> None:
    service = build_status_service(tmp_path, "logs/current_measurement_log.csv")

    service.begin_session(MeasurementMode.SIGMASTUDIO, SerialNumber("SN-DIGITAL"))
    service.mark_download_started()
    service.mark_download_completed(mode="pythonnet")
    service.mark_measurement_delay_started(5)
    service.update_measurement_delay(4)
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
    assert payload["selectedModeLabel"] == "Digital"
    assert payload["phase"] == "completed"
    assert payload["sessionActive"] is False
    assert payload["feedbackMessages"] == []
    assert payload["activity"]["message"] is None
    assert payload["displayMeasurement"]["serialNumber"] == "SN-DIGITAL"
    assert payload["displayMeasurement"]["resultTone"] == "pass"


def test_status_service_tracks_analog_session_without_download_feedback(tmp_path: Path) -> None:
    service = build_status_service(tmp_path, "logs/current_measurement_log.csv")

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
    assert payload["modeLabel"] == "Analog"
    assert payload["downloadStep"]["status"] == "skipped"
    assert payload["feedbackMessages"] == []
    assert payload["activity"]["message"] is None


def test_status_service_tracks_ancr_sensor_mode_metadata_and_scaled_display(tmp_path: Path) -> None:
    service = build_status_service(tmp_path, "logs/current_measurement_log.csv")

    service.begin_session(MeasurementMode.ANCR_SENSOR, SerialNumber("SN-ANCR-SENSOR"))
    service.mark_download_started()
    service.mark_download_completed(mode="pythonnet")
    service.mark_measurement_delay_started(5)
    service.record_measurement(
        MeasurementRecord(
            measured_at=datetime(2026, 4, 1, 10, 0, 1),
            serial_number=SerialNumber("SN-ANCR-SENSOR"),
            current_reading=CurrentReading(Decimal("5000"), "5000"),
            result=MeasurementResult.PASS,
            mode=MeasurementMode.ANCR_SENSOR,
            calculation_factor=Decimal("0.5"),
        )
    )

    payload = service.build_status_payload()

    assert payload["selectedMode"] == MeasurementMode.ANCR_SENSOR.value
    assert payload["selectedModeLabel"] == "ANCR Sensor"
    assert payload["selectedModeFamily"] == "digital"
    assert payload["selectedModeCalculationFactor"] == "0.5"
    assert payload["displayMeasurement"]["currentMilliampere"] == "25.00"


def test_status_service_records_live_measurement_with_normalized_recent_shape(tmp_path: Path) -> None:
    service = build_status_service(tmp_path, "logs/current_measurement_log.csv")

    service.record_measurement(
        MeasurementRecord(
            measured_at=datetime(2026, 4, 1, 10, 0, 1),
            serial_number=SerialNumber("SN-LIVE-ANALOG"),
            current_reading=CurrentReading(Decimal("1000"), "1000"),
            result=MeasurementResult.PASS,
            mode=MeasurementMode.ANALOG,
            spec_text="10.00mA",
        )
    )

    recent_item = service.get_recent_measurements()[0]

    assert recent_item["qr_code"] == "SN-LIVE-ANALOG"
    assert recent_item["SN"] == "SN-LIVE-ANALOG"
    assert recent_item["mode"] == "Analog"
    assert recent_item["type"] == "Analog"
    assert recent_item["spec"] == "10.00mA"
    assert recent_item["current_mA"] == "10.00"


def test_status_service_interrupt_and_reset_returns_input_ready_payload(tmp_path: Path) -> None:
    service = build_status_service(tmp_path, "logs/current_measurement_log.csv")

    session_token = service.begin_session(MeasurementMode.SIGMASTUDIO, SerialNumber("SN-RESET"))
    service.mark_download_started(session_token=session_token)

    had_active_session = service.interrupt_and_reset_session()
    payload = service.build_status_payload()

    assert had_active_session is True
    assert payload["phase"] == "idle"
    assert payload["sessionActive"] is False
    assert payload["sessionCancellationRequested"] is False
    assert payload["currentSerial"] is None
    assert payload["feedbackMessages"] == []
    assert payload["displayMeasurement"]["serialNumber"] == "-"
    assert payload["displayMeasurement"]["resultText"] == "WAITING"
    assert payload["activity"]["title"] == "WAITING"


def test_status_service_ignores_stale_updates_after_interrupt_reset(tmp_path: Path) -> None:
    service = build_status_service(tmp_path, "logs/current_measurement_log.csv")

    session_token = service.begin_session(MeasurementMode.ANALOG, SerialNumber("SN-STALE"))
    service.interrupt_and_reset_session()
    service.mark_measurement_started(session_token=session_token)
    service.mark_error("stale error", session_token=session_token)
    service.finish_session(session_token=session_token)

    payload = service.build_status_payload()

    assert payload["phase"] == "idle"
    assert payload["sessionActive"] is False
    assert payload["currentSerial"] is None
    assert payload["lastError"] is None
    assert payload["activity"]["title"] == "WAITING"


def test_status_service_broadcasts_initial_and_updated_payloads_to_subscribers(tmp_path: Path) -> None:
    service = build_status_service(tmp_path, "logs/current_measurement_log.csv")

    async def scenario() -> None:
        queue = service.register_subscriber()
        initial_payload = await asyncio.wait_for(queue.get(), timeout=0.2)
        assert initial_payload["phase"] == "idle"

        service.set_selected_mode(MeasurementMode.ANCR_MIC)
        updated_payload = await asyncio.wait_for(queue.get(), timeout=0.2)
        assert updated_payload["selectedMode"] == MeasurementMode.ANCR_MIC.value
        assert updated_payload["selectedModeLabel"] == "ANCR MIC"

        service.unregister_subscriber(queue)

    asyncio.run(scenario())
