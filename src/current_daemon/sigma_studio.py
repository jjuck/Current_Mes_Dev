from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class SigmaStudioInvocationError(Exception):
    pass


@dataclass(frozen=True)
class SigmaStudioDownloadResult:
    success: bool
    message: str
    mode: str


@dataclass(frozen=True)
class SigmaStudioSettings:
    dll_path: Path
    fallback_executable_path: Path
    prefer_pythonnet: bool = True


class SigmaStudioDownloader:
    def __init__(
        self,
        settings: SigmaStudioSettings,
        process_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._settings = settings
        self._process_runner = process_runner

    def trigger_sigma_studio_download(self) -> SigmaStudioDownloadResult:
        if self._settings.prefer_pythonnet:
            try:
                return self._trigger_with_pythonnet()
            except Exception:
                return self._trigger_with_fallback_cli()

        return self._trigger_with_fallback_cli()

    def _trigger_with_pythonnet(self) -> SigmaStudioDownloadResult:
        if not self._settings.dll_path.exists():
            raise SigmaStudioInvocationError(
                f"SigmaStudio DLL not found: {self._settings.dll_path}"
            )

        import clr  # type: ignore
        from System import Activator  # type: ignore
        from System.Reflection import Assembly  # type: ignore

        clr.AddReference(str(self._settings.dll_path))
        assembly = Assembly.LoadFile(str(self._settings.dll_path))
        server_instance = self._create_server_instance(assembly, Activator)
        raw_result = server_instance.COMPILE_PROJECT()

        if hasattr(raw_result, "IsSuccess"):
            is_success = bool(raw_result.IsSuccess)
        else:
            is_success = bool(raw_result)

        if not is_success:
            raise SigmaStudioInvocationError(
                "SigmaStudio COMPILE_PROJECT() returned failure."
            )

        return SigmaStudioDownloadResult(
            success=True,
            message="✅ 측정 및 다운로드 완료",
            mode="pythonnet",
        )

    def _create_server_instance(self, assembly, activator):
        candidate_types = []
        for current_type in assembly.GetTypes():
            if not current_type.IsClass or current_type.IsAbstract:
                continue

            interface_names = {interface.Name for interface in current_type.GetInterfaces()}
            if "ISigmaStudioServer" in interface_names or "SigmaStudioServer" in current_type.Name:
                candidate_types.append(current_type)

        if not candidate_types:
            raise SigmaStudioInvocationError(
                "No SigmaStudio server implementation type was found in Analog.SigmaStudioServer.dll"
            )

        for candidate_type in candidate_types:
            try:
                return activator.CreateInstance(candidate_type)
            except Exception:
                continue

        raise SigmaStudioInvocationError(
            "Failed to instantiate an ISigmaStudioServer implementation type."
        )

    def _trigger_with_fallback_cli(self) -> SigmaStudioDownloadResult:
        executable_path = self._settings.fallback_executable_path
        if not executable_path.exists():
            raise SigmaStudioInvocationError(
                f"SigmaDownloader executable not found: {executable_path}"
            )

        process = self._process_runner(
            [str(executable_path), str(self._settings.dll_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            error_text = process.stderr.strip() or process.stdout.strip()
            raise SigmaStudioInvocationError(
                f"SigmaDownloader.exe failed: {error_text or 'unknown error'}"
            )

        return SigmaStudioDownloadResult(
            success=True,
            message="✅ 측정 및 다운로드 완료",
            mode="fallback-cli",
        )
