from decimal import Decimal

import pytest

from src.current_daemon.serial_reader import SerialCommunicationError, WatanabeA7212Reader


def test_parse_response_extracts_numeric_value() -> None:
    reading = WatanabeA7212Reader._parse_response(b"1784\r\n")

    assert reading.milliampere == Decimal("1784")
    assert reading.as_text() == "1784"


def test_parse_response_raises_when_numeric_value_is_missing() -> None:
    with pytest.raises(SerialCommunicationError):
        WatanabeA7212Reader._parse_response(b"NO DATA\r\n")
