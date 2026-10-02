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

"""Protect authored recipe destinations from unrelated workflow-named saves."""

from pathlib import Path

import pytest

from .support import SaveDialog, make_save_view


@pytest.mark.parametrize("saved_as", (False, True), ids=("loaded", "saved-as"))
def test_save_updates_current_recipe_without_touching_default_project(
    tmp_path: Path, saved_as: bool
) -> None:
    """Keep loaded and Save As documents bound to their explicit recipe path."""
    view = make_save_view(tmp_path)
    actions = view.workspace_file_actions.recipe_save_actions
    target = tmp_path / "external.sugar"
    target.write_text("previous external recipe", encoding="utf-8")
    default = view.destination
    default.parent.mkdir(parents=True)
    default.write_bytes(b"unrelated same-named project")
    if saved_as:
        assert actions.on_save_as_clicked(file_dialog=SaveDialog(str(target)))
    else:
        view.unsaved_work_service.mark_saved("workflow", target)
    view.get_active_workflow().global_overrides = {
        "cfg": {"value": 6.25, "mode": "global"}
    }
    view.unsaved_work_service.mark_dirty("workflow")

    assert actions.on_save_clicked()

    assert "6.25" in target.read_text(encoding="utf-8")
    assert default.read_bytes() == b"unrelated same-named project"
    state = view.unsaved_work_service.state_for("workflow")
    assert state.source_path == target
    assert not state.dirty


def test_cancelled_save_as_keeps_current_recipe_target(tmp_path: Path) -> None:
    """An abandoned destination chooser cannot redirect the next Save."""
    view = make_save_view(tmp_path)
    actions = view.workspace_file_actions.recipe_save_actions
    target = tmp_path / "chosen.sugar"
    view.unsaved_work_service.mark_saved("workflow", target)
    view.unsaved_work_service.mark_dirty("workflow")

    assert not actions.on_save_as_clicked(file_dialog=SaveDialog(""))
    assert actions.on_save_clicked()

    assert target.is_file()
    assert not view.destination.exists()
    assert view.unsaved_work_service.state_for("workflow").source_path == target


def test_failed_current_target_does_not_fall_back_to_default_project(
    tmp_path: Path,
) -> None:
    """Preserve dirty work if the selected recipe destination cannot be written."""
    view = make_save_view(tmp_path)
    actions = view.workspace_file_actions.recipe_save_actions
    blocked = tmp_path / "blocked"
    blocked.write_bytes(b"not a directory")
    target = blocked / "chosen.sugar"
    view.unsaved_work_service.mark_saved("workflow", target)
    view.unsaved_work_service.mark_dirty("workflow")

    assert not actions.on_save_clicked()

    assert not view.destination.exists()
    assert blocked.read_bytes() == b"not a directory"
    state = view.unsaved_work_service.state_for("workflow")
    assert state.source_path == target
    assert state.dirty
    assert len(view.reports.reports) == 1
