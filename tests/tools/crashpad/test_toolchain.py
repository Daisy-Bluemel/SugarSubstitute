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

"""Prove Linux build prerequisites at the external compiler boundary."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tools.crashpad_toolchain import resolve_clang_toolchain


class _CompilerProcess:
    """Record a bounded external syntax probe without requiring host Clang."""

    def __init__(self, *, returncode: int = 0) -> None:
        """Select the compiler result and retain invocation evidence."""

        self.returncode = returncode
        self.commands: list[list[str]] = []
        self.options: list[dict[str, object]] = []

    def run(
        self, command: list[str], **options: object
    ) -> subprocess.CompletedProcess[str]:
        """Return a deterministic external compiler response."""

        self.commands.append(command)
        self.options.append(options)
        return subprocess.CompletedProcess(
            command, self.returncode, "", "compiler diagnostic"
        )


def test_explicit_root_selects_its_tools_without_changing_process_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Use the three tools belonging to the requested LLVM root."""

    root = tmp_path / "LLVM-toolchain"
    lookups: list[str] = []
    process = _CompilerProcess()

    def resolve(executable: str) -> str:
        """Record executable discovery independently of host installation."""

        lookups.append(executable)
        return executable

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", resolve)
    monkeypatch.setattr(subprocess, "run", process.run)

    assert resolve_clang_toolchain(root) == root.resolve()
    assert lookups == [
        str(root / "bin" / name) for name in ("clang", "clang++", "llvm-ar")
    ]
    assert process.commands == [
        [str(root / "bin" / "clang++"), "-std=c++23", "-x", "c++", "-fsyntax-only", "-"]
    ]
    assert process.options[0]["timeout"] == 30
    assert process.options[0]["input"] == "int main() { return 0; }\n"
    assert process.options[0]["check"] is False


@pytest.mark.parametrize(
    "directory", ("LLVM with spaces", "LLVM$HOME", "LLVM'root", "LLVM\nroot")
)
def test_explicit_root_rejects_unquoted_shell_path_hazards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, directory: str
) -> None:
    """Reject roots whose spelling changes the pinned GN shell command."""

    def reject_lookup(_executable: str) -> str:
        """Require rejection before executable discovery or process launch."""

        raise AssertionError("An unsafe explicit root must not be used.")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", reject_lookup)

    with pytest.raises(RuntimeError, match="without quoting"):
        resolve_clang_toolchain(tmp_path / directory)


def test_default_linux_selection_preserves_gn_path_toolchain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probe the exact PATH compiler while leaving GN's default selection intact."""

    lookups: list[str] = []
    process = _CompilerProcess()

    def resolve(executable: str) -> str:
        """Represent PATH discovery without assuming platform path spelling."""

        lookups.append(executable)
        return f"resolved-{executable}"

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", resolve)
    monkeypatch.setattr(subprocess, "run", process.run)

    assert resolve_clang_toolchain(None) is None
    assert lookups == ["clang", "clang++", "ar"]
    assert process.commands[0][0] == "resolved-clang++"


@pytest.mark.parametrize("missing", ("clang", "clang++", "llvm-ar"))
def test_incomplete_explicit_toolchain_never_runs_compiler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str
) -> None:
    """Require the complete tool family GN will invoke."""

    process = _CompilerProcess()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        shutil,
        "which",
        lambda executable: None if Path(executable).name == missing else executable,
    )
    monkeypatch.setattr(subprocess, "run", process.run)

    with pytest.raises(RuntimeError, match="missing executable tools") as error:
        resolve_clang_toolchain(tmp_path / "LLVM")

    assert missing in str(error.value)
    assert process.commands == []


def test_rejected_cpp23_flag_reports_compiler_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a compiler that exists but cannot accept the pinned GN language flag."""

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda executable: executable)
    monkeypatch.setattr(subprocess, "run", _CompilerProcess(returncode=1).run)

    with pytest.raises(
        RuntimeError, match="must accept -std=c\\+\\+23.*compiler diagnostic"
    ):
        resolve_clang_toolchain(None)


@pytest.mark.parametrize(
    "failure", (OSError("not executable"), subprocess.TimeoutExpired("clang++", 30))
)
def test_probe_failure_keeps_its_cause(
    monkeypatch: pytest.MonkeyPatch, failure: OSError | subprocess.TimeoutExpired
) -> None:
    """Bound stalled or unlaunchable compilers with an actionable prerequisite error."""

    def fail(
        _command: list[str], **_options: object
    ) -> subprocess.CompletedProcess[str]:
        """Fail at the external process boundary."""

        raise failure

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda executable: executable)
    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(RuntimeError, match="prerequisite probe failed") as error:
        resolve_clang_toolchain(None)

    assert error.value.__cause__ is failure


@pytest.mark.parametrize("platform_name", ("win32", "darwin"))
def test_other_platform_defaults_do_not_probe_linux_tools(
    monkeypatch: pytest.MonkeyPatch, platform_name: str, tmp_path: Path
) -> None:
    """Preserve existing Windows/macOS builds and reject a Linux-only override."""

    def reject_lookup(_executable: str) -> str:
        """Catch Linux prerequisite work on an unrelated target."""

        raise AssertionError("Other targets must retain their existing toolchain.")

    monkeypatch.setattr(sys, "platform", platform_name)
    monkeypatch.setattr(shutil, "which", reject_lookup)

    assert resolve_clang_toolchain(None) is None
    with pytest.raises(RuntimeError, match="only for Linux"):
        resolve_clang_toolchain(tmp_path)
