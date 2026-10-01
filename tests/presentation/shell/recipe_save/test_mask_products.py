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

"""Require explicit saves to include live mask preparation before acknowledgement."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from uuid import uuid4

import pytest

from substitute.domain.workflow import WorkflowState
from .support import SaveDialog, SaveView, make_save_view


class _RejectedPreparation:
    """Reject the external document capture boundary deterministically."""

    def prepare(
        self, *, workflow_id: str, workflow: WorkflowState, destination: Path
    ) -> AbstractContextManager[WorkflowState]:
        """Report that the requested live mask pixels could not be captured."""

        raise RuntimeError("Live mask capture failed")


class _MaskSaveView(SaveView):
    """Expose the explicit-save capture owner on the controlled shell boundary."""

    input_recipe_save_preparation = _RejectedPreparation()


@pytest.mark.parametrize("save_as", (False, True))
def test_mask_preparation_failure_preserves_previous_recipe_and_dirty_state(
    tmp_path: Path, save_as: bool
) -> None:
    """A failed live mask capture must never acknowledge a stale recipe as saved."""

    original = make_save_view(tmp_path)
    view = _MaskSaveView(tmp_path, original.get_active_workflow())
    image_id, mask_id = uuid4(), uuid4()
    workflow = view.get_active_workflow()
    workflow.canvas.bind_image("Cube:Image", image_id)
    workflow.canvas.bind_mask(("Cube", "Mask"), mask_id, image_id)
    destination = tmp_path / "selected.sugar" if save_as else view.destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"previous recipe")
    state = view.unsaved_work_service.state_for("workflow")
    actions = view.workspace_file_actions.recipe_save_actions

    result = (
        actions.on_save_as_clicked(file_dialog=SaveDialog(str(destination)))
        if save_as
        else actions.on_save_clicked()
    )

    assert result is False
    assert destination.read_bytes() == b"previous recipe"
    assert view.unsaved_work_service.state_for("workflow") == state
    assert not (destination.parent / "versions").exists()
    assert len(view.reports.reports) == 1
    assert "Your changes remain open" in view.reports.reports[0].message


def test_mask_save_as_cancellation_never_requests_live_capture(tmp_path: Path) -> None:
    """Cancelling the chooser must remain a no-op even when capture would fail."""

    original = make_save_view(tmp_path)
    view = _MaskSaveView(tmp_path, original.get_active_workflow())
    image_id = uuid4()
    view.get_active_workflow().canvas.bind_image("Cube:Image", image_id)
    view.get_active_workflow().canvas.bind_mask(("Cube", "Mask"), uuid4(), image_id)
    before = view.unsaved_work_service.state_for("workflow")

    assert not view.workspace_file_actions.recipe_save_actions.on_save_as_clicked(
        file_dialog=SaveDialog("")
    )
    assert view.unsaved_work_service.state_for("workflow") == before
    assert view.reports.reports == []
    assert not tuple(tmp_path.rglob("*.sugar"))
