from __future__ import annotations

import logging
import math
import time
from datetime import datetime
from decimal import Decimal
from threading import Lock

from .config import AppConfig
from .domain import MeasurementMode, MeasurementRecord, MeasurementThreshold, SerialNumber
from .logger import MeasurementCsvLogger
from .serial_reader import SerialCommunicationError, WatanabeA7212Reader
from .sigma_studio import SigmaStudioDownloader, SigmaStudioSettings
from .status_service import MeasurementStatusService


class MeasurementExecutionError(Exception):
    pass


class MeasurementSessionCancelledError(MeasurementExecutionError):
    pass


def build_measurement_threshold(config: AppConfig) -> MeasurementThreshold:
    return MeasurementThreshold(
        minimum_raw_value=Decimal(str(config.pass_min_raw_value)),
        maximum_raw_value=Decimal(str(config.sigmastudio_pass_max_raw_value)),
    )


def build_threshold_by_mode(config: AppConfig) -> dict[MeasurementMode, MeasurementThreshold]:
    return {
        MeasurementMode.SIGMASTUDIO: MeasurementThreshold(
            minimum_raw_value=Decimal(str(config.pass_min_raw_value)),
            maximum_raw_value=Decimal(str(config.sigmastudio_pass_max_raw_value)),
        ),
        MeasurementMode.ANALOG: MeasurementThreshold(
            minimum_raw_value=Decimal(str(config.pass_min_raw_value)),
            maximum_raw_value=Decimal(str(config.analog_pass_max_raw_value)),
        ),
    }


def build_delay_by_mode(config: AppConfig) -> dict[MeasurementMode, int]:
    return {
        MeasurementMode.SIGMASTUDIO: config.sigmastudio_measurement_delay_seconds,
        MeasurementMode.ANALOG: config.analog_measurement_delay_seconds,
    }


class MeasurementRecorder:
    def __init__(
        self,
        instrument_reader: WatanabeA7212Reader,
        measurement_logger: MeasurementCsvLogger,
        measurement_threshold_by_mode: dict[MeasurementMode, MeasurementThreshold],
        application_logger: logging.Logger,
        status_service: MeasurementStatusService | None = None,
        sigma_studio_downloader: SigmaStudioDownloader | None = None,
        download_trigger_raw_value: int = 100,
        download_trigger_confirm_count: int = 3,
        trigger_poll_interval_seconds: float = 0.2,
        measurement_delay_by_mode: dict[MeasurementMode, int] | None = None,
        default_measurement_mode: MeasurementMode = MeasurementMode.SIGMASTUDIO,
        sleeper=time.sleep,
    ) -> None:
        self._instrument_reader = instrument_reader
        self._measurement_logger = measurement_logger
        self._measurement_threshold_by_mode = measurement_threshold_by_mode
        self._application_logger = application_logger
        self._status_service = status_service
        self._sigma_studio_downloader = sigma_studio_downloader
        self._download_trigger_raw_value = Decimal(str(download_trigger_raw_value))
        self._download_trigger_confirm_count = download_trigger_confirm_count
        self._trigger_poll_interval_seconds = trigger_poll_interval_seconds
        self._measurement_delay_by_mode = measurement_delay_by_mode or {
            MeasurementMode.SIGMASTUDIO: 0,
            MeasurementMode.ANALOG: 0,
        }
        self._default_measurement_mode = default_measurement_mode
        self._sleeper = sleeper
        self._processing_lock = Lock()

    def measure_and_log(
        self,
        serial_number: SerialNumber,
        trigger: str,
        measurement_mode: MeasurementMode | str | None = None,
    ) -> MeasurementRecord:
        with self._processing_lock:
            resolved_mode = self._resolve_mode(measurement_mode)
            self._update_selected_mode(resolved_mode)
            self._begin_session(resolved_mode, serial_number)
            try:
                self._mark_waiting_for_trigger(serial_number)
                self._wait_for_download_trigger()
                self._run_sigma_studio_download(resolved_mode)
                measurement_delay_seconds = self._measurement_delay_by_mode[resolved_mode]
                if measurement_delay_seconds > 0:
                    self._wait_for_measurement_delay(measurement_delay_seconds)

                self._raise_if_session_cancel_requested()
                self._mark_measurement_started()

                try:
                    current_reading = self._instrument_reader.read_current()
                except SerialCommunicationError as error:
                    self._update_com_status(False)
                    self._mark_error("Serial measurement failed.")
                    raise MeasurementExecutionError("Serial measurement failed.") from error

                record = MeasurementRecord(
                    measured_at=datetime.now().astimezone(),
                    serial_number=serial_number,
                    current_reading=current_reading,
                    result=self._measurement_threshold_by_mode[resolved_mode].classify(current_reading),
                    mode=resolved_mode,
                )

                try:
                    self._measurement_logger.append(record)
                except OSError as error:
                    self._mark_error("Failed to append measurement log.")
                    raise MeasurementExecutionError("Failed to append measurement log.") from error

                self._update_com_status(True)
                if self._status_service is not None:
                    self._status_service.record_measurement(record)

                self._application_logger.info(
                    "Measurement saved | trigger=%s | qr_code=%s | raw_current=%s | current_mA=%s | result=%s",
                    trigger,
                    serial_number.as_text(),
                    current_reading.as_text(),
                    current_reading.as_display_text(),
                    record.result.value,
                )
                return record
            except MeasurementSessionCancelledError:
                self._mark_session_cancelled()
                raise
            finally:
                self._finish_session()

    def _resolve_mode(self, measurement_mode: MeasurementMode | str | None) -> MeasurementMode:
        if measurement_mode is None:
            return self._default_measurement_mode

        if isinstance(measurement_mode, MeasurementMode):
            return measurement_mode

        try:
            return MeasurementMode(measurement_mode)
        except ValueError as error:
            raise MeasurementExecutionError(f"Unsupported measurement mode: {measurement_mode}") from error

    def _update_selected_mode(self, measurement_mode: MeasurementMode) -> None:
        if self._status_service is None:
            return

        self._status_service.set_selected_mode(measurement_mode)

    def _begin_session(self, measurement_mode: MeasurementMode, serial_number: SerialNumber) -> None:
        if self._status_service is None:
            return

        self._status_service.begin_session(measurement_mode, serial_number)

    def _mark_waiting_for_trigger(self, serial_number: SerialNumber) -> None:
        if self._status_service is None:
            return

        self._status_service.mark_waiting_for_trigger(serial_number)

    def _finish_session(self) -> None:
        if self._status_service is None:
            return

        self._status_service.finish_session()

    def _mark_measurement_started(self) -> None:
        if self._status_service is None:
            return

        self._status_service.mark_measurement_started()

    def _mark_session_cancelled(self) -> None:
        if self._status_service is None:
            return

        self._status_service.mark_session_cancelled()

    def _mark_error(self, message: str) -> None:
        if self._status_service is None:
            return

        self._status_service.mark_error(message)

    def cancel_current_session(self) -> bool:
        if self._status_service is None:
            return False

        return self._status_service.request_session_cancel()

    def _raise_if_session_cancel_requested(self) -> None:
        if self._status_service is None:
            return

        if not self._status_service.is_session_cancel_requested():
            return

        self._application_logger.info("Measurement session cancelled by operator request.")
        raise MeasurementSessionCancelledError("Measurement session cancelled.")

    def _wait_for_download_trigger(self) -> None:
        consecutive_match_count = 0

        while True:
            self._raise_if_session_cancel_requested()

            try:
                current_reading = self._instrument_reader.read_current()
            except SerialCommunicationError as error:
                self._update_com_status(False)
                self._mark_error("Failed while waiting for product connection current threshold.")
                raise MeasurementExecutionError(
                    "Failed while waiting for product connection current threshold."
                ) from error

            self._update_com_status(True)
            if current_reading.milliampere >= self._download_trigger_raw_value:
                consecutive_match_count += 1
                if consecutive_match_count >= self._download_trigger_confirm_count:
                    self._application_logger.info(
                        "Download trigger detected | raw_current=%s | threshold=%s | confirmations=%s",
                        current_reading.as_text(),
                        format(self._download_trigger_raw_value, "f"),
                        self._download_trigger_confirm_count,
                    )
                    return
            else:
                consecutive_match_count = 0

            self._sleeper(self._trigger_poll_interval_seconds)

    def _wait_for_measurement_delay(self, measurement_delay_seconds: int) -> None:
        remaining_seconds = float(measurement_delay_seconds)
        sleep_interval_seconds = max(0.1, float(self._trigger_poll_interval_seconds))
        last_reported_remaining_seconds = max(0, int(math.ceil(remaining_seconds)))

        if self._status_service is not None:
            self._status_service.mark_measurement_delay_started(last_reported_remaining_seconds)

        while remaining_seconds > 0:
            self._raise_if_session_cancel_requested()
            current_sleep_seconds = min(remaining_seconds, sleep_interval_seconds)
            self._sleeper(current_sleep_seconds)
            remaining_seconds -= current_sleep_seconds

            current_remaining_seconds = max(0, int(math.ceil(remaining_seconds)))
            if self._status_service is not None and current_remaining_seconds != last_reported_remaining_seconds:
                last_reported_remaining_seconds = current_remaining_seconds
                self._status_service.update_measurement_delay(current_remaining_seconds)

        self._raise_if_session_cancel_requested()

    def _update_com_status(self, is_connected: bool) -> None:
        if self._status_service is None:
            return

        self._status_service.set_com_connection(
            is_connected,
            self._instrument_reader.get_active_port_name(),
        )

    def _run_sigma_studio_download(self, measurement_mode: MeasurementMode) -> None:
        if measurement_mode == MeasurementMode.ANALOG:
            if self._status_service is not None:
                self._status_service.mark_download_skipped()
            return

        if self._sigma_studio_downloader is None or self._status_service is None:
            return

        self._status_service.mark_download_started()

        try:
            download_result = self._sigma_studio_downloader.trigger_sigma_studio_download()
            if not download_result.success:
                self._status_service.mark_download_failed(
                    message=download_result.message or "⚠ 다운로드 실패",
                    mode=download_result.mode,
                )
                raise MeasurementExecutionError("SigmaStudio download failed.")

            self._status_service.mark_download_completed(
                message="✅ 다운로드 완료",
                mode=download_result.mode,
            )
        except Exception as error:
            self._application_logger.exception("SigmaStudio download failed: %s", error)
            self._status_service.mark_download_failed(
                message="⚠ 다운로드 실패",
                mode="error",
            )
            raise MeasurementExecutionError("SigmaStudio download failed.") from error


def build_measurement_recorder(
    config: AppConfig,
    application_logger: logging.Logger,
    status_service: MeasurementStatusService | None = None,
    instrument_reader: WatanabeA7212Reader | None = None,
) -> MeasurementRecorder:
    threshold_by_mode = build_threshold_by_mode(config)
    delay_by_mode = build_delay_by_mode(config)
    serial_reader = instrument_reader or WatanabeA7212Reader(config.serial_settings)
    measurement_logger = MeasurementCsvLogger(
        config.log_csv_path,
        config.log_encoding,
        threshold_by_mode[MeasurementMode.SIGMASTUDIO],
        config.legacy_log_csv_path,
    )
    sigma_studio_downloader = None
    if config.sigma_studio_dll_path is not None and config.sigma_downloader_executable_path is not None:
        sigma_studio_downloader = SigmaStudioDownloader(
            SigmaStudioSettings(
                dll_path=config.sigma_studio_dll_path,
                fallback_executable_path=config.sigma_downloader_executable_path,
                prefer_pythonnet=config.prefer_pythonnet_sigma_download,
            )
        )

    return MeasurementRecorder(
        instrument_reader=serial_reader,
        measurement_logger=measurement_logger,
        measurement_threshold_by_mode=threshold_by_mode,
        application_logger=application_logger,
        status_service=status_service,
        sigma_studio_downloader=sigma_studio_downloader,
        download_trigger_raw_value=config.download_trigger_raw_value,
        download_trigger_confirm_count=config.download_trigger_confirm_count,
        trigger_poll_interval_seconds=config.trigger_poll_interval_seconds,
        measurement_delay_by_mode=delay_by_mode,
        default_measurement_mode=config.default_measurement_mode,
    )
