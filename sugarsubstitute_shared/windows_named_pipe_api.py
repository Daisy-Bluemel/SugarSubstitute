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

"""Describe the standard-library Windows pipe boundary without host-specific stubs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal, Protocol, cast


class NativePipeConnection(Protocol):
    """Expose only message and lifetime operations shared by real pipe connections.

    multiprocessing PipeConnection and Connection are sibling implementations;
    neither must be presented as the other merely to type their shared methods.
    """

    def send_bytes(self, payload: bytes, /) -> None:
        """Send one native pipe message."""
        ...

    def recv_bytes(self, maximum_size: int, /) -> bytes:
        """Receive one message subject to the native size bound."""
        ...

    def poll(self, timeout: float, /) -> bool:
        """Wait boundedly for a message to become available."""
        ...

    def close(self) -> None:
        """Release the native handle owned by this connection."""
        ...

    def fileno(self) -> int:
        """Borrow the connection's native handle without narrowing its width."""
        ...


class NamedPipeOverlapped(Protocol):
    """Describe an accept operation whose result must be collected before release."""

    @property
    def event(self) -> int:
        """Return the borrowed event handle used to wait for completion."""
        ...

    def cancel(self) -> None:
        """Cancel the outstanding operation without transferring its ownership."""
        ...

    def GetOverlappedResult(self, wait: bool, /) -> tuple[int, int]:  # noqa: N802
        """Collect the transferred-byte count and explicit Windows error code."""
        ...


class WindowsNamedPipeApi(Protocol):
    """Describe the used _winapi primitives with their native call signatures."""

    PIPE_ACCESS_DUPLEX: int
    FILE_FLAG_OVERLAPPED: int
    FILE_FLAG_FIRST_PIPE_INSTANCE: int
    PIPE_TYPE_MESSAGE: int
    PIPE_READMODE_MESSAGE: int
    PIPE_WAIT: int
    PIPE_UNLIMITED_INSTANCES: int
    NMPWAIT_WAIT_FOREVER: int
    NULL: int
    ERROR_NO_DATA: int
    INFINITE: int

    def CreateNamedPipe(  # noqa: N802
        self,
        name: str,
        open_mode: int,
        pipe_mode: int,
        max_instances: int,
        out_buffer_size: int,
        in_buffer_size: int,
        default_timeout: int,
        security_attributes: int,
        /,
    ) -> int:
        """Create the secured message-mode pipe using the caller's unchanged flags."""
        ...

    def CloseHandle(self, handle: int, /) -> None:  # noqa: N802
        """Release a pending handle that has no connection owner."""
        ...

    def ConnectNamedPipe(  # noqa: N802
        self, handle: int, overlapped: Literal[True]
    ) -> NamedPipeOverlapped:
        """Begin overlapped accept; only True guarantees an operation object."""
        ...

    def WaitForMultipleObjects(  # noqa: N802
        self, handles: Sequence[int], wait_all: bool, milliseconds: int, /
    ) -> int:
        """Wait on native event handles without changing their owner."""
        ...

    def WaitNamedPipe(self, name: str, timeout: int, /) -> None:  # noqa: N802
        """Wait for the named server with the caller's bounded timeout."""
        ...


class _NativePipeConstructors(Protocol):
    """Describe the Windows-only constructor on multiprocessing.connection."""

    PipeConnection: Callable[[int], NativePipeConnection]


def load_named_pipe_api() -> WindowsNamedPipeApi:
    """Resolve the real Windows module without copying or caching its callables."""
    import _winapi

    return cast(WindowsNamedPipeApi, _winapi)


def open_pipe_connection(handle: int) -> NativePipeConnection:
    """Transfer one accepted handle into the actual stdlib PipeConnection class."""
    import multiprocessing.connection

    constructors = cast(_NativePipeConstructors, multiprocessing.connection)
    return constructors.PipeConnection(handle)


__all__ = [
    "NamedPipeOverlapped",
    "NativePipeConnection",
    "WindowsNamedPipeApi",
    "load_named_pipe_api",
    "open_pipe_connection",
]
