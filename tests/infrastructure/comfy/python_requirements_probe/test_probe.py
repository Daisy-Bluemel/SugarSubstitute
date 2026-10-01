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

"""Verify target-Python requirement satisfaction probes."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import venv

import pytest

from substitute.infrastructure.comfy.python_requirements_probe import (
    PythonRequirementsProbe,
)
from substitute.infrastructure.process import hidden_process_runner


@dataclass(frozen=True)
class _Platform:
    """Select subprocess policy without changing the filesystem's real host."""

    platform: str


@pytest.mark.parametrize("platform, flags", [("linux", 0), ("win32", 0x12340000)])
@pytest.mark.parametrize("failed", [False, True])
def test_probe_preserves_subprocess_options_and_failure_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    platform: str,
    flags: int,
    failed: bool,
) -> None:
    """Keep target-interpreter capture, timeout and diagnostics on each platform."""

    host = _Platform(platform)
    monkeypatch.setattr(hidden_process_runner, "sys", host)
    if platform == "win32":
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", flags, raising=False)
    else:
        monkeypatch.delattr(subprocess, "CREATE_NO_WINDOW", raising=False)
    python = tmp_path / "target-python"
    requirements = tmp_path / "requirements.txt"
    environment = {"PROBE_CONTEXT": "target"}
    commands: list[list[str]] = []

    def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        """Inspect the real probe's launch boundary without starting a child."""

        commands.append(command)
        assert command[0] == str(python)
        assert command[1] == "-c"
        assert command[3] == str(requirements.resolve())
        assert options == {
            "cwd": str(tmp_path),
            "env": environment,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "capture_output": True,
            "timeout": 60,
            "check": False,
            "creationflags": flags,
        }
        assert options["env"] is not environment
        return subprocess.CompletedProcess(
            command,
            7 if failed else 0,
            stdout=(
                "probe stdout"
                if failed
                else 'SUGARSUBSTITUTE_REQUIREMENTS_PROBE={"issues": []}\n'
            ),
            stderr="probe stderr" if failed else "",
        )

    monkeypatch.setattr(subprocess, "run", run)
    if failed:
        with pytest.raises(RuntimeError, match="probe stdout probe stderr"):
            PythonRequirementsProbe().assess(
                requirements_path=requirements,
                python_executable=python,
                workspace=tmp_path,
                env=environment,
            )
    else:
        assert (
            PythonRequirementsProbe()
            .assess(
                requirements_path=requirements,
                python_executable=python,
                workspace=tmp_path,
                env=environment,
            )
            .satisfied
        )
    assert len(commands) == 1


def test_probe_preserves_virtualenv_executable_identity(tmp_path: Path) -> None:
    """Requirement inspection should not dereference a virtualenv Python symlink."""

    environment = tmp_path / "probe-environment"
    venv.EnvBuilder(with_pip=True).create(environment)
    python_executable = environment / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    site_packages = environment / (
        "Lib/site-packages"
        if os.name == "nt"
        else f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    metadata = site_packages / "sugarsubstitute_probe_fixture-1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: sugarsubstitute-probe-fixture\nVersion: 1.0\n",
        encoding="utf-8",
    )
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "sugarsubstitute-probe-fixture==1.0\n",
        encoding="utf-8",
    )

    assessment = PythonRequirementsProbe().assess(
        requirements_path=requirements,
        python_executable=python_executable,
        workspace=tmp_path,
    )

    assert assessment.satisfied is True


def test_probe_reports_satisfied_and_missing_requirements(tmp_path: Path) -> None:
    """The target interpreter should own version and marker evaluation."""

    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "pip>=1\n"
        "definitely-missing-sugarsubstitute-fixture==9876\n"
        'ignored-on-this-python==1; python_version < "2"\n',
        encoding="utf-8",
    )

    assessment = PythonRequirementsProbe().assess(
        requirements_path=requirements,
        python_executable=Path(sys.executable),
        workspace=tmp_path,
    )

    assert assessment.satisfied is False
    assert len(assessment.issues) == 1
    assert (
        "definitely-missing-sugarsubstitute-fixture" in assessment.issues[0].requirement
    )
    assert assessment.issues[0].reason == "missing"


def test_probe_fails_closed_for_unresolved_include_directives(tmp_path: Path) -> None:
    """Unsupported requirement-file composition should be explicit evidence."""

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("-r nested.txt\n", encoding="utf-8")

    assessment = PythonRequirementsProbe().assess(
        requirements_path=requirements,
        python_executable=Path(sys.executable),
        workspace=tmp_path,
    )

    assert assessment.satisfied is False
    assert assessment.issues[0].reason == "unsupported_directive"
