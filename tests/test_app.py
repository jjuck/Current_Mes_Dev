import app


def test_decode_command_output_handles_none_and_bytes() -> None:
    assert app._decode_command_output(None) == ""
    assert app._decode_command_output(b"plain-ascii") == "plain-ascii"


def test_find_listening_pid_returns_pid_for_matching_host_and_port(monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = b"  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       15944\r\n"

    monkeypatch.setattr(app.subprocess, "run", lambda *args, **kwargs: Result())

    listening_pid = app._find_listening_pid("127.0.0.1", 8000)

    assert listening_pid == 15944


def test_kill_existing_process_on_port_calls_taskkill_for_other_process(monkeypatch) -> None:
    command_calls = []

    def fake_run(command, **kwargs):
        command_calls.append(command)

        class Result:
            returncode = 0
            stdout = b"  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       15944\r\n"

        return Result()

    monkeypatch.setattr(app.subprocess, "run", fake_run)
    monkeypatch.setattr(app.os, "getpid", lambda: 100)

    app._kill_existing_process_on_port("127.0.0.1", 8000)

    assert command_calls[1] == ["taskkill", "/PID", "15944", "/F"]


def test_kill_existing_process_on_port_skips_current_process(monkeypatch) -> None:
    command_calls = []

    def fake_run(command, **kwargs):
        command_calls.append(command)

        class Result:
            returncode = 0
            stdout = b"  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       300\r\n"

        return Result()

    monkeypatch.setattr(app.subprocess, "run", fake_run)
    monkeypatch.setattr(app.os, "getpid", lambda: 300)

    app._kill_existing_process_on_port("127.0.0.1", 8000)

    assert command_calls == [["netstat", "-ano"]]


def test_open_browser_after_startup_opens_expected_url(monkeypatch) -> None:
    opened_urls = []

    class FakeTimer:
        def __init__(self, interval, callback) -> None:
            self.interval = interval
            self.callback = callback
            self.daemon = False

        def start(self) -> None:
            self.callback()

    monkeypatch.setattr(app.webbrowser, "open", lambda url: opened_urls.append(url))
    monkeypatch.setattr(app.threading, "Timer", FakeTimer)

    app._open_browser_after_startup("127.0.0.1", 8000)

    assert len(opened_urls) == 1
    assert opened_urls[0].startswith("http://127.0.0.1:8000/?t=")
