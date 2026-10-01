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

"""Own Windows application-instance election through one secured named pipe."""

from __future__ import annotations

import ctypes
import logging
from multiprocessing.connection import Client
import threading

from sugarsubstitute_shared.application_instance_protocol import (
    ApplicationInstanceConnection,
    ApplicationInstanceEndpoint,
)

from sugarsubstitute_shared.windows_process_security import process_user_sid
from sugarsubstitute_shared.windows_ctypes import (
    load_windows_library,
    windows_error,
    windows_last_error,
)
from sugarsubstitute_shared.windows_named_pipe_api import (
    NativePipeConnection,
    load_named_pipe_api,
    open_pipe_connection,
)

_LOGGER = logging.getLogger(__name__)
_PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
_PIPE_BUFFER_BYTES = 65536
_PIPE_CONNECT_WAIT_MILLISECONDS = 100


class WindowsNamedPipeConnection:
    """Frame messages over one local Windows named-pipe connection."""

    def __init__(
        self, connection: NativePipeConnection, *, peer_is_server: bool
    ) -> None:
        """Retain one pipe and record which peer process must be inspected."""

        self._connection = connection
        self._peer_is_server = peer_is_server

    def send_frame(self, payload: bytes) -> None:
        """Send one native message-mode pipe frame."""

        self._connection.send_bytes(payload)

    def receive_frame(
        self,
        maximum_size: int,
        *,
        timeout_seconds: float | None = None,
    ) -> bytes:
        """Receive one bounded native frame within an optional deadline."""

        try:
            if timeout_seconds is not None and not self._connection.poll(
                timeout_seconds
            ):
                raise TimeoutError("Application instance response timed out.")
            return self._connection.recv_bytes(maximum_size)
        except (EOFError, TypeError) as error:
            raise OSError("Application instance named pipe disconnected.") from error

    def close(self) -> None:
        """Close the named-pipe handle."""

        self._connection.close()

    def peer_is_current_user(self) -> bool:
        """Verify the pipe peer through its kernel process token."""

        handle = self._connection.fileno()
        peer_process_id = _named_pipe_peer_process_id(
            handle,
            peer_is_server=self._peer_is_server,
        )
        return process_user_sid(peer_process_id) == process_user_sid(None)

    def peer_process_id(self) -> int | None:
        """Return the peer process identifier reported by the named pipe kernel."""

        return _named_pipe_peer_process_id(
            self._connection.fileno(),
            peer_is_server=self._peer_is_server,
        )


class WindowsNamedPipeListener:
    """Hold the first and therefore authoritative named-pipe instance."""

    def __init__(self, endpoint: ApplicationInstanceEndpoint) -> None:
        """Atomically create a local-only first pipe with the token default DACL."""

        self._address = endpoint.address
        self._lock = threading.Lock()
        self._closed = False
        self._pending_handles = [self._new_handle(first=True)]
        self._active_accept_connection: NativePipeConnection | None = None

    def accept(self) -> ApplicationInstanceConnection:
        """Accept one same-user client and reject every other token owner."""

        connection = self._accept_connection()
        wrapped = WindowsNamedPipeConnection(connection, peer_is_server=False)
        return _authenticate_pipe_peer(
            wrapped,
            rejection_message="Application instance peer belongs to another user.",
        )

    def close(self) -> None:
        """Close every pending named-pipe instance and release election ownership."""

        native = load_named_pipe_api()

        with self._lock:
            if self._closed:
                return
            self._closed = True
            handles = [*self._pending_handles]
            self._pending_handles.clear()
            accept_connection = self._active_accept_connection
            self._active_accept_connection = None
        try:
            if accept_connection is not None:
                accept_connection.close()
        finally:
            for handle in handles:
                try:
                    native.CloseHandle(handle)
                except OSError:
                    pass

    def _new_handle(self, *, first: bool = False) -> int:
        """Create one local-only pipe instance, optionally requiring first owner."""

        native = load_named_pipe_api()

        access_flags = native.PIPE_ACCESS_DUPLEX | native.FILE_FLAG_OVERLAPPED
        if first:
            access_flags |= native.FILE_FLAG_FIRST_PIPE_INSTANCE
        pipe_mode = (
            native.PIPE_TYPE_MESSAGE
            | native.PIPE_READMODE_MESSAGE
            | native.PIPE_WAIT
            | _PIPE_REJECT_REMOTE_CLIENTS
        )
        return int(
            native.CreateNamedPipe(
                self._address,
                access_flags,
                pipe_mode,
                native.PIPE_UNLIMITED_INSTANCES,
                _PIPE_BUFFER_BYTES,
                _PIPE_BUFFER_BYTES,
                native.NMPWAIT_WAIT_FOREVER,
                native.NULL,
            )
        )

    def _accept_connection(self) -> NativePipeConnection:
        """Transfer the accepted pipe only while this listener still owns it."""

        native = load_named_pipe_api()

        with self._lock:
            if self._closed:
                raise OSError("Application instance named-pipe listener is closed.")
            self._pending_handles.append(self._new_handle())
            handle = self._pending_handles.pop(0)
            connection = open_pipe_connection(handle)
            self._active_accept_connection = connection
        try:
            try:
                overlapped = native.ConnectNamedPipe(handle, overlapped=True)
            except OSError as error:
                error_code: object = getattr(error, "winerror", None)
                if (
                    not isinstance(error_code, int)
                    or error_code != native.ERROR_NO_DATA
                ):
                    raise
            else:
                try:
                    native.WaitForMultipleObjects(
                        [overlapped.event],
                        False,
                        native.INFINITE,
                    )
                except BaseException:
                    overlapped.cancel()
                    raise
                finally:
                    _result, native_error = overlapped.GetOverlappedResult(True)
                    if native_error:
                        raise OSError(native_error, "Named-pipe connection failed.")
            with self._lock:
                if self._closed:
                    raise OSError("Application instance named-pipe listener is closed.")
                self._active_accept_connection = None
                return connection
        except BaseException:
            with self._lock:
                owns_connection = self._active_accept_connection is connection
                if owns_connection:
                    self._active_accept_connection = None
            if owns_connection:
                connection.close()
            raise


def connect_windows_named_pipe(
    endpoint: ApplicationInstanceEndpoint,
) -> WindowsNamedPipeConnection:
    """Connect to and authenticate the elected Windows supervisor."""

    native = load_named_pipe_api()

    native.WaitNamedPipe(endpoint.address, _PIPE_CONNECT_WAIT_MILLISECONDS)
    connection = Client(endpoint.address, family="AF_PIPE")
    wrapped = WindowsNamedPipeConnection(connection, peer_is_server=True)
    return _authenticate_pipe_peer(
        wrapped, rejection_message="Application instance owner belongs to another user."
    )


def _authenticate_pipe_peer(
    connection: WindowsNamedPipeConnection, *, rejection_message: str
) -> WindowsNamedPipeConnection:
    """Retain ownership until token verification succeeds, including query failures."""
    try:
        if not connection.peer_is_current_user():
            raise PermissionError(rejection_message)
    except BaseException:
        try:
            connection.close()
        except OSError:
            _LOGGER.warning(
                "Failed to close unauthenticated application instance pipe",
                exc_info=True,
            )
        raise
    return connection


def _named_pipe_peer_process_id(handle: int, *, peer_is_server: bool) -> int:
    """Return the process ID supplied by the named-pipe kernel object."""

    from ctypes import wintypes

    kernel32 = load_windows_library("kernel32", use_last_error=True)
    function_name = (
        "GetNamedPipeServerProcessId"
        if peer_is_server
        else "GetNamedPipeClientProcessId"
    )
    query = getattr(kernel32, function_name)
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    query.restype = wintypes.BOOL
    process_id = wintypes.ULONG()
    if not query(wintypes.HANDLE(handle), ctypes.byref(process_id)):
        raise windows_error(windows_last_error())
    return int(process_id.value)


__all__ = [
    "WindowsNamedPipeConnection",
    "WindowsNamedPipeListener",
    "connect_windows_named_pipe",
]
