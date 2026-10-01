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

"""Preserve authored upload references across editor hydration and execution."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

import pytest

from substitute.application.direct_workflows import DirectWorkflowLoadService
from substitute.application.direct_workflows.execution_projection import (
    DirectWorkflowExecutionProjector,
)
from substitute.application.direct_workflows.generation_plan_service import (
    DirectWorkflowGenerationPlanService,
)
from substitute.application.node_behavior import NodeBehaviorService
from substitute.domain.common import JsonObject
from tests.support.passthrough_cube_analysis import PassthroughCubeWorkflowAnalyzer

_SELECTED = "newly-uploaded.mp4"
_OLD = "previous-upload.mp4"


class _Repository:
    """Return detached user-authored workflow bytes as decoded JSON."""

    def __init__(self, workflow: JsonObject) -> None:
        """Keep the source document separate from every loaded projection."""
        self.workflow = deepcopy(workflow)

    def can_load(self, _path: Path) -> bool:
        """Expose the owned in-memory workflow."""
        return True

    def load(self, _path: Path) -> JsonObject:
        """Return an independent decoded document."""
        return deepcopy(self.workflow)


class _Definitions:
    """Expose a stale backend listing without validating local file existence."""

    def __init__(self, upload_key: str, options: list[str] | None) -> None:
        """Build native COMBO metadata with a distinct older listing default."""
        metadata: dict[str, object] = {upload_key: True, "default": _OLD}
        if options is not None:
            metadata["options"] = options
        self.definitions: dict[str, dict[str, object]] = {
            "CustomMediaLoader": {
                "input": {"required": {"resource": ["COMBO", metadata]}},
                "output": ["VIDEO"],
            },
            "SaveVideo": {
                "input": {"required": {"video": ["VIDEO", {}]}},
                "output_node": True,
            },
        }

    def get_node_definition(self, class_type: str) -> dict[str, object]:
        """Return the same immutable-by-contract cached definition."""
        return {class_type: self.definitions[class_type]}

    def get_required_node_definition(self, class_type: str) -> dict[str, object]:
        """Expose the same metadata for mandatory lookup."""
        return self.get_node_definition(class_type)


def _workflow() -> JsonObject:
    """Build a native workflow whose source selects a newly uploaded file."""
    return {
        "nodes": [
            {
                "id": 1,
                "type": "CustomMediaLoader",
                "inputs": [],
                "outputs": [{"name": "VIDEO", "type": "VIDEO", "links": [1]}],
                "widgets_values": [_SELECTED],
            },
            {
                "id": 2,
                "type": "SaveVideo",
                "inputs": [{"name": "video", "type": "VIDEO", "link": 1}],
                "outputs": [],
                "widgets_values": [],
            },
        ],
        "links": [[1, 1, 0, 2, 0, "VIDEO"]],
    }


def _input_value(graph: Mapping[str, object]) -> object:
    """Read the concrete reference sent to the backend from a lowered graph."""
    node = graph["1"]
    assert isinstance(node, Mapping)
    inputs = node["inputs"]
    assert isinstance(inputs, Mapping)
    return inputs["resource"]


@pytest.mark.parametrize(
    "upload_key", ["image_upload", "audio_upload", "video_upload", "file_upload"]
)
@pytest.mark.parametrize(
    "options", [[_OLD], [], None], ids=["stale", "empty", "unavailable"]
)
def test_upload_reference_survives_editor_hydration_and_generation(
    tmp_path: Path, upload_key: str, options: list[str] | None
) -> None:
    """A listing cannot replace a source filename or grant file transport rights."""
    source = _workflow()
    repository = _Repository(source)
    gateway = _Definitions(upload_key, options)
    backend_metadata = deepcopy(gateway.definitions)
    document = DirectWorkflowLoadService(
        repository, PassthroughCubeWorkflowAnalyzer(), node_definition_gateway=gateway
    ).load(tmp_path / "uploaded-video.json")
    local_metadata = deepcopy(document.buffer)
    behavior = NodeBehaviorService(node_definition_gateway=gateway)

    for _refresh in range(2):
        snapshot = behavior.build_snapshot(
            cube_states={"Workflow": document}, stack_order=["Workflow"]
        )
        spec = snapshot.field_specs_by_alias["Workflow"]["1"]["resource"]
        assert spec.value == _SELECTED
        nodes = document.buffer["nodes"]
        assert isinstance(nodes, Mapping)
        assert _input_value(nodes) == _SELECTED
        assert document.source_workflow == source
        assert document.dirty is False

    plan = DirectWorkflowGenerationPlanService(node_definition_gateway=gateway).build(
        document
    )
    projection = DirectWorkflowExecutionProjector().project(plan)
    assert _input_value(plan.authored_api_graph) == _SELECTED
    assert _input_value(projection.prompt) == _SELECTED
    assert projection.execution_targets == ("2",)
    assert document.source_workflow == repository.workflow == source
    assert gateway.definitions == backend_metadata
    # Hydration may add owner state but cannot rewrite the graph-local schema.
    before_nodes = local_metadata["nodes"]
    after_nodes = document.buffer["nodes"]
    assert isinstance(before_nodes, Mapping) and isinstance(after_nodes, Mapping)
    before_loader = before_nodes["1"]
    after_loader = after_nodes["1"]
    assert isinstance(before_loader, Mapping) and isinstance(after_loader, Mapping)
    assert before_loader["_workflow"] == after_loader["_workflow"]
