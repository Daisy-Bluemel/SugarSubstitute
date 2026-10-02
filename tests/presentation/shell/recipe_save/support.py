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

"""Mount real recipe persistence and document state behind controlled UI boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from sugarsubstitute_shared.localization import ApplicationText
from substitute.application.errors import (
    ErrorReport,
    SubstituteOperationContext,
    build_substitute_exception_report,
)
from substitute.application.recipes import RecipeIoService
from substitute.application.recipes.workflow_recipe_save_service import (
    RecipeInputPreparationPort,
)
from substitute.application.workflows.unsaved_work_service import UnsavedWorkService
from substitute.application.workflows.workflow_session_service import (
    WorkflowSessionService,
)
from substitute.domain.workflow import CubeState, WorkflowState
from tests.support.canonical_cube_graph import graph_backed_cube_workflow_from_states
from substitute.infrastructure.persistence.file_recipe_repository import (
    FileRecipeRepository,
)
from substitute.presentation.shell.workflow_file_context import WorkflowFileContext
from substitute.presentation.shell.workflow_recipe_save_actions import (
    WorkflowRecipeSaveActions,
)


@dataclass
class SaveDialog:
    """Return a controlled destination while observing whether the chooser opens."""

    destination: str
    calls: int = 0
    requested_filter: str = ""
    requested_directory: str = ""

    def getSaveFileName(
        self, parent: object, caption: str, directory: str, filter: str = ""
    ) -> tuple[str, str]:
        """Record one native chooser request without showing a dialog."""

        self.calls += 1
        self.requested_filter = filter
        self.requested_directory = directory
        return self.destination, filter


@dataclass
class SaveReports:
    """Capture structured feedback at the non-blocking presentation boundary."""

    reports: list[ErrorReport] = field(default_factory=list)

    def show_error_report(self, report: ErrorReport) -> None:
        """Record an expected user-action outcome."""

        self.reports.append(report)

    def show_exception_report(
        self,
        *,
        title: ApplicationText,
        message: ApplicationText,
        stage: str,
        error: BaseException,
        context: SubstituteOperationContext,
    ) -> None:
        """Keep real unexpected-error classification and diagnostic construction."""

        self.reports.append(
            build_substitute_exception_report(
                title=title, message=message, stage=stage, error=error, context=context
            )
        )

    def show_comfy_connection_report(
        self,
        *,
        title: ApplicationText,
        message: ApplicationText,
        stage: str,
        context: SubstituteOperationContext,
        error: BaseException | None = None,
    ) -> None:
        """Reject accidental routing of a local save through connectivity feedback."""

        raise AssertionError("Recipe saves do not present connection reports")


@dataclass(frozen=True)
class SavePaths:
    """Expose distinct project, script and Cube roots."""

    projects_dir: Path
    sugar_scripts_dir: Path
    cubes_dir: Path


class SaveTab:
    """Identify the one document being saved."""

    def __init__(self, name: str = "Recipe") -> None:
        """Store the authored display name independently from path normalization."""

        self._name = name

    def text(self) -> str:
        """Return its display name."""

        return self._name

    def routeKey(self) -> str:
        """Return its stable session identity."""

        return "workflow"


class SaveTabs:
    """Expose the active document without mounting unrelated shell widgets."""

    def __init__(self) -> None:
        """Create one stable tab."""

        self.itemMap = {"workflow": SaveTab()}

    def currentIndex(self) -> int:
        """Return the active index."""

        return 0

    def tabItem(self, index: int) -> SaveTab:
        """Resolve that tab."""

        assert index == 0
        return self.itemMap["workflow"]

    def workflow_ids_in_order(self) -> list[str]:
        """Return visible document ordering for shutdown checks."""

        return ["workflow"]


@dataclass(frozen=True)
class _FileActions:
    """Expose the new save owner to the production unsaved-work coordinator."""

    recipe_save_actions: WorkflowRecipeSaveActions


class SaveView:
    """Retain authoritative workflow/session/document state for the save actions."""

    input_recipe_save_preparation: RecipeInputPreparationPort

    def __init__(self, root: Path, workflow: WorkflowState) -> None:
        """Prepare real persistence, session identity and a dirty source baseline."""

        self.path_bundle = SavePaths(root, root / "scripts", root / "cubes")
        self.recipe_io_service = RecipeIoService(FileRecipeRepository())
        self.workflow_session_service = WorkflowSessionService(
            lambda: workflow, default_workflow_id="workflow"
        )
        self.unsaved_work_service = UnsavedWorkService()
        self.unsaved_work_service.mark_saved("workflow", root / "original.json")
        self.unsaved_work_service.mark_dirty("workflow")
        self.workflow_tabbar = SaveTabs()
        self.active_override_manager = None
        self.reports = SaveReports()
        self.workspace_file_actions = _FileActions(
            WorkflowRecipeSaveActions(
                self, context=WorkflowFileContext(self), error_presenter=self.reports
            )
        )

    def get_active_workflow(self) -> WorkflowState:
        """Return the real active graph or legacy stack."""

        return self.workflow_session_service.get_active_workflow()

    @property
    def destination(self) -> Path:
        """Return the real default-policy target."""

        return self.recipe_io_service.build_default_recipe_path(
            "Recipe", self.path_bundle.sugar_scripts_dir
        )


def make_save_view(
    root: Path, *, mixed: bool = False, legacy: bool = False
) -> SaveView:
    """Prepare a real canonical Cube graph and preserved input asset."""

    cube = CubeState(
        cube_id="test/Cube.cube",
        version="1.0.0",
        alias="Cube",
        original_cube={},
        buffer={
            "cube_id": "test/Cube.cube",
            "nodes": {},
            "inputs": {},
            "outputs": {},
            "surface": {"default_flavor_id": "default", "controls": []},
        },
    )
    workflow = graph_backed_cube_workflow_from_states(cube)
    direct = workflow.direct_workflow
    assert direct is not None
    if mixed:
        nodes = direct.source_workflow["nodes"]
        assert isinstance(nodes, list)
        nodes.append({"id": 20, "type": "LoadImage", "widgets_values": ["input.png"]})
    (root / "original.json").write_text(
        json.dumps(direct.source_workflow), encoding="utf-8"
    )
    (root / "input.png").write_bytes(b"preserved input asset")
    if legacy:
        workflow = WorkflowState(
            cubes=dict(workflow.cubes), stack_order=list(workflow.stack_order)
        )
    return SaveView(root, workflow)
