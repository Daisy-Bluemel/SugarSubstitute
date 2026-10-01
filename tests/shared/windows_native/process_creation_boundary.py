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

"""Observe the real process-creation adapter through portable native callbacks.

This harness retains load_kernel's declarations and the real ctypes structures.
It models Windows responses without qualifying a real Windows kernel ABI.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from types import ModuleType, TracebackType

from sugarsubstitute_shared.windows_process_job_api import (
    ProcessInformation,
    StartupInfoEx,
)


@dataclass(frozen=True)
class WindowsHost:
    """Select Windows only for the shared native boundary's local host view."""

    platform: str = "win32"


@dataclass(frozen=True)
class CreationCall:
    """Retain values while the adapter's temporary native buffers are alive."""

    application: str
    command: str
    security: tuple[int | None, int | None]
    inherit: bool
    flags: int
    environment: str
    cwd: str | None
    startup_size: int
    startup_flags: int
    handles: tuple[int, int, int]
    attributes: int
    prior_events: tuple[str, ...]


class UnusedFunction:
    """Accept declarations for kernel operations outside process creation."""

    def __init__(self) -> None:
        """Keep signature configuration possible without simulating behavior."""
        self.argtypes: list[object] = []
        self.restype: object = None


class CrtModule(ModuleType):
    """Supply exactly the CRT conversion used by the production local import."""

    def __init__(self, boundary: ProcessCreationBoundary) -> None:
        """Keep conversion observations with the native call that owns them."""
        super().__init__("msvcrt")
        self.boundary = boundary
        self.converted: list[int] = []
        self.failure_at: int | None = None
        self.failure = OSError(9, "fixture invalid CRT descriptor")

    def get_osfhandle(self, fd: int, /) -> int:
        """Preserve descriptor identity and allow partial conversion failures."""
        self.converted.append(fd)
        self.boundary.events.append("convert")
        if len(self.converted) == self.failure_at:
            raise self.failure
        return self.boundary.handle_base + fd


class NullInput:
    """Record devnull ownership without opening or closing caller descriptors."""

    fd = 303

    def __init__(self, boundary: ProcessCreationBoundary) -> None:
        """Own one simulated devnull context and its cleanup observations."""
        self.boundary = boundary
        self.closed = False
        self.entered = False
        self.exit_error: BaseException | None = None

    def __enter__(self) -> NullInput:
        """Expose the opened descriptor for the duration of native creation."""
        self.entered = True
        return self

    def __exit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close devnull while replacing the simulated native last-error value."""
        self.closed = True
        self.exit_error = error
        self.boundary.events.append("close-devnull")
        self.boundary.last_error = 998

    def fileno(self) -> int:
        """Expose only the descriptor borrowed during the duplication loop."""
        return self.fd


class ProcessCreationBoundary:
    """Control native outcomes and retain observations outside ctypes callbacks."""

    handle_base = 0x100000000 if ctypes.sizeof(wintypes.HANDLE) > 4 else 0x1000000
    current_process = handle_base + 11
    job_handle = handle_base + 22
    process_handle = handle_base + 33
    thread_handle = handle_base + 44
    duplicate_handles = (handle_base + 51, handle_base + 52, handle_base + 53)

    def __init__(self) -> None:
        """Build a CDLL-shaped boundary without loading an operating-system DLL."""
        self.library = object.__new__(ctypes.CDLL)
        self.loads: list[tuple[str, bool]] = []
        self.load_failure: OSError | None = None
        self.failures: dict[str, int] = {}
        self.last_error = 0
        self.errors: dict[int, OSError] = {}
        self.translated: list[int] = []
        self.events: list[str] = []
        self.size = 64
        self.initializations: list[tuple[int | None, int, int, int]] = []
        self.duplicates: list[tuple[int, int, int, int, bool, int]] = []
        self.updates: list[
            tuple[int, int, int, tuple[int, ...], int, object, object]
        ] = []
        self.creations: list[CreationCall] = []
        self.deleted: list[int] = []
        self.closed: list[int] = []
        self.opens: list[tuple[str, str]] = []
        self.open_failure: OSError | None = None
        self.unicode_buffer_sizes: dict[int, int] = {}
        self._create_unicode_buffer = ctypes.create_unicode_buffer
        self.crt = CrtModule(self)
        self.null_input = NullInput(self)
        for name in (
            "CreateJobObjectW",
            "OpenJobObjectW",
            "SetInformationJobObject",
            "QueryInformationJobObject",
            "TerminateJobObject",
            "IsProcessInJob",
            "WaitForSingleObject",
            "GetExitCodeProcess",
        ):
            setattr(self.library, name, UnusedFunction())
        setattr(
            self.library,
            "GetCurrentProcess",
            ctypes.CFUNCTYPE(wintypes.HANDLE)(self._current),
        )
        setattr(
            self.library,
            "CloseHandle",
            ctypes.CFUNCTYPE(wintypes.BOOL, wintypes.HANDLE)(self._close),
        )
        setattr(
            self.library,
            "InitializeProcThreadAttributeList",
            ctypes.CFUNCTYPE(
                wintypes.BOOL,
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.POINTER(ctypes.c_size_t),
            )(self._initialize),
        )
        setattr(
            self.library,
            "DuplicateHandle",
            ctypes.CFUNCTYPE(
                wintypes.BOOL,
                wintypes.HANDLE,
                wintypes.HANDLE,
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.HANDLE),
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            )(self._duplicate),
        )
        setattr(
            self.library,
            "UpdateProcThreadAttribute",
            ctypes.CFUNCTYPE(
                wintypes.BOOL,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.c_size_t,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.c_void_p,
                ctypes.c_void_p,
            )(self._update),
        )
        setattr(
            self.library,
            "DeleteProcThreadAttributeList",
            ctypes.CFUNCTYPE(
                None,
                ctypes.c_void_p,
            )(self._delete),
        )
        setattr(
            self.library,
            "CreateProcessW",
            ctypes.CFUNCTYPE(
                wintypes.BOOL,
                wintypes.LPCWSTR,
                wintypes.LPWSTR,
                ctypes.c_void_p,
                ctypes.c_void_p,
                wintypes.BOOL,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.LPCWSTR,
                ctypes.POINTER(StartupInfoEx),
                ctypes.POINTER(ProcessInformation),
            )(self._create),
        )

    def load(self, name: str, *, use_last_error: bool = False) -> ctypes.CDLL:
        """Leave ABI declarations to the real production loader."""
        self.loads.append((name, use_last_error))
        if self.load_failure is not None:
            raise self.load_failure
        return self.library

    def read_error(self) -> int:
        """Read the most recent native error without clearing its value."""
        self.events.append("read-error")
        return self.last_error

    def translate(self, code: int) -> OSError:
        """Return a stable exception identity for each captured Windows code."""
        self.translated.append(code)
        self.events.append("translate-error")
        return self.errors.setdefault(code, OSError(code, "fixture native failure"))

    def open_null(self, path: str, mode: str) -> NullInput:
        """Observe devnull acquisition and an optional pre-context failure."""
        self.opens.append((path, mode))
        if self.open_failure is not None:
            raise self.open_failure
        return self.null_input

    def create_unicode_buffer(
        self, init: str | int, size: int | None = None
    ) -> ctypes.Array[ctypes.c_wchar]:
        """Retain actual allocation bounds so callback reads cannot overrun buffers."""
        buffer = self._create_unicode_buffer(init, size)
        self.unicode_buffer_sizes[ctypes.addressof(buffer)] = len(buffer)
        return buffer

    def _failed(self, operation: str) -> bool:
        """Publish configured failure codes, preserving explicit zero values."""
        if operation not in self.failures:
            return False
        self.last_error = self.failures[operation]
        return True

    def _initialize(
        self,
        attributes: int | None,
        count: int,
        flags: int,
        size: ctypes._Pointer[ctypes.c_size_t],
    ) -> int:
        """Report the required allocation even when the size probe returns false."""
        self.initializations.append((attributes, count, flags, size.contents.value))
        self.events.append("probe" if attributes is None else "initialize")
        size.contents.value = self.size
        if attributes is None:
            self.last_error = self.failures.get("probe", 122)
            return 0
        return 0 if self._failed("initialize") else 1

    def _current(self) -> int:
        """Supply a pointer-width process reference for duplicate-handle calls."""
        return self.current_process

    def _duplicate(
        self,
        source_process: int,
        source: int,
        target_process: int,
        target: ctypes._Pointer[wintypes.HANDLE],
        access: int,
        inherit: bool,
        options: int,
    ) -> int:
        """Acquire distinct owned handles and permit failures at each position."""
        self.duplicates.append(
            (source_process, source, target_process, access, bool(inherit), options)
        )
        self.events.append("duplicate")
        position = len(self.duplicates)
        if self._failed(f"duplicate-{position}"):
            return 0
        target.contents.value = self.duplicate_handles[position - 1]
        return 1

    def _update(
        self,
        attributes: int,
        flags: int,
        kind: int,
        value: int,
        size: int,
        previous: int | None,
        returned: int | None,
    ) -> int:
        """Snapshot inherited-handle and job lists before their buffers expire."""
        values = ctypes.cast(value, ctypes.POINTER(wintypes.HANDLE))
        handles = tuple(
            int(values[index] or 0)
            for index in range(size // ctypes.sizeof(wintypes.HANDLE))
        )
        self.updates.append(
            (attributes, flags, kind, handles, size, previous, returned)
        )
        operation = "inherit" if kind == 0x00020002 else "job"
        self.events.append(operation)
        return 0 if self._failed(operation) else 1

    def _create(
        self,
        application: str,
        command: str,
        process_security: int | None,
        thread_security: int | None,
        inherit: bool,
        flags: int,
        environment: int,
        cwd: str | None,
        startup: ctypes._Pointer[StartupInfoEx],
        process: ctypes._Pointer[ProcessInformation],
    ) -> int:
        """Observe atomic creation inputs and return separately owned references."""
        chars = ctypes.cast(environment, ctypes.POINTER(ctypes.c_wchar))
        block = "".join(
            chars[index]
            for index in range(self.unicode_buffer_sizes.get(environment, 0))
        )
        info = startup.contents.startup
        self.creations.append(
            CreationCall(
                application,
                command,
                (process_security, thread_security),
                bool(inherit),
                flags,
                block,
                cwd,
                int(info.size),
                int(info.flags),
                (int(info.stdin), int(info.stdout), int(info.stderr)),
                int(startup.contents.attributes),
                tuple(self.events),
            )
        )
        self.events.append("create")
        if self._failed("create"):
            return 0
        process.contents.process = self.process_handle
        process.contents.thread = self.thread_handle
        process.contents.pid = 1234
        process.contents.tid = 5678
        return 1

    def _delete(self, attributes: int) -> None:
        """Observe attribute release and clobber any uncaptured native error."""
        self.deleted.append(attributes)
        self.events.append("delete")
        self.last_error = 999

    def _close(self, handle: int) -> int:
        """Record each owned duplicate release without imposing new BOOL policy."""
        self.closed.append(handle)
        self.events.append("close-handle")
        self.last_error = 1000
        return 1
