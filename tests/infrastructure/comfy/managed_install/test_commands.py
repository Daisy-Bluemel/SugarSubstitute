#    SugarSubstitute - The desktop native Qt front-end for ComfyUI
#    Copyright (C) 2026  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Verify managed-install virtualenv and pip command behavior."""

from __future__ import annotations

from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
import subprocess
import sys
import pytest
from substitute.infrastructure.comfy import managed_install_commands
from substitute.infrastructure.comfy import managed_install_failures
from substitute.infrastructure.process import hidden_process_runner
from substitute.infrastructure.comfy.managed_validation import (
    workspace_python_path,
)
from sugarsubstitute_shared.windows_long_paths import subprocess_path
from sugarsubstitute_shared.startup_remote_access import StartupConnectivityError


@dataclass(frozen=True)
class _Platform:
    """Control console policy without changing Python's actual platform."""

    platform: str


@pytest.fixture(params=("linux", "win32"))
def captured_flags(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> int:
    """Expose the chosen Windows flag only to calls whose host supports it."""

    platform = str(request.param)
    host = _Platform(platform)
    monkeypatch.setattr(hidden_process_runner, "sys", host)
    if platform == "win32":
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x12340000, raising=False)
        return 0x12340000
    monkeypatch.delattr(subprocess, "CREATE_NO_WINDOW", raising=False)
    return 0


class _PipProcess:
    """Expose only pip's merged output and its externally observed lifecycle."""

    def __init__(self, output: str, returncode: int) -> None:
        """Retain output records until the real streaming owner closes them."""

        self.stdout = StringIO(output)
        self.returncode = returncode
        self.waited = False

    def wait(self) -> int:
        """Record the caller's completion barrier without starting a process."""

        self.waited = True
        return self.returncode


@pytest.mark.parametrize("streamed", [False, True], ids=("captured", "streamed"))
@pytest.mark.parametrize(
    "diagnostic, failure",
    [
        ("installed", None),
        (
            "NewConnectionError: getaddrinfo failed; no space left on device",
            StartupConnectivityError,
        ),
        (
            "OSError: [Errno 28] No space left on device",
            managed_install_failures.ManagedInstallStorageError,
        ),
        ("dependency resolver failed", RuntimeError),
    ],
    ids=("success", "connectivity-before-storage", "storage", "generic"),
)
def test_pip_preserves_captured_and_streamed_launch_contracts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    captured_flags: int,
    streamed: bool,
    diagnostic: str,
    failure: type[RuntimeError] | None,
) -> None:
    """Keep flags, callbacks and error classification at the actual subprocess seam."""

    python = tmp_path / "python"
    environment = {"TEMP": str(tmp_path / "scratch")}
    output = f"progress\n\n{diagnostic}\n"
    process = _PipProcess(output, 7 if failure is not None else 0)
    expected_command = [
        subprocess_path(python),
        "-m",
        "pip",
        "install",
        "fixture-package",
    ]
    commands: list[list[str]] = []
    callbacks: list[str] = []

    def capture(
        command: list[str], **options: object
    ) -> subprocess.CompletedProcess[str]:
        """Require captured pip's exact redirection, flag and environment contract."""

        assert not streamed
        commands.append(command)
        assert options == {
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
            "shell": False,
            "env": environment,
            "check": False,
            "creationflags": captured_flags,
        }
        assert options["env"] is environment
        return subprocess.CompletedProcess(command, process.returncode, stdout=output)

    def stream(command: list[str], **options: object) -> _PipProcess:
        """Keep the existing streaming defaults, including unsuppressed console flags."""

        assert streamed
        commands.append(command)
        assert options == {
            "cwd": None,
            "env": environment,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
            "universal_newlines": True,
            "creationflags": 0,
        }
        assert options["env"] is environment
        return process

    monkeypatch.setattr(subprocess, "run", capture)
    monkeypatch.setattr(subprocess, "Popen", stream)

    def install() -> None:
        """Exercise the production pip owner and its real local streaming wrapper."""

        managed_install_commands.pip_install(
            python,
            "fixture-package",
            on_log=callbacks.append if streamed else None,
            env=environment,
        )

    if failure is None:
        install()
    else:
        with pytest.raises(failure) as caught:
            install()
        assert type(caught.value) is failure
    assert commands == [expected_command]
    assert callbacks == (output.splitlines() if streamed else [])
    assert process.waited is streamed
    assert process.stdout.closed is streamed


def test_ensure_workspace_virtualenv_creates_workspace_python(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Managed install should create the workspace-local virtualenv explicitly."""

    observed: list[list[str]] = []
    venv_python = workspace_python_path(tmp_path)

    def _fake_stream_command(
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        on_line: Callable[[str], None] | None = None,
        creationflags: int = 0,
    ) -> int:
        _ = cwd, env, on_line, creationflags
        observed.append(command)
        venv_python.parent.mkdir(parents=True, exist_ok=True)
        venv_python.write_text("", encoding="utf-8")
        return 0

    monkeypatch.setattr(
        managed_install_commands, "stream_command", _fake_stream_command
    )

    result = managed_install_commands.ensure_workspace_virtualenv(tmp_path)

    assert result == venv_python
    assert observed == [
        [sys.executable, "-m", "venv", subprocess_path(tmp_path / ".venv")]
    ]


def test_pip_install_raises_when_streamed_install_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Streamed pip installs should fail closed on non-zero exit codes."""

    monkeypatch.setattr(
        managed_install_commands,
        "stream_command",
        lambda *args, **kwargs: 1,
    )

    with pytest.raises(RuntimeError):
        managed_install_commands.pip_install(
            tmp_path / "python.exe",
            "comfy-cli",
            on_log=lambda message: None,
        )


def test_pip_install_promotes_connectivity_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Pip transport evidence must reach the launch-scoped fallback as a type."""

    def fail_offline(
        _command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        on_line: Callable[[str], None] | None = None,
        creationflags: int = 0,
    ) -> int:
        """Emit the connection failure pip reports when its index is unreachable."""

        _ = cwd, env, creationflags
        assert on_line is not None
        on_line("NewConnectionError: getaddrinfo failed")
        return 1

    monkeypatch.setattr(managed_install_commands, "stream_command", fail_offline)

    with pytest.raises(StartupConnectivityError):
        managed_install_commands.pip_install(
            tmp_path / "python.exe",
            "comfy-cli",
            on_log=lambda _message: None,
        )


def test_pip_install_classifies_storage_failure_and_keeps_managed_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Pip storage errors should not be reported as generic package failures."""

    observed_env: list[dict[str, str] | None] = []
    managed_env = {"TEMP": str(tmp_path / "temp")}

    def _fake_stream_command(
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        on_line: Callable[[str], None] | None = None,
        creationflags: int = 0,
    ) -> int:
        _ = command, cwd, creationflags
        observed_env.append(env)
        assert callable(on_line)
        on_line("OSError: [Errno 28] No space left on device")
        return 1

    monkeypatch.setattr(
        managed_install_commands, "stream_command", _fake_stream_command
    )

    with pytest.raises(managed_install_failures.ManagedInstallStorageError):
        managed_install_commands.pip_install(
            tmp_path / ".venv" / "Scripts" / "python.exe",
            "torch",
            on_log=lambda _message: None,
            env=managed_env,
        )

    assert observed_env == [managed_env]


def test_ensure_workspace_virtualenv_uses_managed_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Workspace venv creation should inherit install-root temp/cache routing."""

    observed_env: list[dict[str, str] | None] = []
    managed_env = {"TEMP": str(tmp_path / "temp")}
    venv_python = workspace_python_path(tmp_path)

    def _fake_stream_command(
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        on_line: Callable[[str], None] | None = None,
        creationflags: int = 0,
    ) -> int:
        _ = command, cwd, on_line, creationflags
        observed_env.append(env)
        venv_python.parent.mkdir(parents=True, exist_ok=True)
        venv_python.write_text("", encoding="utf-8")
        return 0

    monkeypatch.setattr(
        managed_install_commands, "stream_command", _fake_stream_command
    )

    result = managed_install_commands.ensure_workspace_virtualenv(
        tmp_path, env=managed_env
    )

    assert result == venv_python
    assert observed_env == [managed_env]
