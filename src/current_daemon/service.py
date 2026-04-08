from __future__ import annotations

import logging
import time
from datetime import datetime
from decimal import Decimal
from threading import Lock

from .config import AppConfig
from .domain import MeasurementRecord, MeasurementThreshold, SerialNumber
from .logger import MeasurementCsvLogger
from .serial_reader import SerialCommunicationError, WatanabeA7212Reader
from .sigma_studio import SigmaStudioDownloader, SigmaStudioSettings
from .status_service import MeasurementStatusService


class MeasurementExecutionError(Exception):
    pass


def build_measurement_threshold(config: AppConfig) -> MeasurementThreshold:
    return MeasurementThreshold(
        minimum_raw_value=Decimal(str(config.pass_min_raw_value)),
        maximum_raw_value=Decimal(str(config.pass_max_raw_value)),
    )


class MeasurementRecorder:
    def __init__(
        self,
        instrument_reader: WatanabeA7212Reader,
        measurement_logger: MeasurementCsvLogger,
        measurement_threshold: MeasurementThreshold,
        application_logger: logging.Logger,
        status_service: MeasurementStatusService | None = None,
        sigma_studio_downloader: SigmaStudioDownloader | None = None,
        download_trigger_raw_value: int = 100,
        download_trigger_confirm_count: int = 3,
        trigger_poll_interval_seconds: float = 0.2,
        measurement_delay_seconds: int = 0,
        sleeper=time.sleep,
    ) -> None:
        self._instrument_reader = instrument_reader
        self._measurement_logger = measurement_logger
        self._measurement_threshold = measurement_threshold
        self._application_logger = application_logger
        self._status_service = status_service
        self._sigma_studio_downloader = sigma_studio_downloader
        self._download_trigger_raw_value = Decimal(str(download_trigger_raw_value))
        self._download_trigger_confirm_count = download_trigger_confirm_count
        self._trigger_poll_interval_seconds = trigger_poll_interval_seconds
        self._measurement_delay_seconds = measurement_delay_seconds
        self._sleeper = sleeper
        self._processing_lock = Lock()

    def measure_and_log(self, serial_number: SerialNumber, trigger: str) -> MeasurementRecord:
        with self._processing_lock:
            self._wait_for_download_trigger()
            self._run_sigma_studio_download()
            if self._measurement_delay_seconds > 0:
                self._sleeper(self._measurement_delay_seconds)

            try:
                current_reading = self._instrument_reader.read_current()
            except SerialCommunicationError as error:
                self._update_com_status(False)
                raise MeasurementExecutionError("Serial measurement failed.") from error

            record = MeasurementRecord(
                measured_at=datetime.now().astimezone(),
                serial_number=serial_number,
                current_reading=current_reading,
                result=self._measurement_threshold.classify(current_reading),
            )

            try:
                self._measurement_logger.append(record)
            except OSError as error:
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

    def _wait_for_download_trigger(self) -> None:
        consecutive_match_count = 0

        while True:
            try:
                current_reading = self._instrument_reader.read_current()
            except SerialCommunicationError as error:
                self._update_com_status(False)
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

    def _update_com_status(self, is_connected: bool) -> None:
        if self._status_service is None:
            return

        self._status_service.set_com_connection(
            is_connected,
            self._instrument_reader.get_active_port_name(),
        )

    def _run_sigma_studio_download(self) -> None:
        if self._sigma_studio_downloader is None or self._status_service is None:
            return

        try:
            download_result = self._sigma_studio_downloader.trigger_sigma_studio_download()
            self._status_service.set_download_feedback(
                success=download_result.success,
                message=download_result.message,
                mode=download_result.mode,
            )
        except Exception as error:
            self._application_logger.exception("SigmaStudio download failed: %s", error)
            self._status_service.set_download_feedback(
                success=False,
                message="⚠ 측정 완료 / 다운로드 실패",
                mode="error",
            )
            raise MeasurementExecutionError("SigmaStudio download failed.") from error


def build_measurement_recorder(
    config: AppConfig,
    application_logger: logging.Logger,
    status_service: MeasurementStatusService | None = None,
    instrument_reader: WatanabeA7212Reader | None = None,
) -> MeasurementRecorder:
    measurement_threshold = build_measurement_threshold(config)
    serial_reader = instrument_reader or WatanabeA7212Reader(config.serial_settings)
    measurement_logger = MeasurementCsvLogger(
        config.log_csv_path,
        config.log_encoding,
        measurement_threshold,
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
        measurement_threshold=measurement_threshold,
        application_logger=application_logger,
        status_service=status_service,
        sigma_studio_downloader=sigma_studio_downloader,
        download_trigger_raw_value=config.download_trigger_raw_value,
        download_trigger_confirm_count=config.download_trigger_confirm_count,
        trigger_poll_interval_seconds=config.trigger_poll_interval_seconds,
        measurement_delay_seconds=config.measurement_delay_seconds,
    )
