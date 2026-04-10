from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import serial


MeasurementMode = Literal["sigmastudio", "analog"]


@dataclass(frozen=True)
class SerialSettings:
    port: str | None = None
    baudrate: int = 9600
    bytesize: int = serial.SEVENBITS
    parity: str = serial.PARITY_EVEN
    stopbits: float = serial.STOPBITS_TWO
    timeout_seconds: float = 2.0
    command: bytes = b"MES\r\n"


@dataclass(frozen=True)
class AppConfig:
    log_csv_path: Path
    log_encoding: str
    serial_settings: SerialSettings
    default_measurement_mode: MeasurementMode = "sigmastudio"
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    pass_min_raw_value: int = 10
    sigmastudio_pass_max_raw_value: int = 2000
    analog_pass_max_raw_value: int = 1000
    download_trigger_raw_value: int = 100
    download_trigger_confirm_count: int = 3
    trigger_poll_interval_seconds: float = 0.2
    recent_measurement_limit: int = 10
    input_refocus_delay_seconds: int = 1
    sigmastudio_measurement_delay_seconds: int = 8
    analog_measurement_delay_seconds: int = 1
    legacy_log_csv_path: Path | None = None
    logo_asset_path: Path | None = None
    sigma_studio_dll_path: Path | None = None
    sigma_downloader_executable_path: Path | None = None
    prefer_pythonnet_sigma_download: bool = True


def build_config() -> AppConfig:
    """이 함수 한 곳에서 운영 환경 경로와 COM 포트를 수정합니다."""
    project_root = Path(__file__).resolve().parents[2]

    return AppConfig(
        log_csv_path=project_root / "logs" / "current_measurement_log.csv",
        log_encoding="utf-8-sig",
        serial_settings=SerialSettings(),
        default_measurement_mode="sigmastudio",
        web_host="127.0.0.1",
        web_port=8000,
        pass_min_raw_value=10,
        sigmastudio_pass_max_raw_value=2000,
        analog_pass_max_raw_value=1000,
        download_trigger_raw_value=100,
        download_trigger_confirm_count=3,
        trigger_poll_interval_seconds=0.2,
        recent_measurement_limit=10,
        input_refocus_delay_seconds=1,
        sigmastudio_measurement_delay_seconds=8,
        analog_measurement_delay_seconds=1,
        legacy_log_csv_path=project_root / "current_measurement_log.csv",
        logo_asset_path=project_root / "web" / "assets" / "logo.png",
        sigma_studio_dll_path=Path(r"C:\Program Files\Analog Devices\SigmaStudio 4.6\Analog.SigmaStudioServer.dll"),
        sigma_downloader_executable_path=project_root / "SigmaDownloader.exe",
        prefer_pythonnet_sigma_download=True,
    )
