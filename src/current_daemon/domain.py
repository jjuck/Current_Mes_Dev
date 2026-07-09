from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


@dataclass(frozen=True)
class SerialNumber:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip(" \t\r\n")
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

    def scaled_raw_value(self, calculation_factor: Decimal = Decimal("1")) -> Decimal:
        return self.milliampere * calculation_factor

    def as_display_milliampere(self, calculation_factor: Decimal = Decimal("1")) -> Decimal:
        return (self.scaled_raw_value(calculation_factor) / Decimal("100")).quantize(Decimal("0.01"))

    def as_display_text(self, calculation_factor: Decimal = Decimal("1")) -> str:
        return f"{self.as_display_milliampere(calculation_factor):.2f}"


class MeasurementResult(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class MeasurementModeFamily(StrEnum):
    DIGITAL = "digital"
    ANALOG = "analog"


class MeasurementMode(StrEnum):
    SIGMASTUDIO = "sigmastudio"
    ANALOG = "analog"

    ANCR_MIC = "ancr_mic"
    ANCR_SENSOR = "ancr_sensor"

    @property
    def display_name(self) -> str:
        if self == MeasurementMode.ANALOG:
            return "Analog"

        if self == MeasurementMode.ANCR_MIC:
            return "ANCR MIC"

        if self == MeasurementMode.ANCR_SENSOR:
            return "ANCR Sensor"

        return "Digital"

    @property
    def family(self) -> MeasurementModeFamily:
        if self in {MeasurementMode.ANALOG, MeasurementMode.ANCR_MIC}:
            return MeasurementModeFamily.ANALOG

        return MeasurementModeFamily.DIGITAL

    @property
    def requires_download(self) -> bool:
        return self.family == MeasurementModeFamily.DIGITAL

    @classmethod
    def from_value(cls, value: "MeasurementMode | str") -> "MeasurementMode":
        if isinstance(value, cls):
            return value

        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Measurement mode cannot be empty.")

        resolved_by_value = {
            cls.SIGMASTUDIO.value: cls.SIGMASTUDIO,
            cls.ANALOG.value: cls.ANALOG,
            cls.ANCR_MIC.value: cls.ANCR_MIC,
            cls.ANCR_SENSOR.value: cls.ANCR_SENSOR,
            "digital": cls.SIGMASTUDIO,
            "analog": cls.ANALOG,
            "ancr mic": cls.ANCR_MIC,
            "ancr sensor": cls.ANCR_SENSOR,
        }

        resolved_mode = resolved_by_value.get(normalized.casefold())
        if resolved_mode is None:
            raise ValueError(f"Unsupported measurement mode: {value}")

        return resolved_mode

    @classmethod
    def try_from_value(cls, value: "MeasurementMode | str | None") -> "MeasurementMode | None":
        if value is None:
            return None

        normalized = str(value).strip()
        if not normalized:
            return None

        try:
            return cls.from_value(normalized)
        except ValueError:
            return None

    @classmethod
    def resolve_row_mode(
        cls,
        *,
        type_text: str | None = None,
        mode_text: str | None = None,
        trailing_values: Iterable[str] | None = None,
        default_mode: "MeasurementMode | None" = None,
    ) -> "MeasurementMode":
        for candidate in [mode_text, type_text, *(trailing_values or [])]:
            resolved_mode = cls.try_from_value(candidate)
            if resolved_mode is not None:
                return resolved_mode

        return default_mode or cls.SIGMASTUDIO


ANCR_SENSOR_HALF_SCALE_MIN_RAW_CURRENT = Decimal("3000")


def resolve_effective_calculation_factor(
    measurement_mode: MeasurementMode,
    current_reading: CurrentReading,
    configured_factor: Decimal,
) -> Decimal:
    if (
        measurement_mode == MeasurementMode.ANCR_SENSOR
        and current_reading.milliampere < ANCR_SENSOR_HALF_SCALE_MIN_RAW_CURRENT
    ):
        return Decimal("1")

    return configured_factor


@dataclass(frozen=True)
class MeasurementThreshold:
    minimum_raw_value: Decimal
    maximum_raw_value: Decimal
    calculation_factor: Decimal = Decimal("1")

    def classify(self, current_reading: CurrentReading, calculation_factor: Decimal | None = None) -> MeasurementResult:
        effective_calculation_factor = self.calculation_factor if calculation_factor is None else calculation_factor
        scaled_raw_value = current_reading.scaled_raw_value(effective_calculation_factor)
        if self.minimum_raw_value <= scaled_raw_value <= self.maximum_raw_value:
            return MeasurementResult.PASS

        return MeasurementResult.FAIL

    def spec_text(self) -> str:
        maximum_display_value = (self.maximum_raw_value / Decimal("100")).quantize(Decimal("0.01"))
        return f"{maximum_display_value:.2f}mA"


@dataclass(frozen=True)
class MeasurementModeSpec:
    display_name: str
    family: MeasurementModeFamily
    maximum_raw_value: Decimal
    measurement_delay_seconds: int
    requires_download: bool
    calculation_factor: Decimal = Decimal("1")

    def build_threshold(self, minimum_raw_value: Decimal) -> MeasurementThreshold:
        return MeasurementThreshold(
            minimum_raw_value=minimum_raw_value,
            maximum_raw_value=self.maximum_raw_value,
            calculation_factor=self.calculation_factor,
        )

    def to_payload(self, mode: MeasurementMode, minimum_raw_value: Decimal) -> dict[str, object]:
        minimum_display_value = (minimum_raw_value / Decimal("100")).quantize(Decimal("0.01"))
        maximum_display_value = (self.maximum_raw_value / Decimal("100")).quantize(Decimal("0.01"))
        return {
            "value": mode.value,
            "label": self.display_name,
            "family": self.family.value,
            "requiresDownload": self.requires_download,
            "measurementDelaySeconds": self.measurement_delay_seconds,
            "calculationFactor": format(self.calculation_factor, "f"),
            "minimumCurrent_mA": f"{minimum_display_value:.2f}",
            "maximumCurrent_mA": f"{maximum_display_value:.2f}",
        }

    def spec_text(self) -> str:
        maximum_display_value = (self.maximum_raw_value / Decimal("100")).quantize(Decimal("0.01"))
        return f"{maximum_display_value:.2f}mA"


@dataclass(frozen=True)
class MeasurementRecord:
    measured_at: datetime
    serial_number: SerialNumber
    current_reading: CurrentReading
    result: MeasurementResult
    mode: MeasurementMode
    calculation_factor: Decimal = Decimal("1")
    spec_text: str = ""
    vop_text: str = "8"

    def to_row(self) -> dict[str, str]:
        return {
            "datetime": self.measured_at.isoformat(timespec="seconds"),
            "SN": self.serial_number.as_text(),
            "result": self.result.value,
            "raw_current": self.current_reading.as_text(),
            "current_mA": self.current_reading.as_display_text(self.calculation_factor),
            "type": self.mode.display_name,
            "spec": self.spec_text,
            "Vop": self.vop_text,
        }

    def to_payload(self) -> dict[str, str]:
        return {
            "measured_at": self.measured_at.isoformat(timespec="seconds"),
            "qr_code": self.serial_number.as_text(),
            "raw_current": self.current_reading.as_text(),
            "current_mA": self.current_reading.as_display_text(self.calculation_factor),
            "result": self.result.value,
            "mode": self.mode.display_name,
        }
