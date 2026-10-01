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

"""Compose real Input admission owners around file and shell test boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from substitute.application.workflows import WorkflowTabService
from substitute.application.workflows.canvas_image_registry import CanvasImageRegistry
from substitute.application.workflows.input_canvas_binding_service import (
    InputCanvasBindingService,
)
from substitute.application.workflows.input_canvas_state_composition import (
    compose_input_canvas_state,
)
from substitute.application.workflows.input_image_materialization_service import (
    InputImageMaterializationService,
)
from substitute.application.workflows.input_mask_binding_materialization_service import (
    InputMaskBindingMaterializationService,
)
from substitute.application.workflows.input_mask_materialization_service import (
    InputMaskMaterializationService,
)
from substitute.application.workflows.input_section_materialization_service import (
    InputSectionMaterializationService,
)
from substitute.application.workflows.ordered_mask_materialization_service import (
    OrderedMaskMaterializationService,
)
from substitute.application.workflows.synthetic_input_canvas_surface_service import (
    SyntheticInputCanvasSurfaceService,
)
from substitute.application.workflows.workflow_asset_service import WorkflowAssetService
from substitute.application.workflows.workflow_graph_section_service import (
    WorkflowGraphSectionService,
)
from substitute.domain.workflow import CanvasSessionBoundary, WorkflowState
from substitute.presentation.canvas.input.input_route_projector import (
    InputRouteProjector,
)
from substitute.presentation.shell.workflow_document_target import (
    WorkflowSession,
    WorkflowTabBar,
)
from substitute.presentation.shell.workflow_surface_invalidation import (
    WorkflowSurfaceInvalidationService,
)
from tests.application.workflows.input_canvas.fakes import (
    _FakeCanvasIoService,
    _FakeImage,
)
from tests.application.workflows.input_canvas.support import _input_canvas_plan_service
from tests.presentation.shell.canvas_projection.support.input_document import (
    _FakeInputDocument,
)


@dataclass
class ImportSession:
    """Expose the shell session boundary without replacing workflow state owners."""

    workflows: Mapping[str, object]
    active_workflow_id: str = "imported"

    def get_workflow(self, workflow_id: str) -> object | None:
        """Return the requested live workflow state."""
        return self.workflows.get(workflow_id)


@dataclass
class ImportTab:
    """Retain one shell tab's identity and label during document loading."""

    label: str = "Untitled Workflow"

    def routeKey(self) -> str:
        """Return the blank import target's stable identity."""
        return "imported"

    def text(self) -> str:
        """Return the label used by the document target resolver."""
        return self.label

    def setText(self, text: str) -> None:
        """Apply the loaded document label at the shell boundary."""
        self.label = text


@dataclass
class ImportTabBar:
    """Expose the single blank import target through the shell tab contract."""

    itemMap: dict[str, ImportTab]

    def currentIndex(self) -> int:
        """Return the sole visible tab index."""
        return 0

    def tabItem(self, index: int) -> ImportTab:
        """Resolve the import tab by its visible index."""
        assert index == 0
        return self.itemMap["imported"]


@dataclass
class ImportView:
    """Hold typed shell collaborators for the public import action."""

    workflow_session_service: WorkflowSession
    workflow_tabbar: WorkflowTabBar
    workflow_tab_service: object
    workflow_surface_invalidation_service: object


def import_view(workflow: WorkflowState) -> ImportView:
    """Create a blank shell target around a real workflow state."""
    return ImportView(
        workflow_session_service=ImportSession({"imported": workflow}),
        workflow_tabbar=ImportTabBar({"imported": ImportTab()}),
        workflow_tab_service=WorkflowTabService(),
        workflow_surface_invalidation_service=WorkflowSurfaceInvalidationService(),
    )


@dataclass
class InputAdmission:
    """Expose section restoration and the observable renderer boundary."""

    sections: InputSectionMaterializationService
    document: _FakeInputDocument


def input_admission(tmp_path: Path) -> InputAdmission:
    """Use real binding, materialization, asset, and route owners without Qt widgets."""
    document = _FakeInputDocument()
    session_boundary = CanvasSessionBoundary()
    state = compose_input_canvas_state(
        document=document,
        route_projector=InputRouteProjector(
            document, session_boundary=session_boundary
        ),
        session_boundary=session_boundary,
        image_registry=CanvasImageRegistry(),
    )
    graph_sections = WorkflowGraphSectionService()
    assets = WorkflowAssetService(graph_sections)
    canvas_io = _FakeCanvasIoService(
        image=_FakeImage(),
        expected_mask_path=tmp_path / "unused-mask.png",
        created_destinations=[],
    )
    bindings = InputCanvasBindingService(
        plans=_input_canvas_plan_service(), graph_sections=graph_sections
    )
    masks = InputMaskBindingMaterializationService(
        scalar_service=InputMaskMaterializationService(
            input_masks=state.masks,
            canvas_io_service=canvas_io,
            workflow_asset_service=assets,
            graph_section_service=graph_sections,
        ),
        ordered_service=OrderedMaskMaterializationService(
            input_masks=state.masks,
            mask_visuals=state.mask_visuals,
            canvas_io_service=canvas_io,
            graph_section_service=graph_sections,
        ),
    )
    return InputAdmission(
        sections=InputSectionMaterializationService(
            bindings=bindings,
            images=InputImageMaterializationService(
                bindings=bindings,
                images=state.images,
                canvas_io=canvas_io,
                mask_materialization=masks,
                workflow_assets=assets,
                graph_sections=graph_sections,
            ),
            mask_materialization=masks,
            synthetic_surfaces=SyntheticInputCanvasSurfaceService(
                input_images=state.images,
                input_cleanup=state.cleanup,
                canvas_io_service=canvas_io,
            ),
            graph_sections=graph_sections,
        ),
        document=document,
    )
