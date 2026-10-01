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

"""Verify authored prompt history reaches explicit-save tracking in the real shell."""

from __future__ import annotations

from pathlib import Path

from tests.support.prompt_editor.real_shell.scenario import (
    PromptEditorRealShellScenario,
)


def test_prompt_edit_undo_redo_each_dirty_the_owning_document(
    real_shell_scenario: PromptEditorRealShellScenario,
    tmp_path: Path,
) -> None:
    """Use production panel composition and custom prompt history notification."""
    field = real_shell_scenario.workflows.add_prompt_workflow(initial_text="")
    service = real_shell_scenario.shell.unsaved_work_service
    workflow_id = field.workflow.workflow_id
    source = tmp_path / "prompt.sugar"
    service.mark_saved(workflow_id, source)
    assert not service.state_for(workflow_id).dirty

    real_shell_scenario.input.type_text(field, "alpha")
    assert field.editor.toPlainText() == "alpha"
    assert service.state_for(workflow_id).dirty
    assert service.state_for(workflow_id).source_path == source

    service.mark_saved(workflow_id, source)
    real_shell_scenario.input.undo(field)
    assert field.editor.toPlainText() == ""
    assert service.state_for(workflow_id).dirty

    service.mark_saved(workflow_id, source)
    real_shell_scenario.input.redo(field)
    assert field.editor.toPlainText() == "alpha"
    assert service.state_for(workflow_id).dirty
