from __future__ import annotations

import asyncio
import csv
from collections import deque
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from threading import Lock
import time

from .domain import CurrentReading, MeasurementMode, MeasurementRecord, MeasurementThreshold, SerialNumber


class SessionPhase(StrEnum):
    IDLE = "idle"
    WAITING_FOR_TRIGGER = "waiting_for_trigger"
    DOWNLOADING = "downloading"
    WAITING_FOR_MEASUREMENT = "waiting_for_measurement"
    MEASURING = "measuring"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


class SessionStepStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class SessionStepState:
    status: SessionStepStatus = SessionStepStatus.IDLE
    message: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "message": self.message,
        }


@dataclass(frozen=True)
class MeasurementSessionState:
    phase: SessionPhase = SessionPhase.IDLE
    mode: MeasurementMode = MeasurementMode.SIGMASTUDIO
    active: bool = False
    cancellation_requested: bool = False
    remaining_seconds: int | None = None
    current_serial: str | None = None
    retain_last_measurement: bool = True
    clear_feedback_at: float | None = None
    last_error: str | None = None
    download_step: SessionStepState = SessionStepState()
    measurement_step: SessionStepState = SessionStepState()


@dataclass(frozen=True)
class StatusSubscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, object]]


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
        self._session_state = MeasurementSessionState()
        self._legacy_log_csv_path = legacy_log_csv_path
        self._subscribers: list[StatusSubscriber] = []
        self._lock = Lock()
        self._migrate_legacy_location_if_needed()
        self._load_recent_measurements()

    def register_subscriber(self) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=10)
        subscriber = StatusSubscriber(loop=asyncio.get_running_loop(), queue=queue)

        with self._lock:
            self._subscribers.append(subscriber)
            queue.put_nowait(self._build_status_payload_locked())

        return queue

    def unregister_subscriber(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        with self._lock:
            self._subscribers = [subscriber for subscriber in self._subscribers if subscriber.queue is not queue]

    def record_measurement(self, record: MeasurementRecord) -> None:
        payload = record.to_payload()
        with self._lock:
            self._recent_measurements.append(payload)
            self._last_measurement = payload
            self._session_state = replace(
                self._session_state,
                phase=SessionPhase.COMPLETED,
                active=False,
                cancellation_requested=False,
                remaining_seconds=None,
                current_serial=record.serial_number.as_text(),
                retain_last_measurement=True,
                clear_feedback_at=time.time() + 2.0,
                last_error=None,
                measurement_step=SessionStepState(
                    status=SessionStepStatus.COMPLETED,
                    message="✅ 측정 완료",
                ),
            )
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def get_recent_measurements(self) -> list[dict[str, str]]:
        with self._lock:
            return list(reversed(self._recent_measurements))

    def set_com_connection(self, is_connected: bool, port_name: str | None = None) -> None:
        with self._lock:
            if self._com_connected == is_connected and self._com_port_name == port_name:
                return

            self._com_connected = is_connected
            self._com_port_name = port_name
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def set_selected_mode(self, mode: MeasurementMode | str) -> None:
        resolved_mode = self._resolve_mode(mode)
        with self._lock:
            if self._session_state.mode == resolved_mode:
                return

            self._session_state = replace(self._session_state, mode=resolved_mode)
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def begin_session(self, mode: MeasurementMode | str, serial_number: SerialNumber | str | None = None) -> None:
        resolved_mode = self._resolve_mode(mode)
        serial_text = self._normalize_serial(serial_number)
        download_step = SessionStepState(
            status=SessionStepStatus.SKIPPED if resolved_mode == MeasurementMode.ANALOG else SessionStepStatus.IDLE,
            message=None,
        )

        with self._lock:
            self._session_state = MeasurementSessionState(
                phase=SessionPhase.WAITING_FOR_TRIGGER,
                mode=resolved_mode,
                active=True,
                cancellation_requested=False,
                remaining_seconds=None,
                current_serial=serial_text,
                retain_last_measurement=True,
                clear_feedback_at=None,
                last_error=None,
                download_step=download_step,
                measurement_step=SessionStepState(),
            )
            self._last_download = None
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def mark_waiting_for_trigger(self, serial_number: SerialNumber | str | None = None) -> None:
        serial_text = self._normalize_serial(serial_number)
        with self._lock:
            self._session_state = replace(
                self._session_state,
                phase=SessionPhase.WAITING_FOR_TRIGGER,
                active=True,
                remaining_seconds=None,
                current_serial=serial_text or self._session_state.current_serial,
                clear_feedback_at=None,
                last_error=None,
            )
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def mark_download_started(self) -> None:
        with self._lock:
            self._session_state = replace(
                self._session_state,
                phase=SessionPhase.DOWNLOADING,
                active=True,
                remaining_seconds=None,
                clear_feedback_at=None,
                last_error=None,
                download_step=SessionStepState(status=SessionStepStatus.RUNNING, message=None),
            )
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def mark_download_completed(self, message: str = "✅ 다운로드 완료", mode: str | None = None) -> None:
        resolved_mode = mode or self._session_state.mode.value
        with self._lock:
            self._last_download = {
                "success": True,
                "message": message,
                "mode": resolved_mode,
                "status": SessionStepStatus.COMPLETED.value,
            }
            self._session_state = replace(
                self._session_state,
                last_error=None,
                download_step=SessionStepState(
                    status=SessionStepStatus.COMPLETED,
                    message=message,
                ),
            )
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def mark_download_failed(self, message: str = "⚠ 다운로드 실패", mode: str | None = None) -> None:
        resolved_mode = mode or self._session_state.mode.value
        with self._lock:
            self._last_download = {
                "success": False,
                "message": message,
                "mode": resolved_mode,
                "status": SessionStepStatus.FAILED.value,
            }
            self._session_state = replace(
                self._session_state,
                phase=SessionPhase.ERROR,
                active=False,
                cancellation_requested=False,
                remaining_seconds=None,
                clear_feedback_at=None,
                last_error=message,
                download_step=SessionStepState(
                    status=SessionStepStatus.FAILED,
                    message=message,
                ),
            )
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def mark_download_skipped(self) -> None:
        with self._lock:
            self._last_download = {
                "success": True,
                "message": None,
                "mode": self._session_state.mode.value,
                "status": SessionStepStatus.SKIPPED.value,
            }
            self._session_state = replace(
                self._session_state,
                download_step=SessionStepState(status=SessionStepStatus.SKIPPED, message=None),
            )
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def mark_measurement_delay_started(self, remaining_seconds: int) -> None:
        with self._lock:
            self._session_state = replace(
                self._session_state,
                phase=SessionPhase.WAITING_FOR_MEASUREMENT,
                active=True,
                remaining_seconds=max(0, int(remaining_seconds)),
                clear_feedback_at=None,
                last_error=None,
                measurement_step=SessionStepState(status=SessionStepStatus.RUNNING, message=None),
            )
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def update_measurement_delay(self, remaining_seconds: int) -> None:
        normalized_remaining_seconds = max(0, int(remaining_seconds))
        with self._lock:
            if self._session_state.remaining_seconds == normalized_remaining_seconds:
                return

            self._session_state = replace(
                self._session_state,
                phase=SessionPhase.WAITING_FOR_MEASUREMENT,
                remaining_seconds=normalized_remaining_seconds,
            )
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def mark_measurement_started(self) -> None:
        with self._lock:
            self._session_state = replace(
                self._session_state,
                phase=SessionPhase.MEASURING,
                active=True,
                remaining_seconds=None,
                clear_feedback_at=None,
                last_error=None,
                measurement_step=SessionStepState(status=SessionStepStatus.RUNNING, message=None),
            )
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def finish_session(self) -> None:
        with self._lock:
            resolved_phase = self._session_state.phase
            if resolved_phase in {
                SessionPhase.WAITING_FOR_TRIGGER,
                SessionPhase.DOWNLOADING,
                SessionPhase.WAITING_FOR_MEASUREMENT,
                SessionPhase.MEASURING,
            }:
                resolved_phase = SessionPhase.IDLE

            updated_state = replace(
                self._session_state,
                phase=resolved_phase,
                active=False,
                cancellation_requested=False,
                remaining_seconds=None,
            )
            if updated_state == self._session_state:
                return

            self._session_state = updated_state
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def request_session_cancel(self) -> bool:
        with self._lock:
            if not self._session_state.active:
                return False

            self._session_state = replace(self._session_state, cancellation_requested=True)
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)
        return True

    def mark_session_cancelled(self, message: str = "측정이 취소되었습니다.") -> None:
        with self._lock:
            self._session_state = replace(
                self._session_state,
                phase=SessionPhase.CANCELLED,
                active=False,
                cancellation_requested=False,
                remaining_seconds=None,
                clear_feedback_at=None,
                last_error=message,
            )
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def mark_error(self, message: str) -> None:
        with self._lock:
            self._session_state = replace(
                self._session_state,
                phase=SessionPhase.ERROR,
                active=False,
                cancellation_requested=False,
                remaining_seconds=None,
                clear_feedback_at=None,
                last_error=message,
            )
            payload_to_publish, subscribers = self._snapshot_locked()

        self._broadcast(payload_to_publish, subscribers)

    def is_session_cancel_requested(self) -> bool:
        with self._lock:
            return self._session_state.cancellation_requested

    def build_status_payload(self) -> dict[str, object]:
        with self._lock:
            return self._build_status_payload_locked()

    def _build_status_payload_locked(self) -> dict[str, object]:
        state = self._normalize_transient_state_locked(self._session_state)
        self._session_state = state
        feedback_messages = self._build_feedback_messages_locked()
        latest_feedback_message = feedback_messages[-1] if feedback_messages else self._build_idle_feedback_message(state.mode)

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
            "recentMeasurements": list(reversed(self._recent_measurements)),
            "selectedMode": state.mode.value,
            "modeLabel": self._build_mode_label(state.mode),
            "phase": state.phase.value,
            "phaseLabel": self._build_phase_label(state.phase),
            "remainingSeconds": state.remaining_seconds,
            "currentSerial": state.current_serial,
            "retainLastMeasurement": state.retain_last_measurement,
            "sessionActive": state.active,
            "sessionCancellationRequested": state.cancellation_requested,
            "lastError": state.last_error,
            "downloadStep": state.download_step.to_payload(),
            "measurementStep": state.measurement_step.to_payload(),
            "feedbackMessages": feedback_messages,
            "latestFeedbackMessage": latest_feedback_message,
            "activity": self._build_activity_payload_locked(state, feedback_messages),
            "displayMeasurement": self._build_display_measurement_locked(state),
        }

    def _build_activity_payload_locked(
        self,
        state: MeasurementSessionState,
        feedback_messages: list[str],
    ) -> dict[str, str | None]:
        mode_label = self._build_mode_label(state.mode)

        if state.active and state.cancellation_requested:
            return {
                "title": "CANCELLING",
                "message": "작업 취소 요청을 처리 중입니다.",
                "symbol": "❌",
                "tone": "warning",
                "phaseLabel": self._build_phase_label(state.phase),
            }

        if state.phase == SessionPhase.WAITING_FOR_TRIGGER:
            return {
                "title": "TRIGGER WAIT",
                "message": "제품 연결 전류를 확인하는 중입니다.",
                "symbol": "⌛",
                "tone": "running",
                "phaseLabel": self._build_phase_label(state.phase),
            }

        if state.phase == SessionPhase.DOWNLOADING:
            return {
                "title": "DOWNLOADING",
                "message": f"{mode_label} 다운로드를 진행 중입니다.",
                "symbol": "⏳",
                "tone": "running",
                "phaseLabel": self._build_phase_label(state.phase),
            }

        if state.phase == SessionPhase.WAITING_FOR_MEASUREMENT:
            remaining_text = "측정 준비 중입니다."
            if state.remaining_seconds is not None:
                remaining_text = f"{mode_label} 측정까지 {state.remaining_seconds}초"

            return {
                "title": "MEASURING",
                "message": remaining_text,
                "symbol": "⌛",
                "tone": "running",
                "phaseLabel": self._build_phase_label(state.phase),
            }

        if state.phase == SessionPhase.MEASURING:
            return {
                "title": "MEASURING",
                "message": f"{mode_label} 최종 측정 중입니다.",
                "symbol": "⌛",
                "tone": "running",
                "phaseLabel": self._build_phase_label(state.phase),
            }

        if state.phase == SessionPhase.COMPLETED:
            return {
                "title": "COMPLETED",
                "message": None,
                "symbol": "✅",
                "tone": "success",
                "phaseLabel": self._build_phase_label(state.phase),
            }

        if state.phase == SessionPhase.CANCELLED:
            return {
                "title": "CANCELLED",
                "message": state.last_error or "측정이 취소되었습니다.",
                "symbol": "❌",
                "tone": "warning",
                "phaseLabel": self._build_phase_label(state.phase),
            }

        if state.phase == SessionPhase.ERROR:
            return {
                "title": "ERROR",
                "message": state.last_error or "측정 중 오류가 발생했습니다.",
                "symbol": "⚠",
                "tone": "error",
                "phaseLabel": self._build_phase_label(state.phase),
            }

        return {
            "title": "WAITING",
            "message": "스캔 대기 중 / Ready for next measurement",
            "symbol": "⌛",
            "tone": "idle",
            "phaseLabel": self._build_phase_label(state.phase),
        }

    def _build_display_measurement_locked(self, state: MeasurementSessionState) -> dict[str, object]:
        if self._last_measurement is not None and state.retain_last_measurement:
            result_text = self._last_measurement["result"]
            result_tone = "pass" if result_text == "PASS" else "fail"
            current_milliampere = self._last_measurement["current_mA"]
        elif state.phase == SessionPhase.ERROR:
            result_text = "ERROR"
            result_tone = "fail"
            current_milliampere = "0.00"
        else:
            result_text = "WAITING"
            result_tone = "idle"
            current_milliampere = "0.00"

        serial_number = state.current_serial
        if not serial_number and self._last_measurement is not None and state.retain_last_measurement:
            serial_number = self._last_measurement["qr_code"]

        return {
            "serialNumber": serial_number or "-",
            "currentMilliampere": current_milliampere,
            "resultText": result_text,
            "resultTone": result_tone,
        }

    def _build_feedback_messages_locked(self) -> list[str]:
        if self._session_state.phase == SessionPhase.COMPLETED:
            return []

        messages: list[str] = []
        self._append_feedback_message(messages, self._session_state.download_step.message)
        self._append_feedback_message(messages, self._session_state.measurement_step.message)

        if self._session_state.phase == SessionPhase.CANCELLED:
            self._append_feedback_message(messages, self._session_state.last_error or "측정이 취소되었습니다.")
        elif self._session_state.phase == SessionPhase.ERROR:
            self._append_feedback_message(messages, self._session_state.last_error)

        return messages

    def _snapshot_locked(self) -> tuple[dict[str, object], tuple[StatusSubscriber, ...]]:
        return self._build_status_payload_locked(), tuple(self._subscribers)

    def _broadcast(self, payload: dict[str, object], subscribers: tuple[StatusSubscriber, ...]) -> None:
        for subscriber in subscribers:
            try:
                subscriber.loop.call_soon_threadsafe(self._enqueue_payload, subscriber.queue, payload)
            except RuntimeError:
                continue

    def _normalize_transient_state_locked(self, state: MeasurementSessionState) -> MeasurementSessionState:
        if state.phase != SessionPhase.COMPLETED:
            return state

        if state.clear_feedback_at is None or time.time() < state.clear_feedback_at:
            return state

        return replace(
            state,
            phase=SessionPhase.IDLE,
            remaining_seconds=None,
            clear_feedback_at=None,
            download_step=SessionStepState(),
            measurement_step=SessionStepState(),
        )

    @staticmethod
    def _enqueue_payload(queue: asyncio.Queue[dict[str, object]], payload: dict[str, object]) -> None:
        while queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        queue.put_nowait(payload)

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
        mode = (row.get("mode") or MeasurementMode.SIGMASTUDIO.value).strip() or MeasurementMode.SIGMASTUDIO.value

        return {
            "measured_at": (row.get("measured_at") or "").strip(),
            "qr_code": qr_code,
            "raw_current": current_reading.as_text(),
            "current_mA": current_reading.as_display_text(),
            "result": result,
            "mode": mode,
        }

    @staticmethod
    def _parse_decimal(value: str) -> Decimal:
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return Decimal("0")

    @staticmethod
    def _append_feedback_message(messages: list[str], message: str | None) -> None:
        if not message:
            return

        if message in messages:
            return

        messages.append(message)

    @staticmethod
    def _build_mode_label(mode: MeasurementMode) -> str:
        if mode == MeasurementMode.ANALOG:
            return "Analog"

        return "Digital"

    @staticmethod
    def _build_phase_label(phase: SessionPhase) -> str:
        labels = {
            SessionPhase.IDLE: "IDLE",
            SessionPhase.WAITING_FOR_TRIGGER: "WAITING FOR TRIGGER",
            SessionPhase.DOWNLOADING: "DOWNLOADING",
            SessionPhase.WAITING_FOR_MEASUREMENT: "WAITING FOR MEASUREMENT",
            SessionPhase.MEASURING: "MEASURING",
            SessionPhase.COMPLETED: "COMPLETED",
            SessionPhase.CANCELLED: "CANCELLED",
            SessionPhase.ERROR: "ERROR",
        }
        return labels[phase]

    @staticmethod
    def _build_idle_feedback_message(mode: MeasurementMode) -> str:
        return ""

    @staticmethod
    def _normalize_serial(serial_number: SerialNumber | str | None) -> str | None:
        if serial_number is None:
            return None

        if isinstance(serial_number, SerialNumber):
            return serial_number.as_text()

        normalized = str(serial_number).strip()
        return normalized or None

    @staticmethod
    def _resolve_mode(mode: MeasurementMode | str) -> MeasurementMode:
        if isinstance(mode, MeasurementMode):
            return mode

        return MeasurementMode(str(mode))
