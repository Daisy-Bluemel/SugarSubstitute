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

"""Characterize Windows pipe framing, authentication and handle ownership portably."""

from __future__ import annotations

from typing import Literal, NoReturn

import pytest

from sugarsubstitute_shared import application_instance_windows as windows
from sugarsubstitute_shared.application_instance_protocol import (
    ApplicationInstanceEndpoint,
)
from tests.shared.application_instance_broker.windows_pipe_support import (
    NativePipeError,
    PipeConnectionProbe,
    install_pipe_api,
)

_ENDPOINT = ApplicationInstanceEndpoint("windows-named-pipe", r"\\.\pipe\qualification")


def _trust_peer(monkeypatch: pytest.MonkeyPatch, *, owner: bool = True) -> None:
    """Control OS identity queries while retaining both production comparisons."""
    monkeypatch.setattr(
        windows, "_named_pipe_peer_process_id", lambda _handle, *, peer_is_server: 41
    )
    monkeypatch.setattr(
        windows,
        "process_user_sid",
        lambda pid: "owner" if pid is None or owner else "foreign",
    )


def test_connection_delegates_binary_frames_size_and_deadline() -> None:
    """Preserve exact payloads and native framing bounds without adding another codec."""
    pipe = PipeConnectionProbe(0x100000001, payload=b"reply\x00tail")
    connection = windows.WindowsNamedPipeConnection(pipe, peer_is_server=True)
    connection.send_frame(b"request\x00tail")
    assert pipe.sent == [b"request\x00tail"]
    assert connection.receive_frame(128, timeout_seconds=0.25) == b"reply\x00tail"
    assert pipe.timeouts == [0.25]
    assert pipe.limits == [128]
    assert connection.receive_frame(64) == b"reply\x00tail"
    assert pipe.timeouts == [0.25]
    assert pipe.limits == [128, 64]
    connection.close()
    assert pipe.close_count == 1


def test_connection_timeout_never_reads_an_unready_pipe() -> None:
    """Honor the bounded wait before attempting a potentially blocking receive."""
    pipe = PipeConnectionProbe(1, ready=False)
    connection = windows.WindowsNamedPipeConnection(pipe, peer_is_server=False)
    with pytest.raises(TimeoutError, match="response timed out"):
        connection.receive_frame(16, timeout_seconds=0.0)
    assert pipe.timeouts == [0.0]
    assert pipe.limits == []


@pytest.mark.parametrize("failure", [EOFError("eof"), TypeError("closed handle")])
def test_connection_translates_native_disconnect_and_preserves_cause(
    failure: BaseException,
) -> None:
    """Expose the portable disconnect contract without swallowing its native cause."""
    pipe = PipeConnectionProbe(1, receive_error=failure)
    connection = windows.WindowsNamedPipeConnection(pipe, peer_is_server=False)
    with pytest.raises(OSError, match="disconnected") as caught:
        connection.receive_frame(16)
    assert caught.value.__cause__ is failure


def test_native_size_rejection_is_propagated() -> None:
    """Leave native oversized-message rejection authoritative."""
    failure = OSError("bad message length")
    pipe = PipeConnectionProbe(1, receive_error=failure)
    connection = windows.WindowsNamedPipeConnection(pipe, peer_is_server=False)
    with pytest.raises(OSError) as caught:
        connection.receive_frame(8)
    assert caught.value is failure
    assert pipe.limits == [8]


def test_listener_uses_local_only_first_instance_and_transfers_accepted_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep election, token-default DACL, overlap and message-mode contracts exact."""
    api = install_pipe_api(monkeypatch)
    _trust_peer(monkeypatch)
    listener = windows.WindowsNamedPipeListener(_ENDPOINT)
    accepted = None
    try:
        accepted = listener.accept()
        assert api.created == [
            (_ENDPOINT.address, 0x40080003, 0xE, 255, 65536, 65536, 0xFFFFFFFF, 0),
            (_ENDPOINT.address, 0x40000003, 0xE, 255, 65536, 65536, 0xFFFFFFFF, 0),
        ]
        assert api.connect_calls == [(0x100000001, True)]
        assert api.wait_calls == [([0x100000005], False, 0xFFFFFFFF)]
        assert api.operation.waits == [True]
        assert accepted.peer_process_id() == 41
        listener.close()
        listener.close()
        assert api.closed_handles == [0x100000002]
        assert api.connections[0].close_count == 0
    finally:
        listener.close()
        if accepted is not None:
            accepted.close()
    assert api.connections[0].close_count == 1


def test_closed_listener_never_creates_another_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject post-close accept before allocating more native resources."""
    api = install_pipe_api(monkeypatch)
    listener = windows.WindowsNamedPipeListener(_ENDPOINT)
    listener.close()
    with pytest.raises(OSError, match="listener is closed"):
        listener.accept()
    assert len(api.created) == 1
    assert api.closed_handles == [0x100000001]
    assert api.connections == []


def test_listener_rejects_another_token_owner_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never transfer an accepted endpoint to an untrusted account."""
    api = install_pipe_api(monkeypatch)
    _trust_peer(monkeypatch, owner=False)
    listener = windows.WindowsNamedPipeListener(_ENDPOINT)
    try:
        with pytest.raises(PermissionError, match="another user"):
            listener.accept()
        assert api.connections[0].close_count == 1
    finally:
        listener.close()
    assert api.closed_handles == [0x100000002]


def test_no_data_connect_error_keeps_existing_accept_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain the native no-data branch without manufacturing an overlap result."""
    api = install_pipe_api(monkeypatch)
    api.connect_error = NativePipeError(232)
    _trust_peer(monkeypatch)
    listener = windows.WindowsNamedPipeListener(_ENDPOINT)
    try:
        accepted = listener.accept()
        assert api.wait_calls == []
        assert api.operation.waits == []
        accepted.close()
    finally:
        listener.close()
    assert api.connections[0].close_count == 1


@pytest.mark.parametrize(
    "failure", [NativePipeError(5), OSError("missing WinError metadata")]
)
def test_unexpected_connect_error_releases_only_the_transferred_handle(
    monkeypatch: pytest.MonkeyPatch,
    failure: OSError,
) -> None:
    """Preserve the native failure and close the active connection once."""
    api = install_pipe_api(monkeypatch)
    api.connect_error = failure
    listener = windows.WindowsNamedPipeListener(_ENDPOINT)
    try:
        with pytest.raises(OSError) as caught:
            listener.accept()
        assert caught.value is failure
        assert api.connections[0].close_count == 1
    finally:
        listener.close()
    assert api.closed_handles == [0x100000002]


def test_interrupted_wait_cancels_and_collects_before_releasing_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drain the native overlapped operation even when the caller is interrupted."""
    api = install_pipe_api(monkeypatch)
    failure = KeyboardInterrupt()

    def interrupt() -> None:
        """Raise at the native wait boundary without background thread timing."""
        raise failure

    api.on_wait = interrupt
    listener = windows.WindowsNamedPipeListener(_ENDPOINT)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            listener.accept()
        assert caught.value is failure
        assert api.operation.cancellations == 1
        assert api.operation.waits == [True]
        assert api.connections[0].close_count == 1
    finally:
        listener.close()


def test_failed_overlap_result_is_not_treated_as_an_accepted_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a failed native operation before authentication or ownership transfer."""
    api = install_pipe_api(monkeypatch)
    api.operation.native_error = 5
    listener = windows.WindowsNamedPipeListener(_ENDPOINT)
    try:
        with pytest.raises(OSError) as caught:
            listener.accept()
        assert caught.value.errno == 5
        assert api.operation.waits == [True]
        assert api.connections[0].close_count == 1
    finally:
        listener.close()


def test_shutdown_during_accept_owns_connection_cleanup_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve the close-versus-transfer interleaving without a second release."""
    api = install_pipe_api(monkeypatch)
    listener = windows.WindowsNamedPipeListener(_ENDPOINT)
    api.on_wait = listener.close
    with pytest.raises(OSError, match="listener is closed"):
        listener.accept()
    listener.close()
    assert api.connections[0].close_count == 1
    assert api.closed_handles == [0x100000002]
    assert api.operation.waits == [True]


@pytest.mark.parametrize("owner", [True, False], ids=["same-user", "foreign-user"])
def test_client_waits_boundedly_and_authenticates_server(
    monkeypatch: pytest.MonkeyPatch, owner: bool
) -> None:
    """Keep the AF_PIPE transport and token check on outgoing connections."""
    api = install_pipe_api(monkeypatch)
    _trust_peer(monkeypatch, owner=owner)
    calls: list[tuple[str, str]] = []

    def connect(address: str, *, family: str) -> PipeConnectionProbe:
        """Replace only the external stdlib client constructor."""
        calls.append((address, family))
        return api.make_connection(0x100000011)

    monkeypatch.setattr(windows, "Client", connect)
    if owner:
        connection = windows.connect_windows_named_pipe(_ENDPOINT)
        connection.close()
    else:
        with pytest.raises(PermissionError, match="another user"):
            windows.connect_windows_named_pipe(_ENDPOINT)
    assert api.client_waits == [(_ENDPOINT.address, 100)]
    assert calls == [(_ENDPOINT.address, "AF_PIPE")]
    assert api.connections[0].close_count == 1


@pytest.mark.parametrize(
    "incoming", [True, False], ids=["accepted-peer", "server-peer"]
)
@pytest.mark.parametrize(
    "close_fails", [False, True], ids=["close-succeeds", "close-fails"]
)
@pytest.mark.parametrize("query_boundary", ["pid", "sid"])
def test_identity_query_failure_releases_connection_before_propagating(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    incoming: bool,
    close_fails: bool,
    query_boundary: Literal["pid", "sid"],
) -> None:
    """Keep an unverified peer from leaving an unowned live connection behind."""
    api = install_pipe_api(monkeypatch)
    _trust_peer(monkeypatch)
    failure = OSError("controlled token query failure")

    def fail_identity_query() -> NoReturn:
        """Fail at an OS identity lookup boundary after connecting."""
        if close_fails:
            api.connections[0].close_error = OSError("controlled cleanup failure")
        raise failure

    if query_boundary == "pid":
        monkeypatch.setattr(
            windows,
            "_named_pipe_peer_process_id",
            lambda _handle, *, peer_is_server: fail_identity_query(),
        )
    else:
        monkeypatch.setattr(
            windows, "process_user_sid", lambda _pid: fail_identity_query()
        )
    monkeypatch.setattr(
        windows, "Client", lambda _address, *, family: api.make_connection(0x100000011)
    )
    listener = windows.WindowsNamedPipeListener(_ENDPOINT) if incoming else None
    try:
        with pytest.raises(OSError) as caught:
            if listener is not None:
                listener.accept()
            else:
                windows.connect_windows_named_pipe(_ENDPOINT)
        assert caught.value is failure
        assert api.connections[0].close_count == 1
        if close_fails:
            assert (
                "Failed to close unauthenticated application instance pipe"
                in caplog.text
            )
            assert "controlled cleanup failure" in caplog.text
    finally:
        if listener is not None:
            listener.close()
