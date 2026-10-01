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

"""Require visible save outcomes without losing graph, document or file state."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtWidgets import QWidget

from substitute.application.errors import DiagnosticSeverity
from substitute.application.workflows.unsaved_work_service import UnsavedWorkDecision
from substitute.presentation.shell.unsaved_work_controller import UnsavedWorkController
from .support import SaveDialog, SaveTab, make_save_view


def _files(root: Path) -> dict[str, bytes]:
    """Capture every project artifact, including unexpected backups or partial files."""

    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("save_as", (False, True))
@pytest.mark.parametrize("legacy", (False, True))
def test_success_persists_real_recipe_and_marks_exact_document_saved(
    tmp_path: Path, save_as: bool, legacy: bool
) -> None:
    """Both formats and entry points acknowledge a durable explicit save."""

    view = make_save_view(tmp_path, legacy=legacy)
    destination = tmp_path / "custom.sugar" if save_as else view.destination
    before = deepcopy(view.get_active_workflow())
    actions = view.workspace_file_actions.recipe_save_actions
    result = (
        actions.on_save_as_clicked(file_dialog=SaveDialog(str(destination)))
        if save_as
        else actions.on_save_clicked()
    )

    assert result is True
    assert 'use "test/Cube.cube"@1.0.0 as Cube' in destination.read_text(
        encoding="utf-8"
    )
    state = view.unsaved_work_service.state_for("workflow")
    assert state.dirty is False
    assert state.source_path == destination.resolve()
    assert view.get_active_workflow() == before
    assert view.reports.reports == []


@pytest.mark.parametrize("save_as", (False, True))
@pytest.mark.parametrize("existing_target", (False, True))
def test_mixed_graph_refusal_preserves_files_session_and_dirty_state(
    tmp_path: Path, save_as: bool, existing_target: bool
) -> None:
    """An unsupported conversion is visible and never writes or rotates a target."""

    view = make_save_view(tmp_path, mixed=True)
    destination = tmp_path / "custom.sugar" if save_as else view.destination
    if existing_target:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"existing recipe must survive")
    files = _files(tmp_path)
    workflow = deepcopy(view.get_active_workflow())
    state = view.unsaved_work_service.state_for("workflow")
    dialog = SaveDialog(str(destination))
    actions = view.workspace_file_actions.recipe_save_actions

    result = (
        actions.on_save_as_clicked(file_dialog=dialog)
        if save_as
        else actions.on_save_clicked()
    )

    assert result is False
    assert _files(tmp_path) == files
    assert view.get_active_workflow() == workflow
    assert view.workflow_session_service.active_workflow_id == "workflow"
    assert view.unsaved_work_service.state_for("workflow") == state
    assert len(view.reports.reports) == 1
    report = view.reports.reports[0]
    assert report.severity is DiagnosticSeverity.WARNING
    assert "Export to Comfy Workflow" in report.message
    assert report.traceback == ()
    assert dialog.calls == 0


def test_save_as_cancel_keeps_document_dirty_without_feedback(tmp_path: Path) -> None:
    """Cancelling a valid chooser is not a failure or a successful save."""

    view = make_save_view(tmp_path)
    files = _files(tmp_path)
    state = view.unsaved_work_service.state_for("workflow")
    assert (
        view.workspace_file_actions.recipe_save_actions.on_save_as_clicked(
            file_dialog=SaveDialog("")
        )
        is False
    )
    assert _files(tmp_path) == files
    assert view.unsaved_work_service.state_for("workflow") == state
    assert view.reports.reports == []


def test_default_save_retains_service_owned_name_and_path_normalization(
    tmp_path: Path,
) -> None:
    """Whitespace in a display name must not change the canonical destination."""

    view = make_save_view(tmp_path)
    view.workflow_tabbar.itemMap["workflow"] = SaveTab("  Recipe  ")

    assert view.workspace_file_actions.recipe_save_actions.on_save_clicked() is True

    assert view.destination.read_text(encoding="utf-8").startswith(
        "# Project: Recipe\n"
    )
    state = view.unsaved_work_service.state_for("workflow")
    assert state.source_path == view.destination
    assert state.dirty is False
    assert view.workflow_tabbar.tabItem(0).text() == "  Recipe  "


@pytest.mark.parametrize(
    "malformed", (False, True), ids=("write-error", "missing-analysis")
)
def test_unexpected_save_failure_is_visible_and_not_format_refusal(
    tmp_path: Path, malformed: bool
) -> None:
    """Invalid state and actual filesystem errors retain diagnostic identity."""

    view = make_save_view(tmp_path)
    if malformed:
        direct = view.get_active_workflow().direct_workflow
        assert direct is not None
        direct.cube_analysis = None
    else:
        view.path_bundle.sugar_scripts_dir.mkdir()
        (view.path_bundle.sugar_scripts_dir / "Recipe").write_bytes(b"blocking parent")
    files = _files(tmp_path)
    state = view.unsaved_work_service.state_for("workflow")

    assert view.workspace_file_actions.recipe_save_actions.on_save_clicked() is False
    assert _files(tmp_path) == files
    assert view.unsaved_work_service.state_for("workflow") == state
    assert len(view.reports.reports) == 1
    report = view.reports.reports[0]
    assert report.severity is DiagnosticSeverity.ERROR
    assert report.exception_type is not None
    assert "Export to Comfy Workflow" not in report.message


class _ChooseSave:
    """Choose Save at a controlled destructive-action decision boundary."""

    def decide(self, *, parent: QWidget, workflow_name: str) -> UnsavedWorkDecision:
        """Return the user's save decision without opening a native dialog."""

        return UnsavedWorkDecision.SAVE


def test_unsupported_save_blocks_close_and_shutdown_with_document_intact(
    tmp_path: Path,
) -> None:
    """The real close coordinator must retain the workflow after a refused save."""

    view = make_save_view(tmp_path, mixed=True)
    controller = UnsavedWorkController(view, prompt=_ChooseSave())
    files = _files(tmp_path)
    workflow = view.get_active_workflow()

    assert controller.confirm_workflow_close("workflow") is False
    assert controller.confirm_shutdown() is False
    assert view.workflow_session_service.get_active_workflow() is workflow
    assert view.unsaved_work_service.state_for("workflow").dirty is True
    assert _files(tmp_path) == files
    assert len(view.reports.reports) == 2
