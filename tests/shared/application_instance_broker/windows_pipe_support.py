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

"""Control only the external Windows pipe primitives for portable owner tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import multiprocessing.connection
import sys
from types import ModuleType

import pytest


@dataclass(eq=False)
class PipeConnectionProbe:
    """Record message framing and handle closure at the native connection boundary."""

    handle: int
    payload: bytes = b"response"
    ready: bool = True
    receive_error: BaseException | None = None
    close_error: OSError | None = None
    sent: list[bytes] = field(default_factory=list)
    limits: list[int] = field(default_factory=list)
    timeouts: list[float] = field(default_factory=list)
    close_count: int = 0

    def send_bytes(self, payload: bytes) -> None:
        """Record one complete outgoing native message."""
        self.sent.append(payload)

    def recv_bytes(self, maximum_size: int) -> bytes:
        """Expose native receive success or failure without reimplementing framing."""
        self.limits.append(maximum_size)
        if self.receive_error is not None:
            raise self.receive_error
        return self.payload

    def poll(self, timeout: float) -> bool:
        """Record the deadline delegated to the native pipe."""
        self.timeouts.append(timeout)
        return self.ready

    def close(self) -> None:
        """Record each ownership release, including erroneous duplicates."""
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error

    def fileno(self) -> int:
        """Return the unchanged native handle value."""
        return self.handle


@dataclass
class OverlappedProbe:
    """Record cancellation and final collection of one native accept operation."""

    event: int = 0x100000005
    native_error: int = 0
    cancellations: int = 0
    waits: list[bool] = field(default_factory=list)

    def cancel(self) -> None:
        """Record cancellation before the outstanding operation is collected."""
        self.cancellations += 1

    def GetOverlappedResult(self, wait: bool) -> tuple[int, int]:  # noqa: N802
        """Return the final status supplied by the external native operation."""
        self.waits.append(wait)
        return 0, self.native_error


class NativePipeError(OSError):
    """Expose the WinError metadata absent from non-Windows OSError objects."""

    def __init__(self, code: int) -> None:
        """Retain one explicit native failure code."""
        super().__init__(code, "controlled native pipe error")
        self.winerror = code


class PipeApiProbe:
    """Record the named-pipe API without creating sockets or operating-system handles."""

    PIPE_ACCESS_DUPLEX = 3
    FILE_FLAG_OVERLAPPED = 0x40000000
    FILE_FLAG_FIRST_PIPE_INSTANCE = 0x80000
    PIPE_TYPE_MESSAGE = 4
    PIPE_READMODE_MESSAGE = 2
    PIPE_WAIT = 0
    PIPE_UNLIMITED_INSTANCES = 255
    NMPWAIT_WAIT_FOREVER = 0xFFFFFFFF
    NULL = 0
    ERROR_NO_DATA = 232
    INFINITE = 0xFFFFFFFF

    def __init__(self) -> None:
        """Initialize independent call records and optional native failures."""
        self.created: list[tuple[object, ...]] = []
        self.closed_handles: list[int] = []
        self.connections: list[PipeConnectionProbe] = []
        self.connect_calls: list[tuple[int, bool]] = []
        self.wait_calls: list[tuple[list[int], bool, int]] = []
        self.client_waits: list[tuple[str, int]] = []
        self.operation = OverlappedProbe()
        self.connect_error: BaseException | None = None
        self.on_wait: Callable[[], None] | None = None

    def CreateNamedPipe(self, *arguments: object) -> int:  # noqa: N802
        """Record the exact pipe flags, bounds and security attributes."""
        self.created.append(arguments)
        return 0x100000000 + len(self.created)

    def CloseHandle(self, handle: int) -> None:  # noqa: N802
        """Record release of a pending handle not transferred into a connection."""
        self.closed_handles.append(handle)

    def ConnectNamedPipe(self, handle: int, *, overlapped: bool) -> OverlappedProbe:  # noqa: N802
        """Expose native connect setup while retaining the requested overlap mode."""
        self.connect_calls.append((handle, overlapped))
        if self.connect_error is not None:
            raise self.connect_error
        return self.operation

    def WaitForMultipleObjects(
        self, handles: list[int], wait_all: bool, timeout: int
    ) -> int:  # noqa: N802
        """Run an optional shutdown/interruption at the native wait boundary."""
        self.wait_calls.append((handles, wait_all, timeout))
        if self.on_wait is not None:
            self.on_wait()
        return 0

    def WaitNamedPipe(self, address: str, timeout: int) -> None:  # noqa: N802
        """Record the bounded client connection wait."""
        self.client_waits.append((address, timeout))

    def make_connection(self, handle: int) -> PipeConnectionProbe:
        """Retain the connection that assumes ownership of an accepted handle."""
        connection = PipeConnectionProbe(handle)
        self.connections.append(connection)
        return connection


def install_pipe_api(monkeypatch: pytest.MonkeyPatch) -> PipeApiProbe:
    """Replace platform-only primitives without replacing the transport owner."""
    api = PipeApiProbe()
    module = ModuleType("_winapi")
    for name in (
        "PIPE_ACCESS_DUPLEX",
        "FILE_FLAG_OVERLAPPED",
        "FILE_FLAG_FIRST_PIPE_INSTANCE",
        "PIPE_TYPE_MESSAGE",
        "PIPE_READMODE_MESSAGE",
        "PIPE_WAIT",
        "PIPE_UNLIMITED_INSTANCES",
        "NMPWAIT_WAIT_FOREVER",
        "NULL",
        "ERROR_NO_DATA",
        "INFINITE",
        "CreateNamedPipe",
        "CloseHandle",
        "ConnectNamedPipe",
        "WaitForMultipleObjects",
        "WaitNamedPipe",
    ):
        setattr(module, name, getattr(api, name))
    monkeypatch.setitem(sys.modules, "_winapi", module)
    monkeypatch.setattr(
        multiprocessing.connection, "PipeConnection", api.make_connection, raising=False
    )
    return api
