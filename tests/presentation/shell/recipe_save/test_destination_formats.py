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

"""Keep explicit recipe identity separate from import formats and display names."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QWidget

from substitute.application.workflows.unsaved_work_service import UnsavedWorkDecision
from substitute.presentation.shell.unsaved_work_controller import UnsavedWorkController

from .support import SaveDialog, SaveTab, make_save_view


@pytest.mark.parametrize("suffix", (".json", ".png"))
def test_save_preserves_non_recipe_source_bytes(tmp_path: Path, suffix: str) -> None:
    """A loaded import baseline must never become a Sugar Script write target."""

    view = make_save_view(tmp_path)
    source = tmp_path / f"imported{suffix}"
    original = b"imported document bytes must remain unchanged"
    source.write_bytes(original)
    view.unsaved_work_service.mark_saved("workflow", source)
    view.unsaved_work_service.mark_dirty("workflow")

    assert view.workspace_file_actions.recipe_save_actions.on_save_clicked()

    assert source.read_bytes() == original
    assert 'use "test/Cube.cube"@1.0.0 as Cube' in view.destination.read_text(
        encoding="utf-8"
    )
    state = view.unsaved_work_service.state_for("workflow")
    assert state.source_path == view.destination
    assert not state.dirty


def test_save_reuses_case_insensitive_recipe_suffix(tmp_path: Path) -> None:
    """Retain a valid uppercase recipe extension on every supported platform."""

    view = make_save_view(tmp_path)
    target = tmp_path / "selected.SUGAR"
    target.write_bytes(b"previous selected recipe")
    view.unsaved_work_service.mark_saved("workflow", target)
    view.unsaved_work_service.mark_dirty("workflow")

    assert view.workspace_file_actions.recipe_save_actions.on_save_clicked()

    assert 'use "test/Cube.cube"@1.0.0 as Cube' in target.read_text(encoding="utf-8")
    assert not view.destination.exists()
    state = view.unsaved_work_service.state_for("workflow")
    assert state.source_path == target
    assert not state.dirty


@pytest.mark.parametrize("invalid_format", (False, True), ids=("write-error", "format"))
def test_failed_save_as_retains_previous_recipe_identity(
    tmp_path: Path, invalid_format: bool
) -> None:
    """A failed chooser destination cannot redirect or acknowledge later saves."""

    view = make_save_view(tmp_path)
    actions = view.workspace_file_actions.recipe_save_actions
    current = tmp_path / "current.sugar"
    current.write_bytes(b"previous current recipe")
    view.unsaved_work_service.mark_saved("workflow", current)
    view.unsaved_work_service.mark_dirty("workflow")
    previous_state = view.unsaved_work_service.state_for("workflow")
    if invalid_format:
        selected = tmp_path / "export.json"
        selected.write_bytes(b"existing JSON export")
    else:
        blocked = tmp_path / "blocked"
        blocked.write_bytes(b"not a directory")
        selected = blocked / "unwritable.sugar"

    assert not actions.on_save_as_clicked(file_dialog=SaveDialog(str(selected)))

    assert view.unsaved_work_service.state_for("workflow") == previous_state
    assert current.read_bytes() == b"previous current recipe"
    assert not view.destination.exists()
    assert len(view.reports.reports) == 1
    if invalid_format:
        assert selected.read_bytes() == b"existing JSON export"
    else:
        assert selected.parent.read_bytes() == b"not a directory"

    assert actions.on_save_clicked()

    assert 'use "test/Cube.cube"@1.0.0 as Cube' in current.read_text(encoding="utf-8")
    assert not view.destination.exists()
    state = view.unsaved_work_service.state_for("workflow")
    assert state.source_path == current
    assert not state.dirty


@pytest.mark.parametrize("display_name", ("Category/Recipe", "Recipe: variant", r"A\B"))
def test_save_explicit_target_does_not_treat_display_name_as_path(
    tmp_path: Path, display_name: str
) -> None:
    """An existing destination remains writable with a non-path display label."""

    view = make_save_view(tmp_path)
    target = tmp_path / "selected.sugar"
    view.unsaved_work_service.mark_saved("workflow", target)
    view.unsaved_work_service.mark_dirty("workflow")
    view.workflow_tabbar.itemMap["workflow"] = SaveTab(display_name)

    assert view.workspace_file_actions.recipe_save_actions.on_save_clicked()

    assert target.read_text(encoding="utf-8").startswith(f"# Project: {display_name}\n")
    assert not view.path_bundle.sugar_scripts_dir.exists()
    assert view.workflow_tabbar.tabItem(0).text() == display_name
    state = view.unsaved_work_service.state_for("workflow")
    assert state.source_path == target
    assert not state.dirty
    assert view.reports.reports == []


def test_save_as_can_replace_an_unusable_current_target(tmp_path: Path) -> None:
    """A broken old destination cannot prevent choosing a valid rescue location."""

    view = make_save_view(tmp_path)
    blocked = tmp_path / "blocked"
    blocked.write_bytes(b"not a directory")
    view.unsaved_work_service.mark_saved("workflow", blocked / "current.sugar")
    view.unsaved_work_service.mark_dirty("workflow")
    selected = tmp_path / "rescued.sugar"
    dialog = SaveDialog(str(selected))

    assert view.workspace_file_actions.recipe_save_actions.on_save_as_clicked(
        file_dialog=dialog
    )

    assert dialog.calls == 1
    assert 'use "test/Cube.cube"@1.0.0 as Cube' in selected.read_text(encoding="utf-8")
    assert blocked.read_bytes() == b"not a directory"
    assert not view.destination.exists()
    state = view.unsaved_work_service.state_for("workflow")
    assert state.source_path == selected
    assert not state.dirty
    assert view.reports.reports == []


def test_save_as_chooser_starts_at_retained_recipe_path(tmp_path: Path) -> None:
    """Suggest the current external recipe instead of an unrelated default path."""

    view = make_save_view(tmp_path)
    target = tmp_path / "external.sugar"
    target.write_bytes(b"current external recipe")
    view.unsaved_work_service.mark_saved("workflow", target)
    view.unsaved_work_service.mark_dirty("workflow")
    previous_state = view.unsaved_work_service.state_for("workflow")
    dialog = SaveDialog("")

    assert not view.workspace_file_actions.recipe_save_actions.on_save_as_clicked(
        file_dialog=dialog
    )

    assert dialog.calls == 1
    assert dialog.requested_directory == str(target)
    assert target.read_bytes() == b"current external recipe"
    assert not view.destination.exists()
    assert view.unsaved_work_service.state_for("workflow") == previous_state


class _SaveAtShutdown:
    """Choose Save at the external shutdown decision boundary."""

    def decide(self, *, parent: QWidget, workflow_name: str) -> UnsavedWorkDecision:
        """Permit shutdown only after the real document save succeeds."""

        return UnsavedWorkDecision.SAVE


def test_shutdown_save_updates_retained_external_recipe(tmp_path: Path) -> None:
    """Shutdown acknowledges the chosen file without changing another project."""

    view = make_save_view(tmp_path)
    target = tmp_path / "external.sugar"
    target.write_bytes(b"previous external recipe")
    default = view.destination
    default.parent.mkdir(parents=True)
    default.write_bytes(b"unrelated same-named project")
    view.unsaved_work_service.mark_saved("workflow", target)
    view.get_active_workflow().global_overrides = {
        "cfg": {"value": 6.75, "mode": "global"}
    }
    view.unsaved_work_service.mark_dirty("workflow")
    controller = UnsavedWorkController(view, prompt=_SaveAtShutdown())

    assert controller.confirm_shutdown()

    assert "6.75" in target.read_text(encoding="utf-8")
    assert default.read_bytes() == b"unrelated same-named project"
    state = view.unsaved_work_service.state_for("workflow")
    assert state.source_path == target
    assert not state.dirty
    assert view.reports.reports == []
