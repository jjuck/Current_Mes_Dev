from src.current_daemon.config import build_config
from src.current_daemon.logger import build_console_logger
from src.current_daemon.web_api import create_web_app

import os
import re
import subprocess
import threading
import time
import webbrowser

import uvicorn


def _decode_command_output(raw_output: bytes | str | None) -> str:
    if raw_output is None:
        return ""

    if isinstance(raw_output, str):
        return raw_output

    for encoding in ("mbcs", "cp949", "utf-8"):
        try:
            return raw_output.decode(encoding)
        except UnicodeDecodeError:
            continue

    return raw_output.decode("utf-8", errors="ignore")


def _find_listening_pid(host: str, port: int) -> int | None:
    command_result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True,
        check=False,
    )
    if command_result.returncode != 0:
        return None

    listening_pattern = re.compile(
        rf"^\s*TCP\s+{re.escape(host)}:{port}\s+\S+\s+LISTENING\s+(\d+)\s*$",
        re.IGNORECASE,
    )

    decoded_stdout = _decode_command_output(command_result.stdout)
    for line in decoded_stdout.splitlines():
        matched_line = listening_pattern.match(line)
        if matched_line is None:
            continue

        return int(matched_line.group(1))

    return None


def _kill_existing_process_on_port(host: str, port: int) -> None:
    listening_pid = _find_listening_pid(host, port)
    if listening_pid is None or listening_pid == os.getpid():
        return

    subprocess.run(
        ["taskkill", "/PID", str(listening_pid), "/F"],
        capture_output=True,
        check=False,
    )


def _open_browser_after_startup(host: str, port: int) -> None:
    target_url = f"http://{host}:{port}/?t={int(time.time())}"

    def _open() -> None:
        webbrowser.open(target_url)

    timer = threading.Timer(1.0, _open)
    timer.daemon = True
    timer.start()


def main() -> None:
    config = build_config()
    application_logger = build_console_logger()
    application = create_web_app(config, application_logger)
    _kill_existing_process_on_port(config.web_host, config.web_port)
    _open_browser_after_startup(config.web_host, config.web_port)
    uvicorn.run(application, host=config.web_host, port=config.web_port)


if __name__ == "__main__":
    main()
