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

"""Restore explicit saved scalar-mask provenance without altering recipe authoring."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from substitute.application.recipes.recipe_mask_reference_restoration import (
    RecipeMaskReferenceRestoration,
)
from substitute.application.workflows.workflow_asset_service import WorkflowAssetService
from substitute.application.workflows.workflow_graph_section_service import (
    WorkflowGraphSectionService,
)
from substitute.domain.workflow import LocalFileAssetRef
from tests.application.workflows.input_canvas.support import (
    _build_workflow,
    _input_canvas_binding_service,
)
from tests.support.canonical_cube_graph import graph_backed_cube_workflow_from_states


def test_loaded_absolute_mask_registration_preserves_exact_authored_graph(
    tmp_path: Path,
) -> None:
    """Metadata registration must not normalize raw path spelling, prompts, or history."""

    raw = str(tmp_path / "folder") + "/../folder/painted mask.png"
    legacy = _build_workflow(raw)
    workflow = graph_backed_cube_workflow_from_states(legacy.cubes["CubeA"])
    direct = workflow.direct_workflow
    assert direct is not None
    graph_before = json.dumps(direct.source_workflow, sort_keys=True)
    buffer_before = deepcopy(workflow.cubes["CubeA"].buffer)
    history_before = deepcopy(
        (workflow.cubes["CubeA"].undo_stack, workflow.cubes["CubeA"].redo_stack)
    )
    assets = WorkflowAssetService()
    RecipeMaskReferenceRestoration(
        bindings=_input_canvas_binding_service(),
        graphs=WorkflowGraphSectionService(),
        assets=assets,
    ).restore(workflow)
    assert json.dumps(direct.source_workflow, sort_keys=True) == graph_before
    assert workflow.cubes["CubeA"].buffer == buffer_before
    assert (
        workflow.cubes["CubeA"].undo_stack,
        workflow.cubes["CubeA"].redo_stack,
    ) == history_before
    assert direct.dirty is False
    assert assets.input_mask_asset_ref(
        workflow, section_key="CubeA", node_name="input_mask", field_key="image"
    ) == LocalFileAssetRef(raw)


@pytest.mark.parametrize("raw", ("", "old-relative.png", "nested/old-relative.png"))
def test_recipe_restoration_does_not_guess_relative_asset_roots(raw: str) -> None:
    """Legacy relative fields retain existing ownership until explicit materialization."""

    legacy = _build_workflow(raw)
    workflow = graph_backed_cube_workflow_from_states(legacy.cubes["CubeA"])
    before = deepcopy(workflow)
    RecipeMaskReferenceRestoration(
        bindings=_input_canvas_binding_service(),
        graphs=WorkflowGraphSectionService(),
        assets=WorkflowAssetService(),
    ).restore(workflow)
    assert workflow == before
