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

"""Verify the persistence guard, complete JSON export and non-blocking save feedback."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import json
from pathlib import Path

import pytest

from substitute.application.errors import (
    DiagnosticSeverity,
    ErrorReport,
    ErrorReportKind,
)
from substitute.application.recipes.sugarscript_graph_projection import (
    UnsupportedSugarScriptGraphError,
)
from substitute.application.recipes.workflow_export_service import WorkflowExportService
from substitute.domain.common import JsonObject
from substitute.infrastructure.persistence.file_workflow_repository import (
    FileWorkflowRepository,
)
from substitute.presentation.errors import ErrorPresenter
from substitute.presentation.shell.workflow_file_context import WorkflowFileContext
from substitute.presentation.shell.workflow_recipe_save_actions import (
    WorkflowRecipeSaveActions,
)
from .support import make_save_view


class _NoSugarCompiler:
    """Reject any attempt to convert a canonical graph through Sugar Script."""

    def compile_workflow_payload(
        self, *, sugar_script_text: str, output_dir: Path
    ) -> JsonObject:
        """Fail if export leaves canonical graph authority."""

        raise AssertionError("Mixed-graph export must not compile Sugar Script")


def test_direct_recipe_save_guard_preserves_existing_target_and_assets(
    tmp_path: Path,
) -> None:
    """The IO boundary remains safe even when a caller bypasses UI preflight."""

    view = make_save_view(tmp_path, mixed=True)
    destination = tmp_path / "existing.sugar"
    destination.write_bytes(b"previous recipe")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    workflow = deepcopy(view.get_active_workflow())

    with pytest.raises(UnsupportedSugarScriptGraphError):
        view.recipe_io_service.save_workflow_recipe(
            destination, workflow_name="Recipe", workflow=view.get_active_workflow()
        )

    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before
    assert not (tmp_path / "versions").exists()
    assert view.get_active_workflow() == workflow


def test_refused_script_can_export_complete_json_without_mutating_source(
    tmp_path: Path,
) -> None:
    """The recommended format retains ordinary nodes and their asset references."""

    view = make_save_view(tmp_path, mixed=True)
    workflow = view.get_active_workflow()
    direct = workflow.direct_workflow
    assert direct is not None
    graph = deepcopy(direct.source_workflow)
    original = (tmp_path / "original.json").read_bytes()
    asset = (tmp_path / "input.png").read_bytes()
    state = view.unsaved_work_service.state_for("workflow")
    assert view.workspace_file_actions.recipe_save_actions.on_save_clicked() is False
    destination = tmp_path / "complete.json"
    service = WorkflowExportService(FileWorkflowRepository(), _NoSugarCompiler())

    payload = service.export_workflow_json(
        destination_path=destination,
        sugar_script_text=None,
        output_dir=tmp_path,
        workflow=workflow,
    )

    assert json.loads(destination.read_text()) == graph
    assert payload == graph and payload is not direct.source_workflow
    assert direct.source_workflow == graph
    assert (tmp_path / "original.json").read_bytes() == original
    assert (tmp_path / "input.png").read_bytes() == asset
    assert view.unsaved_work_service.state_for("workflow") == state


class _Finished:
    """Expose only the completion-signal boundary used by ErrorPresenter."""

    def __init__(self) -> None:
        """Collect one dialog's completion callbacks."""

        self.callbacks: list[Callable[[int], None]] = []

    def connect(self, callback: Callable[[int], None]) -> None:
        """Retain a queued-dialog completion callback."""

        self.callbacks.append(callback)


class _Dialog:
    """Model the non-blocking dialog API deliberately without an exec method."""

    def __init__(self) -> None:
        """Start with an unopened, retained dialog."""

        self.finished = _Finished()
        self.opened = False
        self.deleted = False

    def open(self) -> None:
        """Record presentation without entering an event loop."""

        self.opened = True

    def deleteLater(self) -> None:
        """Observe release of the presenter-owned dialog."""

        self.deleted = True


def test_format_warning_uses_real_non_blocking_presenter(tmp_path: Path) -> None:
    """Refusal returns safely while a localized warning remains visible."""

    view = make_save_view(tmp_path, mixed=True)
    reports: list[ErrorReport] = []
    dialog = _Dialog()

    def create_dialog(
        parent: object | None,
        report: ErrorReport,
        text: str,
        open_console: Callable[[], None] | None,
    ) -> object:
        """Capture the rendered warning at the external dialog boundary."""

        assert parent is view
        assert "Export to Comfy Workflow" in text
        reports.append(report)
        return dialog

    presenter = ErrorPresenter(parent=view, dialog_factory=create_dialog)
    actions = WorkflowRecipeSaveActions(
        view, context=WorkflowFileContext(view), error_presenter=presenter
    )

    assert actions.on_save_clicked() is False
    assert dialog.opened and not dialog.deleted
    assert reports[0].severity is DiagnosticSeverity.WARNING
    assert reports[0].kind is ErrorReportKind.DOCUMENT_SAVE
    assert reports[0].traceback == ()
    assert view.unsaved_work_service.state_for("workflow").dirty
    for callback in dialog.finished.callbacks:
        callback(0)
    assert dialog.deleted
