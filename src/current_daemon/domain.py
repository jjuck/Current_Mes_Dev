from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


@dataclass(frozen=True)
class SerialNumber:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("Serial number cannot be empty.")

        object.__setattr__(self, "value", normalized)

    def as_text(self) -> str:
        return self.value


@dataclass(frozen=True)
class CurrentReading:
    milliampere: Decimal
    raw_text: str

    def as_text(self) -> str:
        formatted_value = format(self.milliampere, "f")
        if "." not in formatted_value:
            return formatted_value

        return formatted_value.rstrip("0").rstrip(".") or "0"

    def as_display_milliampere(self) -> Decimal:
        return (self.milliampere / Decimal("100")).quantize(Decimal("0.01"))

    def as_display_text(self) -> str:
        return f"{self.as_display_milliampere():.2f}"


class MeasurementResult(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class MeasurementThreshold:
    minimum_raw_value: Decimal
    maximum_raw_value: Decimal

    def classify(self, current_reading: CurrentReading) -> MeasurementResult:
        if self.minimum_raw_value <= current_reading.milliampere <= self.maximum_raw_value:
            return MeasurementResult.PASS

        return MeasurementResult.FAIL


@dataclass(frozen=True)
class MeasurementRecord:
    measured_at: datetime
    serial_number: SerialNumber
    current_reading: CurrentReading
    result: MeasurementResult

    def to_row(self) -> dict[str, str]:
        return {
            "measured_at": self.measured_at.isoformat(timespec="seconds"),
            "qr_code": self.serial_number.as_text(),
            "raw_current": self.current_reading.as_text(),
            "current_mA": self.current_reading.as_display_text(),
            "result": self.result.value,
        }

    def to_payload(self) -> dict[str, str]:
        return {
            "measured_at": self.measured_at.isoformat(timespec="seconds"),
            "qr_code": self.serial_number.as_text(),
            "raw_current": self.current_reading.as_text(),
            "current_mA": self.current_reading.as_display_text(),
            "result": self.result.value,
        }
