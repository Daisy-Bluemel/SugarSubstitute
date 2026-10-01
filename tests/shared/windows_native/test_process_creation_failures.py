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

"""Prove error identity and owned-resource cleanup throughout process creation."""

from __future__ import annotations

import pytest

from sugarsubstitute_shared import windows_process_creation
from tests.shared.windows_native.process_creation_boundary import (
    ProcessCreationBoundary,
)


@pytest.mark.parametrize("code", [0, 5, 87])
@pytest.mark.parametrize("operation", ["probe", "initialize"])
def test_attribute_setup_failure_never_deletes_an_uninitialized_list(
    creation_boundary: ProcessCreationBoundary,
    code: int,
    operation: str,
) -> None:
    """Preserve setup errors without treating allocation as successful initialization."""
    native = creation_boundary
    native.failures[operation] = code
    if operation == "probe":
        native.size = 0
    with pytest.raises(OSError) as caught:
        windows_process_creation.create_windows_process(
            ("fixture",),
            environment={},
            cwd=None,
            output_fd=101,
            creation_flags=0,
        )
    assert caught.value is native.errors[code]
    assert native.translated == [code]
    assert len(native.initializations) == (1 if operation == "probe" else 2)
    assert native.deleted == []
    assert native.closed == []
    assert native.opens == []
    assert native.crt.converted == []
    assert native.creations == []


@pytest.mark.parametrize("position", [1, 2, 3])
def test_crt_failure_closes_only_prior_acquired_duplicates(
    creation_boundary: ProcessCreationBoundary,
    position: int,
) -> None:
    """Keep the original conversion exception through devnull and native cleanup."""
    native = creation_boundary
    native.crt.failure_at = position
    with pytest.raises(OSError) as caught:
        windows_process_creation.create_windows_process(
            ("fixture",),
            environment={},
            cwd=None,
            output_fd=101,
            error_fd=202,
            creation_flags=0,
            job=native.job_handle,
        )
    assert caught.value is native.crt.failure
    assert native.crt.converted == [303, 101, 202][:position]
    assert len(native.duplicates) == position - 1
    assert native.closed == list(native.duplicate_handles[: position - 1])
    assert native.deleted == [native.initializations[1][0]]
    assert native.null_input.closed
    assert native.null_input.exit_error is caught.value
    assert native.translated == []
    assert native.updates == []
    assert native.creations == []


@pytest.mark.parametrize("code", [0, 5, 87])
@pytest.mark.parametrize("position", [1, 2, 3])
def test_duplicate_failure_captures_error_before_partial_cleanup(
    creation_boundary: ProcessCreationBoundary,
    code: int,
    position: int,
) -> None:
    """Close prior duplicates once without closing caller descriptors or the job."""
    native = creation_boundary
    native.failures[f"duplicate-{position}"] = code
    with pytest.raises(OSError) as caught:
        windows_process_creation.create_windows_process(
            ("fixture",),
            environment={},
            cwd=None,
            output_fd=101,
            error_fd=202,
            creation_flags=0,
            job=native.job_handle,
        )
    assert caught.value is native.errors[code]
    assert native.translated == [code]
    assert native.crt.converted == [303, 101, 202][:position]
    assert len(native.duplicates) == position
    assert native.closed == list(native.duplicate_handles[: position - 1])
    assert native.deleted == [native.initializations[1][0]]
    assert native.null_input.closed
    assert native.null_input.exit_error is caught.value
    assert native.events.index("translate-error") < native.events.index("close-devnull")
    assert native.last_error == (999 if position == 1 else 1000)
    assert native.updates == []
    assert native.creations == []


@pytest.mark.parametrize("code", [0, 5, 87])
@pytest.mark.parametrize("operation", ["inherit", "job", "create"])
def test_admission_or_creation_failure_preserves_error_through_all_cleanup(
    creation_boundary: ProcessCreationBoundary,
    code: int,
    operation: str,
) -> None:
    """Prevent process transfer after failed inheritance, job admission, or creation."""
    native = creation_boundary
    native.failures[operation] = code
    with pytest.raises(OSError) as caught:
        windows_process_creation.create_windows_process(
            ("fixture",),
            environment={},
            cwd=None,
            output_fd=101,
            error_fd=202,
            creation_flags=0,
            job=native.job_handle,
        )
    assert caught.value is native.errors[code]
    assert native.translated == [code]
    assert len(native.updates) == (1 if operation == "inherit" else 2)
    assert len(native.creations) == (1 if operation == "create" else 0)
    assert native.closed == list(native.duplicate_handles)
    assert native.deleted == [native.initializations[1][0]]
    assert native.null_input.closed
    assert native.null_input.exit_error is caught.value
    assert native.events.index("translate-error") < native.events.index("close-devnull")
    assert native.last_error == 1000


def test_devnull_open_failure_releases_initialized_attributes(
    creation_boundary: ProcessCreationBoundary,
) -> None:
    """Release the attribute list even when no devnull context can be entered."""
    native = creation_boundary
    failure = OSError(24, "fixture no file descriptors available")
    native.open_failure = failure
    with pytest.raises(OSError) as caught:
        windows_process_creation.create_windows_process(
            ("fixture",),
            environment={},
            cwd=None,
            output_fd=101,
            creation_flags=0,
        )
    assert caught.value is failure
    assert native.deleted == [native.initializations[1][0]]
    assert native.closed == []
    assert native.crt.converted == []
    assert not native.null_input.entered
    assert not native.null_input.closed
    assert native.creations == []
    assert native.translated == []
