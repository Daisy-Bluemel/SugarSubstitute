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

"""Preserve explicit document identity across both startup restoration paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from substitute.application.workflows.unsaved_work_service import (
    UnsavedWorkService,
    WorkflowDocumentState,
)
from substitute.application.workflows.workflow_session_service import (
    WorkflowSessionService,
)
from substitute.domain.workflow import WorkflowState
from substitute.domain.workspace_snapshot import (
    InputMaskReference,
    ShellLayoutSnapshot,
    WorkflowSnapshot,
    WorkspaceSnapshot,
)
from substitute.domain.workspace_snapshot.models import (
    WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
)
from substitute.presentation.shell.restore_projection_controller import (
    RestoreProjectionController,
)
from substitute.presentation.shell.session_snapshot_capture_adapter import (
    SessionSnapshotCaptureAdapter,
)
from substitute.presentation.shell.workspace_restore_controller import (
    WorkspaceRestoreController,
)


@dataclass
class _WorkflowViews:
    """Substitute the Qt tab boundary while retaining the real session owner."""

    session: WorkflowSessionService[WorkflowState]
    reject_registration: bool = False

    def reset_restored_workspace(self) -> None:
        """Remove existing workflow registrations without constructing widgets."""

        self.session.replace_workflows({}, active_workflow_id="")

    def add_restored_workflow(
        self, snapshot: WorkflowSnapshot, *, activate: bool
    ) -> None:
        """Register a workflow at the controlled tab-materialization boundary."""

        if self.reject_registration:
            raise RuntimeError("Workflow view creation failed")
        self.session.add_existing_workflow(
            snapshot.workflow_id, snapshot.workflow, activate=activate
        )


@dataclass
class _MaskViews:
    """Observe the document state available when restored mask media is loaded."""

    documents: UnsavedWorkService
    observed_states: list[WorkflowDocumentState] = field(default_factory=list)

    def restore_input_mask(self, reference: InputMaskReference) -> bool:
        """Record the saved workflow's identity before media restoration finishes."""

        self.observed_states.append(self.documents.state_for("saved"))
        return True


class _ProjectionViews(RestoreProjectionController):
    """Keep real restore finalization without constructing editor widgets."""

    def project_restored_workflow(self, workflow_id: str) -> None:
        """Accept a restored workflow projection at the Qt boundary."""

    def project_restored_settings(self) -> None:
        """Accept Settings projection at the Qt boundary."""


class _LayoutView:
    """Replace native geometry application with an immediate layout boundary."""

    def apply_restored_shell_layout(self, snapshot: ShellLayoutSnapshot | None) -> None:
        """Complete layout without deferring the restore finalization signal."""


@dataclass
class _FinalizedSignal:
    """Observe authoritative document state at the restore completion signal."""

    session: WorkflowSessionService[WorkflowState]
    documents: UnsavedWorkService
    observed_states: dict[str, WorkflowDocumentState] = field(default_factory=dict)

    def emit(self) -> None:
        """Capture each restored document when startup reports readiness."""

        self.observed_states = {
            workflow_id: self.documents.state_for(workflow_id)
            for workflow_id in self.session.workflows
        }


class _RestoreShell:
    """Compose real restore and document owners behind controlled Qt boundaries."""

    def __init__(self) -> None:
        """Prepare a shell capable of restoring cube-free workflow snapshots."""

        self.workflow_session_service = WorkflowSessionService(WorkflowState)
        self.unsaved_work_service = UnsavedWorkService()
        self.restored_workflow_materializer = _WorkflowViews(
            self.workflow_session_service
        )
        self.workspace_restore_image_adapter = _MaskViews(self.unsaved_work_service)
        self.restore_projection_controller = _ProjectionViews(self)
        self.shell_layout_restore_controller = _LayoutView()
        self.restore_finalized = _FinalizedSignal(
            self.workflow_session_service, self.unsaved_work_service
        )
        self.cube_load_service = object()
        self.node_behavior_service = object()
        self._shell_restore_lifecycle = "constructing"
        self._pending_restored_shell_layout: ShellLayoutSnapshot | None = None


def _snapshot(root: Path) -> WorkspaceSnapshot:
    """Include clean, edited, never-saved, and imported documents in one session."""

    values: tuple[tuple[str, bool, Path | None], ...] = (
        ("saved", False, root / "external.sugar"),
        ("edited", True, root / "edited.sugar"),
        ("unsaved", True, None),
        ("imported", False, root / "source.json"),
    )
    workflows = tuple(
        WorkflowSnapshot(
            workflow_id=workflow_id,
            tab_label=workflow_id,
            workflow=WorkflowState(),
            document_dirty=dirty,
            document_source_path=source,
            input_masks=(
                InputMaskReference(
                    mask_id="mask", image_id="image", path=root / "mask.png"
                ),
            )
            if workflow_id == "saved"
            else (),
        )
        for workflow_id, dirty, source in values
    )
    return WorkspaceSnapshot(
        schema_version=WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
        workflows=workflows,
        tab_order=tuple(workflow.workflow_id for workflow in workflows),
        active_route="saved",
        active_workflow_id="saved",
    )


@pytest.mark.parametrize("prehydrated", (False, True), ids=("ordinary", "prehydrated"))
def test_startup_restore_retains_document_state_for_next_capture(
    tmp_path: Path, prehydrated: bool
) -> None:
    """Both startup paths retain every document's dirty flag and exact save target."""

    shell = _RestoreShell()
    snapshot = _snapshot(tmp_path)
    expected = {
        workflow.workflow_id: WorkflowDocumentState(
            dirty=workflow.document_dirty, source_path=workflow.document_source_path
        )
        for workflow in snapshot.workflows
    }
    for workflow in snapshot.workflows:
        shell.unsaved_work_service.restore(
            workflow.workflow_id,
            dirty=not workflow.document_dirty,
            source_path=tmp_path / "stale.sugar",
        )
    controller = WorkspaceRestoreController(shell)

    if prehydrated:
        controller.install_hydrated_prehydrated_workspace(snapshot)
    else:
        assert controller.restore_initial_workspace_snapshot(snapshot)

    capture = SessionSnapshotCaptureAdapter(shell)
    for workflow_id, state in expected.items():
        assert shell.unsaved_work_service.state_for(workflow_id) == state
        assert capture.workflow_document_dirty(workflow_id) == state.dirty
        assert capture.workflow_document_source_path(workflow_id) == state.source_path
    assert shell.workflow_session_service.active_workflow_id == "saved"
    if not prehydrated:
        assert shell.restore_finalized.observed_states == expected
        assert shell._shell_restore_lifecycle == "running"


def test_ordinary_restore_binds_source_before_restoring_masks(tmp_path: Path) -> None:
    """Mask recovery must see the retained recipe source during materialization."""

    shell = _RestoreShell()

    assert WorkspaceRestoreController(shell).restore_initial_workspace_snapshot(
        _snapshot(tmp_path)
    )

    assert shell.workspace_restore_image_adapter.observed_states == [
        WorkflowDocumentState(dirty=False, source_path=tmp_path / "external.sugar")
    ]


def test_failed_workflow_registration_preserves_previous_document_state(
    tmp_path: Path,
) -> None:
    """A workflow that could not be materialized cannot replace saved identity."""

    shell = _RestoreShell()
    shell.restored_workflow_materializer.reject_registration = True
    shell.unsaved_work_service.restore(
        "saved", dirty=True, source_path=tmp_path / "previous.sugar"
    )
    previous = shell.unsaved_work_service.state_for("saved")

    assert not WorkspaceRestoreController(shell).restore_initial_workspace_snapshot(
        _snapshot(tmp_path)
    )

    assert shell.unsaved_work_service.state_for("saved") == previous
    assert shell.restore_finalized.observed_states == {}
    assert shell.workspace_restore_image_adapter.observed_states == []
