from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

import serial
from serial.tools.list_ports import comports

from .config import SerialSettings
from .domain import CurrentReading


class SerialCommunicationError(Exception):
    pass


@dataclass(frozen=True)
class SerialPortStatus:
    is_connected: bool
    port_name: str | None


class WatanabeA7212Reader:
    def __init__(self, settings: SerialSettings) -> None:
        self._settings = settings
        self._resolved_port_name: str | None = settings.port

    def read_current(self) -> CurrentReading:
        try:
            with self._open_connection() as connection:
                connection.reset_input_buffer()
                connection.write(self._settings.command)
                connection.flush()

                response = connection.read_until(expected=b"\n")
                if not response:
                    response = connection.read(64)
        except (serial.SerialException, OSError) as error:
            raise SerialCommunicationError("Failed to communicate with the current meter.") from error

        if not response:
            raise SerialCommunicationError("No response was received from the current meter.")

        return self._parse_response(response)

    def probe_connection(self) -> bool:
        return self.probe_connection_status().is_connected

    def probe_connection_status(self) -> SerialPortStatus:
        port_name = self._detect_port_name()
        if port_name is None:
            return SerialPortStatus(is_connected=False, port_name=None)

        try:
            with self._open_connection(port_name):
                self._resolved_port_name = port_name
                return SerialPortStatus(is_connected=True, port_name=port_name)
        except (serial.SerialException, OSError):
            return SerialPortStatus(is_connected=False, port_name=port_name)

    def get_active_port_name(self) -> str | None:
        return self._resolved_port_name or self._detect_port_name()

    def _open_connection(self, port_name: str | None = None) -> serial.Serial:
        resolved_port_name = port_name or self._require_port_name()
        return serial.Serial(
            port=resolved_port_name,
            baudrate=self._settings.baudrate,
            bytesize=self._settings.bytesize,
            parity=self._settings.parity,
            stopbits=self._settings.stopbits,
            timeout=self._settings.timeout_seconds,
        )

    def _require_port_name(self) -> str:
        port_name = self._detect_port_name()
        if port_name is None:
            raise SerialCommunicationError("No COM port detected.")

        self._resolved_port_name = port_name
        return port_name

    def _detect_port_name(self) -> str | None:
        if self._resolved_port_name:
            return self._resolved_port_name

        if self._settings.port:
            self._resolved_port_name = self._settings.port
            return self._resolved_port_name

        available_ports = [port.device for port in comports() if port.device]
        if not available_ports:
            return None

        self._resolved_port_name = available_ports[0]
        return self._resolved_port_name

    @staticmethod
    def _parse_response(response: bytes) -> CurrentReading:
        decoded_response = response.decode("ascii", errors="ignore").strip()
        matched_value = re.search(r"[-+]?\d+(?:\.\d+)?", decoded_response)
        if matched_value is None:
            raise SerialCommunicationError(f"Unable to parse current value from response: {decoded_response!r}")

        return CurrentReading(
            milliampere=Decimal(matched_value.group()),
            raw_text=decoded_response,
        )
