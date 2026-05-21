from src.current_daemon.input_locale import (
    ENGLISH_KEYBOARD_LAYOUT,
    KLF_ACTIVATE,
    WM_INPUTLANGCHANGEREQUEST,
    WindowsEnglishInputController,
)


class FakeKeyboardLayoutApi:
    def __init__(self, keyboard_layout: int = 1033, foreground_window_handle: int = 501) -> None:
        self.keyboard_layout = keyboard_layout
        self.foreground_window_handle = foreground_window_handle
        self.load_calls: list[tuple[str, int]] = []
        self.post_calls: list[tuple[int, int, int, int]] = []
        self.activate_calls: list[tuple[int, int]] = []

    def load_keyboard_layout(self, layout: str, flags: int) -> int:
        self.load_calls.append((layout, flags))
        return self.keyboard_layout

    def get_foreground_window(self) -> int:
        return self.foreground_window_handle

    def post_message(self, hwnd: int, message: int, w_param: int, l_param: int) -> int:
        self.post_calls.append((hwnd, message, w_param, l_param))
        return 1

    def activate_keyboard_layout(self, keyboard_layout: int, flags: int) -> int:
        self.activate_calls.append((keyboard_layout, flags))
        return keyboard_layout


def test_windows_english_input_controller_is_noop_outside_windows() -> None:
    keyboard_layout_api = FakeKeyboardLayoutApi()
    controller = WindowsEnglishInputController(
        keyboard_layout_api=keyboard_layout_api,
        platform_name="Linux",
    )

    result = controller.ensure_english_input_mode()

    assert result.requested is False
    assert result.applied is False
    assert result.layout is None
    assert keyboard_layout_api.load_calls == []
    assert keyboard_layout_api.post_calls == []
    assert keyboard_layout_api.activate_calls == []


def test_windows_english_input_controller_requests_english_layout_for_foreground_window() -> None:
    keyboard_layout_api = FakeKeyboardLayoutApi(keyboard_layout=777, foreground_window_handle=9001)
    controller = WindowsEnglishInputController(
        keyboard_layout_api=keyboard_layout_api,
        platform_name="Windows",
    )

    result = controller.ensure_english_input_mode()

    assert result.requested is True
    assert result.applied is True
    assert result.layout == ENGLISH_KEYBOARD_LAYOUT
    assert result.foreground_window_handle == 9001
    assert keyboard_layout_api.load_calls == [(ENGLISH_KEYBOARD_LAYOUT, KLF_ACTIVATE)]
    assert keyboard_layout_api.post_calls == [(9001, WM_INPUTLANGCHANGEREQUEST, 0, 777)]
    assert keyboard_layout_api.activate_calls == [(777, KLF_ACTIVATE)]
