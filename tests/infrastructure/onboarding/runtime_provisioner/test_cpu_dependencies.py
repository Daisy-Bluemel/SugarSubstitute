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

"""Prove source onboarding retains CPU Torch when installing app dependencies."""

from __future__ import annotations

import json
from pathlib import Path
import platform
import subprocess

import pytest

from substitute.domain.onboarding import (
    InstallationConfiguration,
    RuntimeBootstrapStatus,
    RuntimeConfiguration,
)
from substitute.infrastructure.onboarding import SubstituteRuntimeProvisioner


class RuntimePip:
    """Model only the external interpreter and package-manager process boundary."""

    def __init__(self, installed: tuple[str, str] = ("", "")) -> None:
        """Start from the target environment's existing distribution metadata."""
        self.installed = installed
        self.resolved = ("2.14.1+cpu", "0.29.1+cpu")
        self.commands: list[list[str]] = []
        self.timeouts: list[int | None] = []
        self.probe_error: OSError | subprocess.SubprocessError | None = None
        self.install_error: OSError | subprocess.SubprocessError | None = None
        self.metadata_reply: str | None = None

    def run(
        self,
        command: list[str],
        *,
        check: bool,
        stdout: object | None = None,
        stderr: object | None = None,
        capture_output: bool = False,
        text: bool = False,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Expose metadata and emulate successful pip resolution without downloads."""
        self.commands.append(command)
        self.timeouts.append(timeout)
        if command[1] == "-c":
            if self.probe_error is not None:
                raise self.probe_error
            return subprocess.CompletedProcess(
                command,
                0,
                self.metadata_reply
                if self.metadata_reply is not None
                else json.dumps(self.installed),
            )
        if "--index-url" in command:
            if self.install_error is not None:
                raise self.install_error
            self.installed = self.resolved
        return subprocess.CompletedProcess(command, 0, "")


def provision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pip: RuntimePip
) -> RuntimeConfiguration:
    """Run the real source provisioner against one existing isolated runtime."""
    configuration = RuntimeConfiguration.create_default(
        InstallationConfiguration.create_default(tmp_path)
    )
    executable = configuration.python_executable
    assert executable is not None
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.touch()
    monkeypatch.setattr(subprocess, "run", pip.run)
    return SubstituteRuntimeProvisioner(tmp_path / "requirements.txt").provision(
        configuration
    )


def test_linux_source_onboarding_constrains_dependencies_to_resolved_cpu_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final resolver cannot replace preinstalled CPU wheels with CUDA builds."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    pip = RuntimePip()
    result = provision(tmp_path, monkeypatch, pip)

    cpu_command = next(command for command in pip.commands if "--index-url" in command)
    assert cpu_command[cpu_command.index("--index-url") + 1] == (
        "https://download.pytorch.org/whl/cpu"
    )
    assert cpu_command[-2:] == ["torch", "torchvision"]
    assert "--force-reinstall" not in cpu_command
    requirements = next(command for command in pip.commands if "-r" in command)
    assert "torch==2.14.1+cpu" in requirements
    assert "torchvision==0.29.1+cpu" in requirements
    assert result.bootstrap_status is RuntimeBootstrapStatus.READY
    assert all(
        timeout == 30
        for command, timeout in zip(pip.commands, pip.timeouts, strict=True)
        if command[1] == "-c"
    )
    assert pip.timeouts[pip.commands.index(cpu_command)] == 1800


@pytest.mark.parametrize(
    "installed",
    [("2.99.0+cu129", "0.99.0+cu129"), ("2.14.1+cpu", "0.29.1"), ("", "0.29.1+cu129")],
)
def test_linux_source_onboarding_replaces_mixed_or_newer_gpu_installations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installed: tuple[str, str]
) -> None:
    """An interrupted or newer CUDA runtime must not satisfy the CPU install step."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    pip = RuntimePip(installed)
    provision(tmp_path, monkeypatch, pip)
    cpu_command = next(command for command in pip.commands if "--index-url" in command)
    assert "--force-reinstall" in cpu_command


@pytest.mark.parametrize("platform_name", ["Windows", "Darwin"])
def test_other_platform_source_onboarding_retains_default_package_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform_name: str
) -> None:
    """The Linux support-runtime choice must not affect Windows or macOS installs."""
    monkeypatch.setattr(platform, "system", lambda: platform_name)
    pip = RuntimePip()
    provision(tmp_path, monkeypatch, pip)
    assert not any("--index-url" in command for command in pip.commands)
    assert not any(command[1] == "-c" for command in pip.commands)
    requirements = next(command for command in pip.commands if "-r" in command)
    assert not any(argument.startswith("torch") for argument in requirements)


def test_existing_cpu_installation_does_not_require_forced_reinstallation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CPU retry preserves normal pip reuse while maintaining exact constraints."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    pip = RuntimePip(("2.14.1+cpu", "0.29.1+cpu"))
    provision(tmp_path, monkeypatch, pip)
    assert not any("--force-reinstall" in command for command in pip.commands)


@pytest.mark.parametrize(
    "resolved",
    [("", "0.29.1+cpu"), ("2.14.1", "0.29.1+cpu"), ("2.15.0.dev1+cpu", "0.30.0+cpu")],
)
def test_unexpected_torch_build_blocks_general_dependency_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resolved: tuple[str, str]
) -> None:
    """Do not declare a GPU, missing, or prerelease package to be a stable CPU runtime."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    pip = RuntimePip()
    pip.resolved = resolved
    with pytest.raises(RuntimeError, match="did not resolve to stable CPU builds"):
        provision(tmp_path, monkeypatch, pip)
    assert not any("-r" in command for command in pip.commands)


@pytest.mark.parametrize(
    "reply", ["not-json", "{}", '["2.14.1+cpu"]', '[1, "0.29.1+cpu"]']
)
def test_invalid_interpreter_metadata_stops_provisioning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    """Malformed metadata cannot supply pip arguments or a ready installation."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    pip = RuntimePip()
    pip.metadata_reply = reply
    with pytest.raises(RuntimeError, match="Torch package metadata"):
        provision(tmp_path, monkeypatch, pip)
    assert not any(
        "--index-url" in command or "-r" in command for command in pip.commands
    )


@pytest.mark.parametrize("boundary", ["probe", "install"])
@pytest.mark.parametrize("failure", ["exit", "timeout", "launch"])
def test_external_torch_failure_preserves_cause_and_stops_provisioning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str, failure: str
) -> None:
    """Failed or hung external tools must retain their diagnostics and never mark ready."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    pip = RuntimePip()
    error: OSError | subprocess.SubprocessError
    if failure == "exit":
        error = subprocess.CalledProcessError(1, ["target-python"])
    elif failure == "timeout":
        error = subprocess.TimeoutExpired(["target-python"], 30)
    else:
        error = OSError("target Python is unavailable")
    if boundary == "probe":
        pip.probe_error = error
    else:
        pip.install_error = error
    with pytest.raises(RuntimeError) as caught:
        provision(tmp_path, monkeypatch, pip)
    assert caught.value.__cause__ is error
    assert not any("-r" in command for command in pip.commands)
