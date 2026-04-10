from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.current_daemon.config import SerialSettings
from src.current_daemon.serial_reader import SerialCommunicationError, WatanabeA7212Reader


def test_parse_response_extracts_numeric_value() -> None:
    reading = WatanabeA7212Reader._parse_response(b"1784\r\n")

    assert reading.milliampere == Decimal("1784")
    assert reading.as_text() == "1784"


def test_parse_response_raises_when_numeric_value_is_missing() -> None:
    with pytest.raises(SerialCommunicationError):
        WatanabeA7212Reader._parse_response(b"NO DATA\r\n")


def test_auto_detect_port_selects_first_port_matching_serial_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.current_daemon.serial_reader.comports",
        lambda: [
            SimpleNamespace(device="COM1", description="Communications Port", hwid="ACPI\\PNP0501"),
            SimpleNamespace(device="COM7", description="USB Serial Device", hwid="USB VID:PID=1111:2222"),
            SimpleNamespace(device="COM8", description="Other Serial Adapter", hwid="USB VID:PID=3333:4444"),
        ],
    )

    reader = WatanabeA7212Reader(SerialSettings())

    assert reader.get_active_port_name() == "COM7"


def test_auto_detect_port_returns_none_when_no_port_contains_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.current_daemon.serial_reader.comports",
        lambda: [
            SimpleNamespace(device="COM1", description="Communications Port", hwid="ACPI\\PNP0501"),
            SimpleNamespace(device="COM2", description="PCI Port", hwid="PCI\\VEN_8086&DEV_9D3D"),
        ],
    )

    reader = WatanabeA7212Reader(SerialSettings())

    assert reader.get_active_port_name() is None


def test_manual_port_setting_takes_priority_over_auto_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.current_daemon.serial_reader.comports",
        lambda: pytest.fail("Automatic port detection should not run when a manual port is configured."),
    )

    reader = WatanabeA7212Reader(SerialSettings(port="COM9"))

    assert reader.get_active_port_name() == "COM9"
