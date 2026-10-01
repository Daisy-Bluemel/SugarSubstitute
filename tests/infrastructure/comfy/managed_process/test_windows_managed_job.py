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

"""Prove managed-job error and handle contracts with simulated Windows APIs.

These portable tests retain the real job and process adapters. Local ctypes
callbacks replace the OS boundary; they do not qualify the Windows kernel ABI.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import pytest

from substitute.infrastructure.comfy.windows_managed_job import WindowsManagedJob
from sugarsubstitute_shared import windows_ctypes
from sugarsubstitute_shared.windows_process_job_api import BasicAccounting


@dataclass(frozen=True)
class _Host:
    """Expose Windows only to the shared native capability boundary."""

    platform: str = "win32"


class _UnusedFunction:
    """Accept real ABI declarations while rejecting unplanned native operations."""

    def __init__(self) -> None:
        """Retain declarations without implementing unrelated kernel behavior."""
        self.argtypes: list[object] = []
        self.restype: object = None


class _NativeBoundary:
    """Supply controlled kernel results and independently observable references."""

    job_handle = 0x100000011
    process_handle = 0x100000022

    def __init__(self) -> None:
        """Build a portable library object without loading a native library."""
        self.library = object.__new__(ctypes.CDLL)
        self.failures: dict[str, int] = {}
        self.last_error = 0
        self.errors: dict[int, OSError] = {}
        self.translated: list[int] = []
        self.loads: list[tuple[str, bool]] = []
        self.load_failure: OSError | None = None
        self.opened_jobs: list[tuple[int, bool, str]] = []
        self.opened_processes: list[tuple[int, bool, int]] = []
        self.membership_queries: list[tuple[int, int]] = []
        self.accounting_queries: list[tuple[int, int, int, object]] = []
        self.closed: list[int] = []
        self.member = True
        self.active_processes = 1
        for name in (
            "CreateJobObjectW",
            "SetInformationJobObject",
            "TerminateJobObject",
            "GetCurrentProcess",
            "DuplicateHandle",
            "InitializeProcThreadAttributeList",
            "UpdateProcThreadAttribute",
            "DeleteProcThreadAttributeList",
            "CreateProcessW",
            "WaitForSingleObject",
            "GetExitCodeProcess",
            "GetProcessTimes",
            "QueryFullProcessImageNameW",
            "TerminateProcess",
        ):
            setattr(self.library, name, _UnusedFunction())
        setattr(
            self.library,
            "OpenJobObjectW",
            ctypes.CFUNCTYPE(
                wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR
            )(self._open_job),
        )
        setattr(
            self.library,
            "OpenProcess",
            ctypes.CFUNCTYPE(
                wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
            )(self._open_process),
        )
        setattr(
            self.library,
            "IsProcessInJob",
            ctypes.CFUNCTYPE(
                wintypes.BOOL,
                wintypes.HANDLE,
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.BOOL),
            )(self._contains),
        )
        setattr(
            self.library,
            "QueryInformationJobObject",
            ctypes.CFUNCTYPE(
                wintypes.BOOL,
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.POINTER(BasicAccounting),
                wintypes.DWORD,
                ctypes.c_void_p,
            )(self._query),
        )
        setattr(
            self.library,
            "CloseHandle",
            ctypes.CFUNCTYPE(wintypes.BOOL, wintypes.HANDLE)(self._close),
        )

    def load(self, name: str, *, use_last_error: bool = False) -> ctypes.CDLL:
        """Stand in for WinDLL while leaving real adapter configuration intact."""
        self.loads.append((name, use_last_error))
        if self.load_failure is not None:
            raise self.load_failure
        return self.library

    def read_error(self) -> int:
        """Expose the error of the most recent simulated native operation."""
        return self.last_error

    def translate(self, code: int) -> OSError:
        """Return one identifiable native exception for each explicit code."""
        self.translated.append(code)
        return self.errors.setdefault(code, OSError(code, "fixture native error"))

    def _failed(self, operation: str) -> bool:
        """Publish a configured native failure, including a zero error code."""
        if operation not in self.failures:
            return False
        self.last_error = self.failures[operation]
        return True

    def _open_job(self, access: int, inherit: bool, name: str) -> int:
        """Return a distinct job reference or a controlled native failure."""
        self.opened_jobs.append((access, bool(inherit), name))
        return 0 if self._failed("open_job") else self.job_handle

    def _open_process(self, access: int, inherit: bool, pid: int) -> int:
        """Retain the requested process independently of the job reference."""
        self.opened_processes.append((access, bool(inherit), pid))
        return 0 if self._failed("open_process") else self.process_handle

    def _contains(
        self, process: int, job: int, member: ctypes._Pointer[wintypes.BOOL]
    ) -> int:
        """Publish membership through the native out-parameter only on success."""
        self.membership_queries.append((process, job))
        if self._failed("contains"):
            return 0
        member.contents.value = self.member
        return 1

    def _query(
        self,
        job: int,
        kind: int,
        accounting: ctypes._Pointer[BasicAccounting],
        size: int,
        returned: object,
    ) -> int:
        """Supply active family membership through the real accounting structure."""
        self.accounting_queries.append((job, kind, size, returned))
        if self._failed("query"):
            return 0
        accounting.contents.active_processes = self.active_processes
        return 1

    def _close(self, handle: int) -> int:
        """Record handle release and replace stale thread-local error state."""
        self.closed.append(handle)
        operation = "close_job" if handle == self.job_handle else "close_process"
        if self._failed(operation):
            return 0
        self.last_error = 999
        return 1


@pytest.fixture
def native(monkeypatch: pytest.MonkeyPatch) -> _NativeBoundary:
    """Replace Windows-only ctypes symbols without changing the test host."""
    boundary = _NativeBoundary()
    monkeypatch.setattr(windows_ctypes, "sys", _Host())
    monkeypatch.setattr(ctypes, "WinDLL", boundary.load, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", boundary.read_error, raising=False)
    monkeypatch.setattr(ctypes, "WinError", boundary.translate, raising=False)
    return boundary


def test_open_rejects_missing_identity_before_native_loading(
    native: _NativeBoundary,
) -> None:
    """Do not request an arbitrary job when persisted identity is absent."""
    with pytest.raises(ValueError, match="identity is missing"):
        WindowsManagedJob.open("")
    assert native.loads == []


def test_open_preserves_loader_failure(native: _NativeBoundary) -> None:
    """Keep the original unavailable-library error without attempting cleanup."""
    failure = OSError(126, "fixture library unavailable")
    native.load_failure = failure
    with pytest.raises(OSError) as caught:
        WindowsManagedJob.open("fixture-job")
    assert caught.value is failure
    assert native.loads == [("kernel32", True)]
    assert native.closed == []


def test_open_treats_only_missing_job_as_retired(native: _NativeBoundary) -> None:
    """An absent job has already retired and provides no reference to release."""
    native.failures["open_job"] = 2
    assert WindowsManagedJob.open("fixture-job") is None
    assert native.translated == []
    assert native.closed == []


@pytest.mark.parametrize("code", [0, 5, 87])
def test_open_preserves_other_native_errors(native: _NativeBoundary, code: int) -> None:
    """Forward every non-absence error without substituting or dropping its code."""
    native.failures["open_job"] = code
    with pytest.raises(OSError) as caught:
        WindowsManagedJob.open("fixture-job")
    assert caught.value is native.errors[code]
    assert native.translated == [code]
    assert native.closed == []


@pytest.mark.parametrize(("for_termination", "access"), [(False, 0x4), (True, 0xE)])
def test_open_retains_requested_rights_and_closes_own_reference(
    native: _NativeBoundary, for_termination: bool, access: int
) -> None:
    """Keep observation and termination rights distinct and release the opened job."""
    job = WindowsManagedJob.open("fixture-job", for_termination=for_termination)
    assert job is not None
    with job as retained:
        assert retained is job
        assert native.closed == []
    assert native.opened_jobs == [(access, False, "fixture-job")]
    assert native.loads == [("kernel32", True)]
    assert native.closed == [native.job_handle]


@pytest.mark.parametrize("member", [False, True])
def test_contains_releases_the_retained_process(
    native: _NativeBoundary, member: bool
) -> None:
    """Return actual membership while closing the process and job independently."""
    native.member = member
    job = WindowsManagedJob.open("fixture-job")
    assert job is not None
    with job:
        assert job.contains_process(123) is member
        assert native.closed == [native.process_handle]
    assert native.opened_processes == [(0x101000, False, 123)]
    assert native.membership_queries == [(native.process_handle, native.job_handle)]
    assert native.closed == [native.process_handle, native.job_handle]


def test_contains_absent_process_does_not_query_or_close_it(
    native: _NativeBoundary,
) -> None:
    """An exited process has no acquired reference and cannot belong to the job."""
    native.failures["open_process"] = 87
    job = WindowsManagedJob.open("fixture-job")
    assert job is not None
    with job:
        assert not job.contains_process(123)
    assert native.membership_queries == []
    assert native.translated == []
    assert native.closed == [native.job_handle]


@pytest.mark.parametrize("operation", ["open_process", "contains"])
def test_contains_preserves_native_failure_through_cleanup(
    native: _NativeBoundary, operation: str
) -> None:
    """Capture the original failure before successful cleanup changes last-error."""
    native.failures[operation] = 5
    job = WindowsManagedJob.open("fixture-job")
    assert job is not None
    with pytest.raises(OSError) as caught, job:
        job.contains_process(123)
    assert caught.value is native.errors[5]
    assert native.translated == [5]
    assert native.closed == (
        [native.job_handle]
        if operation == "open_process"
        else [native.process_handle, native.job_handle]
    )
    assert native.last_error == 999


@pytest.mark.parametrize("query_fails", [False, True])
def test_contains_preserves_process_close_failure_and_query_context(
    native: _NativeBoundary, query_fails: bool
) -> None:
    """Retain the process-close failure and chain any original membership error."""
    native.failures["close_process"] = 6
    if query_fails:
        native.failures["contains"] = 5
    job = WindowsManagedJob.open("fixture-job")
    assert job is not None
    with pytest.raises(OSError) as caught, job:
        job.contains_process(123)
    assert caught.value is native.errors[6]
    assert caught.value.__context__ is (native.errors[5] if query_fails else None)
    assert native.translated == ([5, 6] if query_fails else [6])
    assert native.closed == [native.process_handle, native.job_handle]


@pytest.mark.parametrize("active_processes", [0, 3])
def test_has_members_reads_native_accounting(
    native: _NativeBoundary, active_processes: int
) -> None:
    """Detect remaining children without depending on the original root PID."""
    native.active_processes = active_processes
    job = WindowsManagedJob.open("fixture-job")
    assert job is not None
    with job:
        assert job.has_members() is bool(active_processes)
    assert native.accounting_queries == [
        (native.job_handle, 1, ctypes.sizeof(BasicAccounting), None)
    ]
    assert native.closed == [native.job_handle]


def test_has_members_preserves_query_failure_through_cleanup(
    native: _NativeBoundary,
) -> None:
    """Do not interpret a failed accounting query as an empty family."""
    native.failures["query"] = 87
    job = WindowsManagedJob.open("fixture-job")
    assert job is not None
    with pytest.raises(OSError) as caught, job:
        job.has_members()
    assert caught.value is native.errors[87]
    assert native.translated == [87]
    assert native.closed == [native.job_handle]


@pytest.mark.parametrize("body_fails", [False, True])
def test_context_close_preserves_native_failure_and_body_context(
    native: _NativeBoundary, body_fails: bool
) -> None:
    """Surface close failure without losing an exception already leaving the body."""
    native.failures["close_job"] = 6
    body_error = RuntimeError("fixture body failed")
    job = WindowsManagedJob.open("fixture-job")
    assert job is not None
    with pytest.raises(OSError) as caught, job:
        if body_fails:
            raise body_error
    assert caught.value is native.errors[6]
    assert caught.value.__context__ is (body_error if body_fails else None)
    assert native.translated == [6]
    assert native.closed == [native.job_handle]
