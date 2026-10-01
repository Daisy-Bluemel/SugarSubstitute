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

"""Verify mask edits dirty their owning documents before recovery persistence."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from substitute.application.workflows.unsaved_work_service import UnsavedWorkService
from substitute.domain.workflow import WorkflowState
from substitute.presentation.shell.input_mask_unsaved_work_observer import (
    InputMaskUnsavedWorkObserver,
)
from substitute.presentation.shell.session_autosave_controller import (
    SessionAutosaveController,
)


class _Edits:
    """Deliver identified document events without constructing a canvas widget."""

    def __init__(self) -> None:
        """Initialize the external event boundary without subscribers."""

        self._callbacks: list[Callable[[UUID], None]] = []

    def connect(self, callback: Callable[[UUID], None]) -> None:
        """Register one mask edit consumer."""

        self._callbacks.append(callback)

    def emit(self, image_id: UUID) -> None:
        """Publish the original edit identity independently of tab selection."""

        for callback in self._callbacks:
            callback(image_id)


def test_mask_edit_marks_exact_inactive_owner_before_autosave() -> None:
    """Only authoritative image membership determines the dirty document."""

    image_id = uuid4()
    owner, other = WorkflowState(), WorkflowState()
    owner.canvas.bind_image("Cube:Image", image_id)
    other.canvas.bind_image("Other:Image", uuid4())
    workflows = {"owner": owner, "other": other}
    service = UnsavedWorkService()
    service.mark_saved("owner", Path("owner.sugar"))
    service.mark_saved("other", Path("other.sugar"))
    edits = _Edits()
    autosaves: list[tuple[bool, bool]] = []
    invalidated: list[str] = []
    observer = InputMaskUnsavedWorkObserver(
        edits=edits,
        workflows=lambda: workflows,
        unsaved_work=service,
        edits_muted=lambda: False,
        mark_workflow_changed=invalidated.append,
        request_autosave=lambda: autosaves.append(
            (service.state_for("owner").dirty, service.state_for("other").dirty)
        ),
    )

    edits.emit(image_id)

    assert observer is not None
    assert autosaves == [(True, False)]
    assert invalidated == ["owner"]
    assert service.state_for("owner").source_path == Path("owner.sugar")
    assert service.state_for("other").dirty is False


@pytest.mark.parametrize("owner_count", (0, 2))
def test_unknown_or_ambiguous_image_does_not_dirty_a_workflow(owner_count: int) -> None:
    """Reject absent or nonunique ownership without guessing from presentation."""

    image_id = uuid4()
    workflows = {str(index): WorkflowState() for index in range(owner_count)}
    for workflow in workflows.values():
        workflow.canvas.bind_image("Cube:Image", image_id)
    service = UnsavedWorkService()
    edits = _Edits()
    autosaves: list[None] = []
    invalidated: list[str] = []
    InputMaskUnsavedWorkObserver(
        edits=edits,
        workflows=lambda: workflows,
        unsaved_work=service,
        edits_muted=lambda: False,
        mark_workflow_changed=invalidated.append,
        request_autosave=lambda: autosaves.append(None),
    )

    edits.emit(image_id)

    assert service.dirty_workflow_ids(tuple(workflows)) == ()
    assert autosaves == []
    assert invalidated == []


@pytest.mark.parametrize(
    "lifecycle", ("constructing", "prehydrating", "restoring", "gui_reloading")
)
def test_muted_mask_edit_preserves_restored_document_state(lifecycle: str) -> None:
    """Suppressed restoration callbacks cannot introduce a dirty document."""

    image_id = uuid4()
    workflow = WorkflowState()
    workflow.canvas.bind_image("Cube:Image", image_id)
    service = UnsavedWorkService()
    service.mark_saved("owner", Path("saved.sugar"))
    edits = _Edits()
    autosaves: list[None] = []
    invalidated: list[str] = []
    shell = _LifecycleShell(lifecycle)
    controller = SessionAutosaveController(shell)
    InputMaskUnsavedWorkObserver(
        edits=edits,
        workflows=lambda: {"owner": workflow},
        unsaved_work=service,
        edits_muted=controller.session_autosave_muted,
        mark_workflow_changed=invalidated.append,
        request_autosave=lambda: autosaves.append(None),
    )

    edits.emit(image_id)

    assert service.state_for("owner").dirty is False
    assert autosaves == []
    assert invalidated == []


class _LifecycleShell:
    """Expose only the production restoration lifecycle required by mute policy."""

    def __init__(self, lifecycle: str) -> None:
        """Retain the exact lifecycle value consumed by the real controller."""

        self._shell_restore_lifecycle = lifecycle
