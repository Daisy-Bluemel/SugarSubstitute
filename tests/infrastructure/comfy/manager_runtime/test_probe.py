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

"""Tests for non-mutating ComfyUI Manager runtime probes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import cast

import pytest

from substitute.domain.comfy_manager import ComfyManagerKind, ComfyManagerRuntime
from substitute.infrastructure.comfy import manager_runtime_probe
from substitute.infrastructure.comfy.manager_environment import (
    manager_runtime_environment,
)
from substitute.infrastructure.comfy.manager_contract import ComfyManagerContract
from substitute.infrastructure.process import hidden_process_runner
from sugarsubstitute_shared.windows_long_paths import (
    subprocess_path,
    subprocess_working_directory,
)
from tools.ci.comfy_support_matrix import (
    COMFY_RELEASE_CONTRACTS,
    ComfySupportMatrixEntry,
)


@dataclass(frozen=True)
class _Platform:
    """Choose probe flags without changing the test runner's operating system."""

    platform: str


@pytest.fixture(params=("linux", "win32"))
def probe_flags(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> int:
    """Keep flag expectations independent of the production policy function."""

    platform = str(request.param)
    host = _Platform(platform)
    monkeypatch.setattr(hidden_process_runner, "sys", host)
    if platform == "win32":
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x12340000, raising=False)
        return 0x12340000
    monkeypatch.delattr(subprocess, "CREATE_NO_WINDOW", raising=False)
    return 0


def _assert_probe_options(options: Mapping[str, object], flags: int) -> None:
    """Require the bounded, captured subprocess contract for every Manager probe."""

    assert set(options) == {
        "cwd",
        "env",
        "text",
        "encoding",
        "errors",
        "capture_output",
        "timeout",
        "check",
        "creationflags",
    }
    assert options["text"] is True
    assert options["encoding"] == "utf-8"
    assert options["errors"] == "replace"
    assert options["capture_output"] is True
    assert options["timeout"] == 60
    assert options["check"] is False
    assert options["creationflags"] == flags


@pytest.mark.parametrize(
    "entry",
    COMFY_RELEASE_CONTRACTS,
    ids=lambda entry: entry.comfyui_tag,
)
def test_comfy_cli_environment_never_requires_system_git(
    tmp_path: Path,
    entry: ComfySupportMatrixEntry,
) -> None:
    """Protect every supported Manager runtime from a system-Git dependency."""

    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    runtime = ComfyManagerRuntime(
        kind=ComfyManagerKind.INTEGRATED,
        workspace=tmp_path,
        python_executable=python,
        version=entry.manager_version,
        supports_pygit2=entry.supports_pygit2,
        uses_pygit2=entry.supports_pygit2,
    )

    environment = manager_runtime_environment(
        runtime.workspace,
        {"PATH": "", "GIT_PYTHON_REFRESH": "error"},
        use_pygit2=runtime.uses_pygit2,
    )

    assert environment["PATH"] == ""
    assert environment["GIT_PYTHON_REFRESH"] == "quiet"
    assert environment.get("CM_USE_PYGIT2") == ("1" if entry.supports_pygit2 else None)


def test_integrated_manager_4_1_probe_requires_no_pygit2_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe_flags: int,
) -> None:
    """Manager 4.1 should validate through only its baseline package contract."""

    python = _prepare_integrated_workspace(tmp_path)
    observed_environment: dict[str, str] = {}

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        """Observe the baseline Manager launch and return its native evidence."""

        _assert_probe_options(kwargs, probe_flags)
        assert command[0] == subprocess_path(python)
        assert kwargs["cwd"] == subprocess_working_directory(tmp_path)
        observed_environment.update(cast(Mapping[str, str], kwargs["env"]))
        assert "from comfyui_manager.common import git_compat" not in command[2]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "SUGARSUBSTITUTE_MANAGER_PROBE="
                '{"supports_pygit2": false, "version": "4.1"}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "substitute.infrastructure.comfy.manager_runtime_probe.subprocess.run",
        fake_run,
    )

    result = manager_runtime_probe.ComfyManagerRuntimeProbe().integrated(
        workspace=tmp_path,
        python_executable=python,
        env={"PATH": "", "CM_USE_PYGIT2": "1"},
    )

    assert result.runtime is not None
    assert result.runtime.version == "4.1"
    assert result.runtime.supports_pygit2 is False
    assert result.runtime.uses_pygit2 is False
    assert "CM_USE_PYGIT2" not in observed_environment


def test_integrated_version_probe_ignores_manager_backend_banner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Only marker-prefixed JSON should determine the Manager version."""

    python = _prepare_integrated_workspace(tmp_path)
    monkeypatch.setattr(
        "substitute.infrastructure.comfy.manager_runtime_probe.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "[ComfyUI-Manager] Using Pygit2\n"
                "SUGARSUBSTITUTE_MANAGER_PROBE="
                '{"supports_pygit2": true, "version": "4.2.2"}\n'
            ),
            stderr="",
        ),
    )

    result = manager_runtime_probe.ComfyManagerRuntimeProbe().integrated(
        workspace=tmp_path,
        python_executable=python,
    )

    assert result.runtime is not None
    assert result.runtime.version == "4.2.2"
    assert result.runtime.supports_pygit2 is True


def test_pygit2_backend_probe_forces_backend_only_after_capability_detection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe_flags: int,
) -> None:
    """A capable Manager should receive the explicit pygit2 environment."""

    python = _prepare_integrated_workspace(tmp_path)
    baseline = manager_runtime_probe.ComfyManagerRuntimeProbe()
    runtime = _integrated_runtime(tmp_path, python)
    observed_environment: dict[str, str] = {}

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        """Check the optional backend launch without importing Manager itself."""

        _assert_probe_options(kwargs, probe_flags)
        assert command[0] == subprocess_path(python)
        assert kwargs["cwd"] == subprocess_working_directory(tmp_path)
        observed_environment.update(cast(Mapping[str, str], kwargs["env"]))
        assert "git_compat.USE_PYGIT2" in command[2]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='SUGARSUBSTITUTE_MANAGER_PROBE={"uses_pygit2": true}\n',
            stderr="",
        )

    monkeypatch.setattr(
        "substitute.infrastructure.comfy.manager_runtime_probe.subprocess.run",
        fake_run,
    )

    result = baseline.pygit2_backend(runtime)

    assert result.runtime is not None
    assert result.runtime.uses_pygit2 is True
    assert observed_environment["CM_USE_PYGIT2"] == "1"


def test_legacy_probe_never_inherits_integrated_backend_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe_flags: int,
) -> None:
    """Legacy Manager should retain its own upstream Git behavior."""

    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    contract = ComfyManagerContract(tmp_path)
    contract.legacy_cli_path.parent.mkdir(parents=True)
    contract.legacy_cli_path.write_text("# fixture", encoding="utf-8")
    observed_environment: dict[str, str] = {}

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        """Check the legacy CLI launch while preserving its environment owner."""

        _assert_probe_options(kwargs, probe_flags)
        assert command == [
            subprocess_path(python),
            subprocess_path(contract.legacy_cli_path),
            "--help",
        ]
        assert kwargs["cwd"] == subprocess_working_directory(tmp_path)
        observed_environment.update(cast(Mapping[str, str], kwargs["env"]))
        return subprocess.CompletedProcess(command, 0, stdout="help", stderr="")

    monkeypatch.setattr(
        "substitute.infrastructure.comfy.manager_runtime_probe.subprocess.run",
        fake_run,
    )

    result = manager_runtime_probe.ComfyManagerRuntimeProbe().legacy(
        workspace=tmp_path,
        python_executable=python,
        env={"PATH": "", "CM_USE_PYGIT2": "1"},
    )

    assert result.runtime is not None
    assert result.runtime.kind is ComfyManagerKind.LEGACY_CUSTOM_NODE
    assert "CM_USE_PYGIT2" not in observed_environment


@pytest.mark.parametrize("kind", ["integrated", "pygit2", "legacy"])
def test_manager_probe_preserves_failed_command_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe_flags: int,
    kind: str,
) -> None:
    """Return failed probe evidence without changing capture or timeout policy."""

    python = _prepare_integrated_workspace(tmp_path)
    contract = ComfyManagerContract(tmp_path)
    contract.legacy_cli_path.parent.mkdir(parents=True)
    contract.legacy_cli_path.write_text("# fixture", encoding="utf-8")
    commands: list[list[str]] = []

    def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        """Fail only the external command after inspecting its launch contract."""

        commands.append(command)
        _assert_probe_options(options, probe_flags)
        return subprocess.CompletedProcess(
            command, 7, stdout="probe stdout", stderr="probe stderr"
        )

    monkeypatch.setattr(subprocess, "run", run)
    probe = manager_runtime_probe.ComfyManagerRuntimeProbe()
    if kind == "integrated":
        result = probe.integrated(workspace=tmp_path, python_executable=python)
    elif kind == "pygit2":
        result = probe.pygit2_backend(_integrated_runtime(tmp_path, python))
    else:
        result = probe.legacy(workspace=tmp_path, python_executable=python)
    assert result.runtime is None
    assert result.failure == "probe stdout probe stderr"
    assert len(commands) == 1


def _prepare_integrated_workspace(workspace: Path) -> Path:
    """Create an integrated checkout contract and Python fixture."""

    (workspace / "comfy").mkdir(parents=True)
    (workspace / "comfy" / "cli_args.py").write_text(
        'parser.add_argument("--enable-manager")',
        encoding="utf-8",
    )
    (workspace / "manager_requirements.txt").write_text(
        "comfyui_manager==4.2.2",
        encoding="utf-8",
    )
    python = workspace / "python.exe"
    python.write_text("", encoding="utf-8")
    return python


def _integrated_runtime(
    workspace: Path,
    python: Path,
) -> ComfyManagerRuntime:
    """Build a pygit2-capable integrated runtime."""

    return ComfyManagerRuntime(
        kind=ComfyManagerKind.INTEGRATED,
        workspace=workspace,
        python_executable=python,
        version="4.2.2",
        supports_pygit2=True,
    )
