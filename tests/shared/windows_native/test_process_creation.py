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

"""Characterize atomic process creation and validation before native acquisition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys

import pytest

from sugarsubstitute_shared import windows_process_creation
from sugarsubstitute_shared.windows_process_job_api import StartupInfoEx
from tests.shared.windows_native.process_creation_boundary import (
    ProcessCreationBoundary,
)


@pytest.mark.parametrize("with_job", [False, True])
@pytest.mark.parametrize("separate_error", [False, True])
@pytest.mark.parametrize("with_cwd", [False, True])
def test_creation_transfers_only_returned_handles_after_atomic_admission(
    creation_boundary: ProcessCreationBoundary,
    tmp_path: Path,
    with_job: bool,
    separate_error: bool,
    with_cwd: bool,
) -> None:
    """Keep flags, Unicode quoting, handle lists, and job admission in one creation."""
    native = creation_boundary
    cwd = tmp_path / "work 路径" if with_cwd else None
    result = windows_process_creation.create_windows_process(
        ("fixture worker.exe", "two words", 'say "你好"', ""),
        environment={"z": "last", "a": "first", "B": "值"},
        cwd=cwd,
        output_fd=101,
        error_fd=202 if separate_error else None,
        creation_flags=0x02000010,
        job=native.job_handle if with_job else None,
    )
    assert (result.process, result.thread, result.pid, result.tid) == (
        native.process_handle,
        native.thread_handle,
        1234,
        5678,
    )
    assert native.loads == [("kernel32", True)]
    assert native.crt.converted == [303, 101, 202 if separate_error else 101]
    assert native.duplicates == [
        (
            native.current_process,
            native.handle_base + fd,
            native.current_process,
            0,
            True,
            2,
        )
        for fd in native.crt.converted
    ]
    assert native.opens == [(os.devnull, "rb")]
    assert native.null_input.entered and native.null_input.closed
    assert native.null_input.exit_error is None
    assert len(native.creations) == 1
    call = native.creations[0]
    assert call.application == "fixture worker.exe"
    assert call.command == '"fixture worker.exe" "two words" "say \\"你好\\"" ""'
    assert call.security == (None, None)
    assert call.inherit
    assert call.flags == 0x02080410
    assert call.environment == "a=first\0B=值\0z=last\0\0"
    assert call.cwd == (str(cwd) if cwd is not None else None)
    assert call.startup_size == ctypes.sizeof(StartupInfoEx)
    assert call.startup_flags == 0x00000100
    assert call.handles == native.duplicate_handles
    assert native.initializations == [
        (None, 2 if with_job else 1, 0, 0),
        (call.attributes, 2 if with_job else 1, 0, native.size),
    ]
    expected_updates: list[tuple[int, int, int, tuple[int, ...], int, None, None]] = [
        (
            call.attributes,
            0,
            0x00020002,
            native.duplicate_handles,
            3 * ctypes.sizeof(wintypes.HANDLE),
            None,
            None,
        ),
    ]
    if with_job:
        expected_updates.append(
            (
                call.attributes,
                0,
                0x0002000D,
                (native.job_handle,),
                ctypes.sizeof(wintypes.HANDLE),
                None,
                None,
            )
        )
    assert native.updates == expected_updates
    assert call.prior_events == (
        "probe",
        "initialize",
        "convert",
        "duplicate",
        "convert",
        "duplicate",
        "convert",
        "duplicate",
        "inherit",
        *(("job",) if with_job else ()),
    )
    assert native.deleted == [call.attributes]
    assert native.closed == list(native.duplicate_handles)
    assert native.events[-5:] == [
        "close-devnull",
        "delete",
        "close-handle",
        "close-handle",
        "close-handle",
    ]
    assert native.translated == []


def test_empty_environment_remains_double_nul_terminated(
    creation_boundary: ProcessCreationBoundary,
) -> None:
    """Create a process with an explicitly empty Unicode environment block."""
    native = creation_boundary
    windows_process_creation.create_windows_process(
        ("fixture",),
        environment={},
        cwd=None,
        output_fd=101,
        creation_flags=0,
    )
    assert native.creations[0].environment == "\0\0"
    assert native.creations[0].flags == 0x00080400


@pytest.mark.parametrize(
    ("command", "environment", "message"),
    [
        ((), {}, "command"),
        ((), {"": "invalid"}, "command"),
        (("bad\0command",), {}, "command"),
        (("fixture", "bad\0argument"), {}, "command"),
        (("fixture",), {"": "value"}, "environment"),
        (("fixture",), {"A=B": "value"}, "environment"),
        (("fixture",), {"A\0B": "value"}, "environment"),
        (("fixture",), {"A": "bad\0value"}, "environment"),
    ],
)
def test_invalid_input_fails_before_loading_or_converting(
    creation_boundary: ProcessCreationBoundary,
    command: Sequence[str],
    environment: Mapping[str, str],
    message: str,
) -> None:
    """Reject malformed arguments and environments before acquiring resources."""
    native = creation_boundary
    with pytest.raises(ValueError, match=message):
        windows_process_creation.create_windows_process(
            command,
            environment=environment,
            cwd=None,
            output_fd=101,
            creation_flags=0,
        )
    assert native.loads == []
    assert native.crt.converted == []
    assert native.opens == []
    assert native.initializations == []
    assert native.creations == []


@pytest.mark.parametrize(
    ("command", "environment"),
    [((), {}), (("fixture",), {"": "bad"})],
)
def test_crt_import_still_precedes_input_validation(
    creation_boundary: ProcessCreationBoundary,
    monkeypatch: pytest.MonkeyPatch,
    command: Sequence[str],
    environment: Mapping[str, str],
) -> None:
    """Retain the existing missing-CRT failure even for an invalid request."""
    monkeypatch.setitem(sys.modules, "msvcrt", None)
    with pytest.raises(ModuleNotFoundError, match="msvcrt"):
        windows_process_creation.create_windows_process(
            command,
            environment=environment,
            cwd=None,
            output_fd=101,
            creation_flags=0,
        )
    assert creation_boundary.loads == []
    assert creation_boundary.crt.converted == []


def test_loader_failure_preserves_identity_without_acquiring_resources(
    creation_boundary: ProcessCreationBoundary,
) -> None:
    """Surface unavailable native libraries before any attribute or fd ownership."""
    native = creation_boundary
    failure = OSError(126, "fixture missing kernel")
    native.load_failure = failure
    with pytest.raises(OSError) as caught:
        windows_process_creation.create_windows_process(
            ("fixture",),
            environment={},
            cwd=None,
            output_fd=101,
            creation_flags=0,
        )
    assert caught.value is failure
    assert native.loads == [("kernel32", True)]
    assert native.initializations == []
    assert native.crt.converted == []
    assert native.opens == []
    assert native.closed == []
    assert native.deleted == []
