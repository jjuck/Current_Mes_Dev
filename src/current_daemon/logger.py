from __future__ import annotations

import csv
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from .domain import CurrentReading, MeasurementMode, MeasurementRecord, MeasurementThreshold


class MeasurementCsvLogger:
    EXPECTED_COLUMNS = ["datetime", "SN", "type", "spec", "Vop", "raw_current", "current_mA", "result"]

    def __init__(
        self,
        log_csv_path: Path,
        encoding: str,
        measurement_threshold: MeasurementThreshold,
        legacy_log_csv_path: Path | None = None,
        measurement_threshold_by_mode: dict[MeasurementMode, MeasurementThreshold] | None = None,
        default_measurement_mode: MeasurementMode = MeasurementMode.SIGMASTUDIO,
    ) -> None:
        self._log_csv_path = log_csv_path
        self._encoding = encoding
        self._measurement_threshold = measurement_threshold
        self._legacy_log_csv_path = legacy_log_csv_path
        self._measurement_threshold_by_mode = measurement_threshold_by_mode or {
            default_measurement_mode: measurement_threshold,
        }
        self._default_measurement_mode = default_measurement_mode

    def append(self, record: MeasurementRecord) -> None:
        self._log_csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_location_if_needed()
        self._migrate_legacy_header_if_needed()
        dataframe = pd.DataFrame([record.to_row()])
        should_write_header = not self._log_csv_path.exists() or self._log_csv_path.stat().st_size == 0
        dataframe.to_csv(
            self._log_csv_path,
            mode="a",
            index=False,
            header=should_write_header,
            encoding=self._encoding,
        )

    def _migrate_legacy_header_if_needed(self) -> None:
        if not self._log_csv_path.exists() or self._log_csv_path.stat().st_size == 0:
            return

        with self._log_csv_path.open("r", encoding=self._encoding, newline="") as log_file:
            reader = csv.DictReader(log_file)
            fieldnames = reader.fieldnames or []
            if fieldnames == self.EXPECTED_COLUMNS:
                return

            normalized_rows = [self._normalize_legacy_row(row) for row in reader]

        with self._log_csv_path.open("w", encoding=self._encoding, newline="") as log_file:
            writer = csv.DictWriter(log_file, fieldnames=self.EXPECTED_COLUMNS)
            writer.writeheader()
            writer.writerows(normalized_rows)

    def _migrate_legacy_location_if_needed(self) -> None:
        if self._legacy_log_csv_path is None:
            return

        if self._log_csv_path.exists() or not self._legacy_log_csv_path.exists():
            return

        self._log_csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._legacy_log_csv_path.replace(self._log_csv_path)

    def _normalize_legacy_row(self, row: dict[str, str]) -> dict[str, str]:
        serial_number = (row.get("SN") or row.get("qr_code") or row.get("serial_number") or "").strip()
        raw_current_text = (row.get("raw_current") or row.get("current_mA") or "0").strip()
        raw_current_value = self._parse_decimal(raw_current_text)
        current_reading = CurrentReading(raw_current_value, raw_current_text)
        resolved_mode = MeasurementMode.resolve_row_mode(
            type_text=row.get("type"),
            mode_text=row.get("mode"),
            trailing_values=self._legacy_extra_values(row),
            default_mode=self._default_measurement_mode,
        )
        threshold = self._measurement_threshold_by_mode[resolved_mode]
        result = (row.get("result") or "").strip() or threshold.classify(current_reading).value
        spec_text = (row.get("spec") or self._measurement_threshold_to_spec_text(threshold)).strip() or self._measurement_threshold_to_spec_text(threshold)
        vop_text = (row.get("Vop") or "8").strip() or "8"

        return {
            "datetime": (row.get("datetime") or row.get("measured_at") or "").strip(),
            "SN": serial_number,
            "type": resolved_mode.display_name,
            "spec": spec_text,
            "Vop": vop_text,
            "raw_current": current_reading.as_text(),
            "current_mA": current_reading.as_display_text(threshold.calculation_factor),
            "result": result,
        }

    @staticmethod
    def _legacy_extra_values(row: dict[str, str]) -> list[str]:
        extra_values = row.get(None) or []
        if isinstance(extra_values, list):
            return [str(value).strip() for value in extra_values if str(value).strip()]

        normalized = str(extra_values).strip()
        return [normalized] if normalized else []

    @staticmethod
    def _measurement_threshold_to_spec_text(threshold: MeasurementThreshold) -> str:
        return threshold.spec_text()

    @staticmethod
    def _parse_decimal(value: str) -> Decimal:
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return Decimal("0")


def build_console_logger() -> logging.Logger:
    logger = logging.getLogger("current_measurement_daemon")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    logger.addHandler(handler)
    return logger
