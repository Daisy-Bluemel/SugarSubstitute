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

"""Verify the Windows stdlib boundary resolves actual, live platform objects."""

from __future__ import annotations

import multiprocessing.connection
import sys

import pytest

from sugarsubstitute_shared.windows_named_pipe_api import (
    load_named_pipe_api,
    open_pipe_connection,
)
from tests.shared.application_instance_broker.windows_pipe_support import (
    OverlappedProbe,
    PipeConnectionProbe,
    install_pipe_api,
)


def test_api_returns_actual_module_and_observes_live_native_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve late native monkeypatches used by controlled accept cancellation."""
    probe = install_pipe_api(monkeypatch)
    native = load_named_pipe_api()
    module = sys.modules["_winapi"]
    assert native is module
    replacement = OverlappedProbe(event=0x100000009)
    calls: list[tuple[int, bool]] = []

    def connect(handle: int, *, overlapped: bool) -> OverlappedProbe:
        """Supply a changed callable after the consumer has resolved the module."""
        calls.append((handle, overlapped))
        return replacement

    monkeypatch.setattr(module, "ConnectNamedPipe", connect)
    assert native.ConnectNamedPipe(0x100000003, overlapped=True) is replacement
    assert calls == [(0x100000003, True)]
    assert probe.connect_calls == []


def test_connection_constructor_is_resolved_at_each_handle_transfer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain actual stdlib constructor replacement without substituting Connection."""
    first = install_pipe_api(monkeypatch)
    original = open_pipe_connection(0x100000001)
    second_calls: list[int] = []

    def replacement(handle: int) -> PipeConnectionProbe:
        """Record a later stdlib constructor and its unchanged wide handle."""
        second_calls.append(handle)
        return PipeConnectionProbe(handle)

    monkeypatch.setattr(multiprocessing.connection, "PipeConnection", replacement)
    later = open_pipe_connection(0x100000003)
    assert original is first.connections[0]
    assert original.fileno() == 0x100000001
    assert later.fileno() == 0x100000003
    assert len(first.connections) == 1
    assert second_calls == [0x100000003]
    original.close()
    later.close()


def test_missing_native_module_fails_without_a_transport_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Propagate platform-module absence instead of inventing another IPC transport."""
    monkeypatch.setitem(sys.modules, "_winapi", None)
    with pytest.raises(ModuleNotFoundError):
        load_named_pipe_api()


def test_missing_pipe_constructor_is_not_replaced_with_another_connection_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail explicitly when the platform-only stdlib pipe implementation is absent."""
    monkeypatch.delattr(multiprocessing.connection, "PipeConnection", raising=False)
    with pytest.raises(AttributeError, match="PipeConnection"):
        open_pipe_connection(0x100000001)
