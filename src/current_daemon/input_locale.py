from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


ENGLISH_KEYBOARD_LAYOUT = "00000409"
WM_INPUTLANGCHANGEREQUEST = 0x0050
KLF_ACTIVATE = 0x00000001


@dataclass(frozen=True)
class InputLocaleSwitchResult:
    requested: bool
    applied: bool
    layout: str | None
    detail: str
    foreground_window_handle: int | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "requested": self.requested,
            "applied": self.applied,
            "layout": self.layout,
            "detail": self.detail,
            "foregroundWindowHandle": self.foreground_window_handle,
        }


class KeyboardLayoutApi(Protocol):
    def load_keyboard_layout(self, layout: str, flags: int) -> int:
        ...

    def get_foreground_window(self) -> int:
        ...

    def post_message(self, hwnd: int, message: int, w_param: int, l_param: int) -> int:
        ...

    def activate_keyboard_layout(self, keyboard_layout: int, flags: int) -> int:
        ...


class ScanInputController(Protocol):
    def ensure_english_input_mode(self) -> InputLocaleSwitchResult:
        ...


class WindowsKeyboardLayoutApi:
    def __init__(self) -> None:
        import ctypes

        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

    def load_keyboard_layout(self, layout: str, flags: int) -> int:
        return int(self._user32.LoadKeyboardLayoutW(layout, flags))

    def get_foreground_window(self) -> int:
        return int(self._user32.GetForegroundWindow())

    def post_message(self, hwnd: int, message: int, w_param: int, l_param: int) -> int:
        return int(self._user32.PostMessageW(hwnd, message, w_param, l_param))

    def activate_keyboard_layout(self, keyboard_layout: int, flags: int) -> int:
        return int(self._user32.ActivateKeyboardLayout(keyboard_layout, flags))


class WindowsEnglishInputController:
    def __init__(
        self,
        keyboard_layout_api: KeyboardLayoutApi | None = None,
        platform_name: str | None = None,
    ) -> None:
        self._keyboard_layout_api = keyboard_layout_api or WindowsKeyboardLayoutApi()
        self._platform_name = platform_name

    def ensure_english_input_mode(self) -> InputLocaleSwitchResult:
        if self._resolved_platform_name() != "Windows":
            return InputLocaleSwitchResult(
                requested=False,
                applied=False,
                layout=None,
                detail="Windows keyboard layout forcing is unavailable on this platform.",
            )

        keyboard_layout = self._keyboard_layout_api.load_keyboard_layout(
            ENGLISH_KEYBOARD_LAYOUT,
            KLF_ACTIVATE,
        )
        if keyboard_layout == 0:
            return InputLocaleSwitchResult(
                requested=True,
                applied=False,
                layout=ENGLISH_KEYBOARD_LAYOUT,
                detail="Failed to load the English keyboard layout.",
            )

        foreground_window_handle = self._keyboard_layout_api.get_foreground_window() or None
        if foreground_window_handle is not None:
            self._keyboard_layout_api.post_message(
                foreground_window_handle,
                WM_INPUTLANGCHANGEREQUEST,
                0,
                keyboard_layout,
            )

        self._keyboard_layout_api.activate_keyboard_layout(keyboard_layout, KLF_ACTIVATE)

        detail = (
            "Requested the English keyboard layout for the active window."
            if foreground_window_handle is not None
            else "Activated the English keyboard layout for the current process."
        )
        return InputLocaleSwitchResult(
            requested=True,
            applied=True,
            layout=ENGLISH_KEYBOARD_LAYOUT,
            detail=detail,
            foreground_window_handle=foreground_window_handle,
        )

    def _resolved_platform_name(self) -> str:
        if self._platform_name is not None:
            return self._platform_name

        import platform

        return platform.system()
