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

"""Characterize native library failures at the Windows capability boundary."""

from __future__ import annotations

from collections.abc import Callable
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import pytest

from sugarsubstitute_shared import windows_ctypes, windows_directory_junction
from sugarsubstitute_shared.windows_file_users import WindowsFileUsers
from sugarsubstitute_shared.windows_job_completion import WindowsJobCompletion
from sugarsubstitute_shared.windows_process_family import WindowsProcessFamily
from sugarsubstitute_shared.windows_process_handle_api import NativeProcessHandleApi
from sugarsubstitute_shared.windows_process_job_api import load_kernel
from sugarsubstitute_shared.windows_process_security import (
    process_session_id,
    process_user_sid,
)


@dataclass(frozen=True)
class _Host:
    """Control one adapter's platform without changing the test runner's host."""

    platform: str


@pytest.mark.parametrize(
    ("operation", "library", "use_last_error"),
    [
        (lambda: process_user_sid(None), "kernel32", True),
        (lambda: process_session_id(123), "kernel32", True),
        (load_kernel, "kernel32", True),
        (NativeProcessHandleApi, "kernel32", True),
        (lambda: WindowsJobCompletion(7), "kernel32", True),
        (
            lambda: WindowsProcessFamily(job=7, process=8, pid=123, args=("fixture",)),
            "kernel32",
            True,
        ),
        (WindowsFileUsers, "Rstrtmgr.dll", False),
    ],
    ids=(
        "account",
        "session",
        "job",
        "process-handle",
        "job-completion",
        "process-family",
        "file-users",
    ),
)
def test_native_capability_preserves_library_failure(
    monkeypatch: pytest.MonkeyPatch,
    operation: Callable[[], object],
    library: str,
    use_last_error: bool,
) -> None:
    """Surface the original load failure with each capability's last-error mode."""
    failure = OSError(126, "fixture library unavailable")
    loads: list[tuple[str, bool]] = []

    def fail_load(name: str, *, use_last_error: bool = False) -> ctypes.CDLL:
        """Stop at the operating-system loader before any native API executes."""
        loads.append((name, use_last_error))
        raise failure

    monkeypatch.setattr(windows_ctypes, "sys", _Host("win32"))
    monkeypatch.setattr(ctypes, "WinDLL", fail_load, raising=False)
    with pytest.raises(OSError) as caught:
        operation()
    assert caught.value is failure
    assert loads == [(library, use_last_error)]


def test_junction_load_failure_removes_only_new_junction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep the existing target while rolling back the empty failed junction."""
    target = tmp_path / "target"
    target.mkdir()
    content = target / "preserved.txt"
    content.write_text("preserved", encoding="utf-8")
    junction = tmp_path / "junction"
    failure = OSError(126, "fixture library unavailable")

    def fail_load(name: str, *, use_last_error: bool = False) -> ctypes.CDLL:
        """Reject native loading after the junction directory was prepared."""
        assert name == "kernel32"
        assert use_last_error
        assert junction.is_dir()
        raise failure

    monkeypatch.setattr(windows_directory_junction, "sys", _Host("win32"))
    monkeypatch.setattr(windows_ctypes, "sys", _Host("win32"))
    monkeypatch.setattr(ctypes, "WinDLL", fail_load, raising=False)
    with pytest.raises(OSError) as caught:
        windows_directory_junction.create_windows_directory_junction(
            junction=junction, target=target
        )
    assert caught.value is failure
    assert not junction.exists()
    assert content.read_text(encoding="utf-8") == "preserved"


@pytest.mark.parametrize("use_last_error", [None, False, True])
def test_windows_loader_returns_stdcall_library_with_requested_error_mode(
    monkeypatch: pytest.MonkeyPatch, use_last_error: bool | None
) -> None:
    """Forward default and explicit modes to WinDLL without substituting CDLL."""
    library = object.__new__(ctypes.CDLL)
    loads: list[tuple[str, bool]] = []

    def load(name: str, *, use_last_error: bool = False) -> ctypes.CDLL:
        """Represent the stdcall loader without touching any operating-system DLL."""
        loads.append((name, use_last_error))
        return library

    monkeypatch.setattr(windows_ctypes, "sys", _Host("win32"))
    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    actual = (
        windows_ctypes.load_windows_library("fixture.dll")
        if use_last_error is None
        else windows_ctypes.load_windows_library(
            "fixture.dll", use_last_error=use_last_error
        )
    )
    assert actual is library
    assert loads == [("fixture.dll", use_last_error is True)]


@pytest.mark.parametrize("platform", ["linux", "darwin"])
@pytest.mark.parametrize(
    "operation",
    [
        lambda: windows_ctypes.load_windows_library("fixture.dll"),
        windows_ctypes.windows_last_error,
        lambda: windows_ctypes.windows_error(5),
    ],
    ids=("load", "last-error", "translate-error"),
)
def test_non_windows_boundary_rejects_unavailable_native_symbols(
    monkeypatch: pytest.MonkeyPatch, platform: str, operation: Callable[[], object]
) -> None:
    """Fail explicitly before any absent Windows-only ctypes attribute is read."""
    monkeypatch.setattr(windows_ctypes, "sys", _Host(platform))
    for name in ("WinDLL", "get_last_error", "WinError"):
        monkeypatch.delattr(ctypes, name, raising=False)
    with pytest.raises(OSError, match="require Windows"):
        operation()


@pytest.mark.parametrize("code", [0, 5, 87])
def test_windows_error_preserves_explicit_code_and_native_exception(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    """Keep the native exception identity, including a supplied zero error code."""
    native_error = OSError(code, "fixture translated native error")
    translated: list[int] = []

    def translate(native_code: int) -> OSError:
        """Represent Windows' native error translation at its stdlib boundary."""
        translated.append(native_code)
        return native_error

    monkeypatch.setattr(windows_ctypes, "sys", _Host("win32"))
    monkeypatch.setattr(ctypes, "WinError", translate, raising=False)
    assert windows_ctypes.windows_error(code) is native_error
    assert translated == [code]


def test_windows_last_error_reads_current_thread_copy_each_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not cache the error state across distinct native operations."""
    errors = iter((5, 87))

    def read_error() -> int:
        """Supply successive thread-local native error observations."""
        return next(errors)

    monkeypatch.setattr(windows_ctypes, "sys", _Host("win32"))
    monkeypatch.setattr(ctypes, "get_last_error", read_error, raising=False)
    assert windows_ctypes.windows_last_error() == 5
    assert windows_ctypes.windows_last_error() == 87


def test_session_query_preserves_native_failure_through_shared_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain the process API's original failure after capturing its native code."""
    library = object.__new__(ctypes.CDLL)
    queried: list[int] = []
    native_error = OSError(5, "fixture access denied")

    def query(pid: int, session: object) -> int:
        """Return a failed native BOOL without assigning a session identifier."""
        queried.append(pid)
        return 0

    native_query = ctypes.CFUNCTYPE(
        wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
    )(query)
    setattr(library, "ProcessIdToSessionId", native_query)

    def load(name: str, *, use_last_error: bool = False) -> ctypes.CDLL:
        """Supply only the process-session API with its required last-error mode."""
        assert name == "kernel32"
        assert use_last_error
        return library

    def translate(code: int) -> OSError:
        """Verify the captured thread-local code reaches the native translator."""
        assert code == 5
        return native_error

    monkeypatch.setattr(windows_ctypes, "sys", _Host("win32"))
    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(ctypes, "WinError", translate, raising=False)
    with pytest.raises(OSError) as caught:
        process_session_id(123)
    assert caught.value is native_error
    assert queried == [123]
