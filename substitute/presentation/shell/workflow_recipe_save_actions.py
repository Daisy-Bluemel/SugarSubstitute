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

"""Own explicit Sugar Script save decisions, persistence outcomes and user feedback."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from PySide6.QtWidgets import QFileDialog

from sugarsubstitute_shared.presentation.localization import (
    app_text,
    render_application_text,
)
from substitute.application.errors import (
    DiagnosticSeverity,
    ErrorReport,
    ErrorReportKind,
    SubstituteOperationContext,
)
from substitute.application.recipes import RecipeIoService
from substitute.application.recipes.workflow_recipe_save_service import (
    RecipeInputPreparationPort,
    WorkflowRecipeSaveService,
)
from substitute.application.recipes.sugarscript_graph_projection import (
    UnsupportedSugarScriptGraphError,
    explicit_sugarscript_connections,
)
from substitute.application.workflows.workflow_session_service import (
    WorkflowSessionService,
)
from substitute.domain.workflow import WorkflowState
from substitute.presentation.errors import ErrorPresenter, ErrorReportPresenterProtocol
from substitute.presentation.shell.workflow_file_context import WorkflowFileContext
from substitute.shared.logging.logger import get_logger, log_exception
from substitute.shared.util.path_safety import validate_top_level_name

_LOGGER = get_logger("presentation.shell.workflow_recipe_save_actions")


class RecipeSaveDialog(Protocol):
    """Choose a Sugar Script destination at the native file-dialog boundary."""

    def getSaveFileName(
        self, parent: object, caption: str, directory: str, filter: str = ""
    ) -> tuple[str, str]:
        """Return the chosen path, or an empty path when cancelled."""


class _WorkflowTab(Protocol):
    """Expose a workflow display name."""

    def text(self) -> str:
        """Return the active tab name."""


class _WorkflowTabs(Protocol):
    """Expose the active tab's display identity."""

    def currentIndex(self) -> int:
        """Return the active tab index."""

    def tabItem(self, index: int) -> _WorkflowTab:
        """Resolve one tab."""


class WorkflowRecipeSaveView(Protocol):
    """Expose only the authoritative collaborators required for an explicit save."""

    @property
    def workflow_tabbar(self) -> _WorkflowTabs:
        """Return the current workflow tabs."""

    @property
    def workflow_session_service(self) -> WorkflowSessionService[WorkflowState]:
        """Return the active workflow identity owner."""

    @property
    def recipe_io_service(self) -> RecipeIoService:
        """Return the recipe persistence use-case owner."""

    @property
    def input_recipe_save_preparation(self) -> RecipeInputPreparationPort:
        """Return the live Input mask capture and immutable-product owner."""

    def get_active_workflow(self) -> WorkflowState:
        """Return the authoritative active workflow."""


class WorkflowRecipeSaveActions:
    """Save losslessly representable workflows and explain refused or failed saves."""

    def __init__(
        self,
        view: WorkflowRecipeSaveView,
        *,
        context: WorkflowFileContext,
        error_presenter: ErrorReportPresenterProtocol | None = None,
    ) -> None:
        """Compose save actions with shared context and a non-blocking presenter."""

        self._view = view
        self._context = context
        self._presenter = (
            error_presenter
            if error_presenter is not None
            else ErrorPresenter(parent=view)
        )

    def on_save_clicked(self, *, sugar_scripts_dir: Path | None = None) -> bool:
        """Save to the workflow-named script path and acknowledge only success."""

        return self._save(sugar_scripts_dir=sugar_scripts_dir, file_dialog=None)

    def on_save_as_clicked(
        self,
        *,
        sugar_scripts_dir: Path | None = None,
        file_dialog: RecipeSaveDialog = cast(RecipeSaveDialog, QFileDialog),
    ) -> bool:
        """Check representability before requesting a user-selected destination."""

        return self._save(sugar_scripts_dir=sugar_scripts_dir, file_dialog=file_dialog)

    def _save(
        self, *, sugar_scripts_dir: Path | None, file_dialog: RecipeSaveDialog | None
    ) -> bool:
        """Keep expected format refusals distinct from unexpected persistence errors."""

        view = self._view
        workflow_name = "untitled_workflow"
        workflow_id: str | None = None
        destination: Path | None = None
        try:
            workflow_id = view.workflow_session_service.active_workflow_id
            index = view.workflow_tabbar.currentIndex()
            if index >= 0:
                workflow_name = view.workflow_tabbar.tabItem(index).text()
            workflow = view.get_active_workflow()
            explicit_sugarscript_connections(workflow.direct_workflow)
            root = self._context.sugar_scripts_dir(sugar_scripts_dir)
            destination = view.recipe_io_service.build_default_recipe_path(
                workflow_name, root
            )
            if file_dialog is not None:
                selected, _ = file_dialog.getSaveFileName(
                    view,
                    render_application_text(app_text("Save Sugar Script As...")),
                    str(destination),
                    render_application_text(app_text("Sugar Script (%1)", "*.sugar")),
                )
                if not selected:
                    return False
                destination = view.recipe_io_service.validate_recipe_destination(
                    Path(selected).resolve()
                )
            scopes = self._context.global_override_scopes()
            WorkflowRecipeSaveService(
                recipes=view.recipe_io_service,
                input_preparation=lambda: view.input_recipe_save_preparation,
            ).save(
                destination=destination,
                workflow_id=workflow_id,
                workflow_name=(
                    validate_top_level_name(workflow_name, subject="Workflow")
                    if file_dialog is None
                    else workflow_name
                ),
                workflow=workflow,
                global_override_scopes=scopes,
            )
            self._context.mark_saved(workflow_id, destination)
            return True
        except UnsupportedSugarScriptGraphError:
            self._presenter.show_error_report(
                ErrorReport(
                    kind=ErrorReportKind.DOCUMENT_SAVE,
                    severity=DiagnosticSeverity.WARNING,
                    title=app_text("Cannot save as Sugar Script"),
                    message=app_text(
                        "This workflow contains nodes that Sugar Script cannot preserve. Choose “Export to Comfy Workflow...” to save the complete workflow."
                    ),
                    stage="save",
                    workflow_id=workflow_id,
                    operation_context=SubstituteOperationContext(
                        operation="save_workflow_recipe",
                        workflow_id=workflow_id,
                        workflow_name=workflow_name,
                    ),
                )
            )
            return False
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as error:
            log_exception(
                _LOGGER,
                "Failed to save recipe",
                workflow_name=workflow_name,
                workflow_id=workflow_id,
                destination_path=str(destination) if destination is not None else None,
            )
            self._presenter.show_exception_report(
                title=app_text("Save Sugar Script failed"),
                message=app_text(
                    "The workflow could not be saved. Your changes remain open."
                ),
                stage="save",
                error=error,
                context=SubstituteOperationContext(
                    operation="save_workflow_recipe",
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    path=str(destination) if destination is not None else None,
                ),
            )
            return False
