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

"""Compose real startup media owners behind controlled shell view boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from cutecanvas import PreparedDocumentRestore
from PySide6.QtGui import QImage

from substitute.application.workflows.canvas_route_projector_port import (
    create_canvas_session_boundary,
)
from substitute.application.workflows.input_image_asset_service import (
    InputImageAssetService,
)
from substitute.application.workflows.input_mask_restoration_service import (
    InputMaskRestorationService,
)
from substitute.application.workflows.input_mask_visual_state_service import (
    InputMaskVisualStateService,
)
from substitute.application.workflows.input_route_projection_service import (
    InputRouteProjectionService,
)
from substitute.application.workflows.unsaved_work_service import UnsavedWorkService
from substitute.application.workflows.workflow_session_service import (
    WorkflowSessionService,
)
from substitute.domain.workflow import WorkflowState
from substitute.domain.workspace_snapshot import ShellLayoutSnapshot, WorkflowSnapshot
from substitute.presentation.canvas.input.input_document import InputCanvasDocument
from substitute.presentation.canvas.input.input_editable_document_lifecycle import (
    InputEditableDocumentLifecycle,
)
from substitute.presentation.canvas.input.input_route_projector import (
    InputRouteProjector,
)
from substitute.presentation.shell.restore_projection_controller import (
    RestoreProjectionController,
)
from substitute.presentation.shell.shell_prehydrated_restore_controller import (
    ShellPrehydratedRestoreController,
)
from substitute.presentation.shell.workspace_restore_controller import (
    WorkspaceRestoreController,
)
from substitute.presentation.shell.workspace_restore_image_adapter import (
    WorkspaceRestoreImageAdapter,
)


class PreparedArchive:
    """Supply already decoded archive authority at the startup worker boundary."""

    def __init__(self, prepared: PreparedDocumentRestore) -> None:
        """Retain the prepared document without another filesystem read."""
        self.prepared = prepared

    def prepared_editable_document(self) -> PreparedDocumentRestore:
        """Return the completed background preparation result."""
        return self.prepared


class RestoreViews:
    """Replace workflow widgets, layout, and completion signals with local state."""

    def __init__(self, session: WorkflowSessionService[WorkflowState]) -> None:
        """Retain the real workflow session at the view registration boundary."""
        self.session = session
        self.finalized = False

    def reset_restored_workspace(self) -> None:
        """Reset registrations without discarding the retained Input document."""
        self.session.replace_workflows({}, active_workflow_id="")

    def add_restored_workflow(
        self, snapshot: WorkflowSnapshot, *, activate: bool
    ) -> None:
        """Register restored state without constructing workflow widgets."""
        self.session.add_existing_workflow(
            snapshot.workflow_id, snapshot.workflow, activate=activate
        )

    def add_prehydrated_workflow(
        self, snapshot: WorkflowSnapshot, *, activate: bool
    ) -> None:
        """Register pre-show state at the same controlled widget boundary."""
        self.add_restored_workflow(snapshot, activate=activate)

    def apply_restored_shell_layout(self, snapshot: ShellLayoutSnapshot | None) -> None:
        """Complete layout without native window geometry."""

    def emit(self) -> None:
        """Record startup completion at the signal boundary."""
        self.finalized = True

    def reconcile(self, workflows: Mapping[str, WorkflowState]) -> int:
        """Accept empty regional collections at the unrelated regional boundary."""
        return 0


class ProjectionViews(RestoreProjectionController):
    """Keep real finalization without projecting editor widgets."""

    def project_restored_workflow(self, workflow_id: str) -> None:
        """Accept projection without mounting an editor panel."""


class ImageFiles:
    """Read real image files and observe editable authority before media fallback."""

    def __init__(self, document: InputCanvasDocument, mask_id: UUID) -> None:
        """Retain the document and archived mask being recovered."""
        self.document = document
        self.mask_id = mask_id
        self.mask_at_image_load: list[QImage | None] = []

    def load_input_image(self, path: Path) -> QImage:
        """Capture the recovered mask before any file-backed image is admitted."""
        self.mask_at_image_load.append(self.document.export_mask_image(self.mask_id))
        return QImage(str(path))


class RestoreShell:
    """Exercise real startup orchestration and Input recovery without a main window."""

    def __init__(
        self, document: InputCanvasDocument, archive: Path, mask_id: UUID
    ) -> None:
        """Compose authoritative Input and workspace owners with view-only doubles."""
        self.workflow_session_service = WorkflowSessionService(WorkflowState)
        self.unsaved_work_service = UnsavedWorkService()
        views = RestoreViews(self.workflow_session_service)
        self.restored_workflow_materializer = views
        self.restore_projection_controller = ProjectionViews(self)
        self.shell_layout_restore_controller = views
        self.restore_finalized = views
        self.restored_ordered_mask_collections = views
        self.canvas_io_service = ImageFiles(document, mask_id)
        boundary = create_canvas_session_boundary()
        routes = InputRouteProjectionService(
            projector=InputRouteProjector(document, session_boundary=boundary),
            session_boundary=boundary,
        )
        self.input_image_assets = InputImageAssetService(
            document=document, routes=routes
        )
        self.input_mask_restoration = InputMaskRestorationService(
            document=document,
            routes=routes,
            visuals=InputMaskVisualStateService(document),
        )
        self.input_editable_document_lifecycle = InputEditableDocumentLifecycle(
            document=document.editable_persistence,
            archive_path=archive,
        )
        self.workspace_restore_image_adapter = WorkspaceRestoreImageAdapter(self)
        self.workspace_restore_controller = WorkspaceRestoreController(self)
        self.shell_prehydrated_restore_controller = ShellPrehydratedRestoreController(
            self
        )
        self.shell_prehydrated_restore_controller.initialize_restore_state()
        self.cube_load_service = object()
        self.node_behavior_service = object()
        self._initial_workspace_hydrated = False
        self._pending_restored_shell_layout: ShellLayoutSnapshot | None = None
        self._restore_asset_preload: PreparedArchive | None = None
