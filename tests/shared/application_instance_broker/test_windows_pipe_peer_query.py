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

"""Verify peer PID ABI declarations and immediate native error capture."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import pytest

from sugarsubstitute_shared import application_instance_windows as windows
from tests.shared.application_instance_broker.windows_pipe_support import (
    PipeConnectionProbe,
)


class _PidQuery:
    """Emulate only the native query's output parameter and result code."""

    def __init__(self, *, result: int, trace: list[str]) -> None:
        """Retain externally controlled success and exact native-call observations."""
        self.result = result
        self.trace = trace
        self.argtypes: list[object] | None = None
        self.restype: object = None
        self.handles: list[int | None] = []

    def __call__(self, handle: wintypes.HANDLE, output: object) -> int:
        """Write through the actual by-reference ULONG supplied by the owner."""
        self.trace.append("query")
        self.handles.append(handle.value)
        output_value = getattr(output, "_obj", None)
        assert isinstance(output_value, wintypes.ULONG)
        output_value.value = 67531
        return self.result


@dataclass
class _KernelProbe:
    """Expose the exact pair of native PID query functions used by this owner."""

    GetNamedPipeServerProcessId: _PidQuery
    GetNamedPipeClientProcessId: _PidQuery


@pytest.mark.parametrize("peer_is_server", [True, False], ids=["server", "client"])
def test_peer_query_preserves_handle_width_direction_and_native_abi(
    monkeypatch: pytest.MonkeyPatch, peer_is_server: bool
) -> None:
    """Require stdcall/last-error loading and the unchanged Windows PID signature."""
    trace: list[str] = []
    server = _PidQuery(result=1, trace=trace)
    client = _PidQuery(result=1, trace=trace)
    kernel = _KernelProbe(
        GetNamedPipeServerProcessId=server, GetNamedPipeClientProcessId=client
    )
    loads: list[tuple[str, bool]] = []

    def load(name: str, *, use_last_error: bool) -> _KernelProbe:
        """Record the native library boundary without loading a host DLL."""
        loads.append((name, use_last_error))
        return kernel

    monkeypatch.setattr(windows, "load_windows_library", load)
    connection = windows.WindowsNamedPipeConnection(
        PipeConnectionProbe(0x100000001), peer_is_server=peer_is_server
    )
    assert connection.peer_process_id() == 67531
    query, unused = (server, client) if peer_is_server else (client, server)
    assert loads == [("kernel32", True)]
    assert query.argtypes == [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    assert query.restype is wintypes.BOOL
    assert query.handles == [0x100000001]
    assert unused.handles == []
    assert trace == ["query"]


def test_peer_query_captures_last_error_before_translating_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the failed native call's error and exception identity authoritative."""
    trace: list[str] = []
    query = _PidQuery(result=0, trace=trace)
    failure = OSError("controlled native PID failure")
    monkeypatch.setattr(
        windows,
        "load_windows_library",
        lambda _name, *, use_last_error: _KernelProbe(
            GetNamedPipeServerProcessId=query,
            GetNamedPipeClientProcessId=_PidQuery(result=1, trace=trace),
        ),
    )

    def last_error() -> int:
        """Expose one thread-local native code immediately after the query."""
        trace.append("last-error")
        return 5

    def translate(code: int) -> OSError:
        """Verify exact error forwarding without executing a native translator."""
        assert code == 5
        trace.append("translate-error")
        return failure

    monkeypatch.setattr(windows, "windows_last_error", last_error)
    monkeypatch.setattr(windows, "windows_error", translate)
    connection = windows.WindowsNamedPipeConnection(
        PipeConnectionProbe(1), peer_is_server=True
    )
    with pytest.raises(OSError) as caught:
        connection.peer_process_id()
    assert caught.value is failure
    assert trace == ["query", "last-error", "translate-error"]
