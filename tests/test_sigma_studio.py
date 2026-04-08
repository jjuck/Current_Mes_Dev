from pathlib import Path

import pytest

from src.current_daemon.sigma_studio import SigmaStudioDownloader, SigmaStudioInvocationError, SigmaStudioSettings


class FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_sigma_studio_downloader_uses_fallback_cli_when_pythonnet_is_disabled(tmp_path: Path) -> None:
    dll_path = tmp_path / "Analog.SigmaStudioServer.dll"
    dll_path.write_text("dll", encoding="utf-8")
    executable_path = tmp_path / "SigmaDownloader.exe"
    executable_path.write_text("exe", encoding="utf-8")

    downloader = SigmaStudioDownloader(
        settings=SigmaStudioSettings(
            dll_path=dll_path,
            fallback_executable_path=executable_path,
            prefer_pythonnet=False,
        ),
        process_runner=lambda *args, **kwargs: FakeCompletedProcess(returncode=0, stdout="ok"),
    )

    result = downloader.trigger_sigma_studio_download()

    assert result.success is True
    assert result.mode == "fallback-cli"


def test_sigma_studio_downloader_raises_when_fallback_executable_is_missing(tmp_path: Path) -> None:
    dll_path = tmp_path / "Analog.SigmaStudioServer.dll"
    dll_path.write_text("dll", encoding="utf-8")

    downloader = SigmaStudioDownloader(
        settings=SigmaStudioSettings(
            dll_path=dll_path,
            fallback_executable_path=tmp_path / "missing.exe",
            prefer_pythonnet=False,
        )
    )

    with pytest.raises(SigmaStudioInvocationError):
        downloader.trigger_sigma_studio_download()
