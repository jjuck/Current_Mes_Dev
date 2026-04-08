from __future__ import annotations

import csv
from collections import deque
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import Lock

from .domain import CurrentReading, MeasurementRecord, MeasurementThreshold


class MeasurementStatusService:
    def __init__(
        self,
        log_csv_path: Path,
        log_encoding: str,
        measurement_threshold: MeasurementThreshold,
        recent_limit: int,
        legacy_log_csv_path: Path | None = None,
    ) -> None:
        self._log_csv_path = log_csv_path
        self._log_encoding = log_encoding
        self._measurement_threshold = measurement_threshold
        self._recent_measurements: deque[dict[str, str]] = deque(maxlen=recent_limit)
        self._last_measurement: dict[str, str] | None = None
        self._last_download: dict[str, object] | None = None
        self._com_connected = False
        self._com_port_name: str | None = None
        self._legacy_log_csv_path = legacy_log_csv_path
        self._lock = Lock()
        self._migrate_legacy_location_if_needed()
        self._load_recent_measurements()

    def record_measurement(self, record: MeasurementRecord) -> None:
        payload = record.to_payload()
        with self._lock:
            self._recent_measurements.append(payload)
            self._last_measurement = payload

    def get_recent_measurements(self) -> list[dict[str, str]]:
        with self._lock:
            return list(reversed(self._recent_measurements))

    def set_com_connection(self, is_connected: bool, port_name: str | None = None) -> None:
        with self._lock:
            self._com_connected = is_connected
            self._com_port_name = port_name

    def set_download_feedback(self, success: bool, message: str, mode: str) -> None:
        with self._lock:
            self._last_download = {
                "success": success,
                "message": message,
                "mode": mode,
            }

    def build_status_payload(self) -> dict[str, object]:
        with self._lock:
            if self._com_port_name:
                com_label = f"{self._com_port_name} {'CONNECTED' if self._com_connected else 'DISCONNECTED'}"
            else:
                com_label = "COM CONNECTED" if self._com_connected else "COM DISCONNECTED"

            return {
                "comConnected": self._com_connected,
                "comLabel": com_label,
                "comPortName": self._com_port_name,
                "lastMeasurement": self._last_measurement,
                "lastDownload": self._last_download,
            }

    def _migrate_legacy_location_if_needed(self) -> None:
        if self._legacy_log_csv_path is None:
            return

        if self._log_csv_path.exists() or not self._legacy_log_csv_path.exists():
            return

        self._log_csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._legacy_log_csv_path.replace(self._log_csv_path)

    def _load_recent_measurements(self) -> None:
        if not self._log_csv_path.exists() or self._log_csv_path.stat().st_size == 0:
            return

        with self._log_csv_path.open("r", encoding=self._log_encoding, newline="") as log_file:
            reader = csv.DictReader(log_file)
            normalized_rows = [self._normalize_row(row) for row in reader]

        for row in normalized_rows:
            self._recent_measurements.append(row)

        if normalized_rows:
            self._last_measurement = normalized_rows[-1]

    def _normalize_row(self, row: dict[str, str]) -> dict[str, str]:
        qr_code = (row.get("qr_code") or row.get("serial_number") or "").strip()
        raw_current_text = (row.get("raw_current") or row.get("current_mA") or "0").strip()
        raw_current_value = self._parse_decimal(raw_current_text)
        current_reading = CurrentReading(raw_current_value, raw_current_text)
        result = row.get("result") or self._measurement_threshold.classify(current_reading).value

        return {
            "measured_at": (row.get("measured_at") or "").strip(),
            "qr_code": qr_code,
            "raw_current": current_reading.as_text(),
            "current_mA": current_reading.as_display_text(),
            "result": result,
        }

    @staticmethod
    def _parse_decimal(value: str) -> Decimal:
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return Decimal("0")
