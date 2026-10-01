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

"""Verify imported graph sections reach the real Input admission owners."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from substitute.application.direct_workflows import DirectWorkflowLoadService
from substitute.application.workflows.editor_projection_service import (
    DIRECT_WORKFLOW_SECTION_KEY,
)
from substitute.application.workflows.workflow_graph_section_service import (
    WorkflowGraphSectionService,
)
from substitute.domain.comfy_workflow import CanonicalCubeGraphAnalysis
from substitute.domain.common import JsonObject
from substitute.domain.workflow import WorkflowState
from substitute.infrastructure.comfy.workflow_document_repository import (
    ComfyWorkflowDocumentRepository,
)
from substitute.presentation.shell.direct_workflow_file_actions import (
    DirectWorkflowFileActions,
)
from tests.support.canonical_cube_graph import graph_backed_cube_workflow

from .import_input_support import import_view, input_admission


@dataclass(frozen=True)
class _CubeAnalyzer:
    """Return one fixed SugarCubes response without mocking internal projection."""

    analysis: CanonicalCubeGraphAnalysis

    def analyze(self, workflow: JsonObject) -> CanonicalCubeGraphAnalysis:
        """Preserve canonical input data in the external analyzer response."""
        return replace(self.analysis, workflow=deepcopy(workflow))


def _source_graph(
    aliases: tuple[str, ...], image_path: Path
) -> tuple[JsonObject, _CubeAnalyzer]:
    """Build canonical Cube sections alongside a complete ordinary Comfy graph."""
    template = graph_backed_cube_workflow(*aliases)
    direct = template.direct_workflow
    assert direct is not None and direct.cube_analysis is not None
    for cube in template.cubes.values():
        cube.buffer["nodes"] = {
            "image": {"class_type": "LoadImage", "inputs": {"image": str(image_path)}},
            "preview": {
                "class_type": "PreviewImage",
                "inputs": {"images": ["image", 0]},
            },
        }
        cube.buffer["outputs"] = {"image": ["image", 0]}
    source = deepcopy(direct.source_workflow)
    nodes = source["nodes"]
    links = source["links"]
    assert isinstance(nodes, list) and isinstance(links, list)
    nodes.extend(
        [
            {
                "id": 101,
                "type": "LoadImage",
                "inputs": [
                    {
                        "name": "image",
                        "type": "IMAGEUPLOAD",
                        "widget": {"name": "image"},
                        "link": None,
                    }
                ],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [101]}],
                "widgets_values": [str(image_path)],
                "properties": {"preserved": "ordinary-node metadata"},
            },
            {
                "id": 102,
                "type": "PreviewImage",
                "inputs": [{"name": "images", "type": "IMAGE", "link": 101}],
                "outputs": [],
                "widgets_values": [],
            },
        ]
    )
    links.append([101, 101, 0, 102, 0, "IMAGE"])
    source["extra"] = {"preserved": {"unicode": "Café", "values": [1, True, None]}}
    return source, _CubeAnalyzer(direct.cube_analysis)


@pytest.mark.parametrize(
    "aliases",
    [(), ("Load Image",), ("Second", "First")],
    ids=["plain", "one-cube", "two-cubes"],
)
def test_import_materializes_every_projected_input_section(
    tmp_path: Path, aliases: tuple[str, ...]
) -> None:
    """Admit every section's image without losing canonical graph or source bytes."""
    image_path = tmp_path / "source.png"
    payload, analyzer = _source_graph(aliases, image_path)
    source = tmp_path / "imported.json"
    source_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    source.write_bytes(source_bytes)
    workflow = WorkflowState()
    admission = input_admission(tmp_path)
    graph_sections = WorkflowGraphSectionService()
    requests: list[tuple[str, str, bool]] = []
    refreshes: list[str] = []

    def materialize(workflow_id: str, section_key: str) -> None:
        """Route the import callback into the real section admission service."""
        requests.append(
            (
                workflow_id,
                section_key,
                graph_sections.graph(workflow, section_key) is not None,
            )
        )
        admission.sections.materialize_loaded_section(
            workflows={"imported": workflow},
            workflow_id=workflow_id,
            section_key=section_key,
            workflow_name="Imported",
            projects_dir=tmp_path,
        )

    actions = DirectWorkflowFileActions(
        view=import_view(workflow),
        load_service=DirectWorkflowLoadService(
            ComfyWorkflowDocumentRepository(), analyzer
        ),
        add_workflow_tab=lambda: pytest.fail("The blank tab must receive this import."),
        refresh_active_workflow=lambda: refreshes.append("refresh"),
        materialize_loaded_section=materialize,
    )

    assert actions.load_document(source) == "imported"

    expected_sections = aliases or (DIRECT_WORKFLOW_SECTION_KEY,)
    assert requests == [("imported", key, True) for key in expected_sections]
    assert graph_sections.section_keys(workflow) == expected_sections
    image_node = "image" if aliases else "101"
    assert set(workflow.canvas.image_entries) == {
        f"{key}:{image_node}" for key in expected_sections
    }
    assert len(admission.document.images) == len(expected_sections)
    assert {path for _, path in admission.document.images.values()} == {image_path}
    assert admission.document.current_id == workflow.canvas.input_image_uuid
    assert refreshes == ["refresh"]
    assert workflow.direct_workflow is not None
    assert workflow.direct_workflow.source_workflow == payload
    assert source.read_bytes() == source_bytes


def test_import_reports_section_materialization_failure(tmp_path: Path) -> None:
    """Keep import failure handling and canonical data intact for a failed section."""
    payload, analyzer = _source_graph(("First", "Second"), tmp_path / "source.png")
    source = tmp_path / "imported.json"
    source_bytes = json.dumps(payload).encode("utf-8")
    source.write_bytes(source_bytes)
    workflow = WorkflowState()
    requests: list[str] = []

    def fail_materialization(workflow_id: str, section_key: str) -> None:
        """Model an unavailable Input document at the shell presentation boundary."""
        assert workflow_id == "imported"
        requests.append(section_key)
        raise RuntimeError("Input document unavailable")

    actions = DirectWorkflowFileActions(
        view=import_view(workflow),
        load_service=DirectWorkflowLoadService(
            ComfyWorkflowDocumentRepository(), analyzer
        ),
        add_workflow_tab=lambda: pytest.fail("The blank tab must receive this import."),
        refresh_active_workflow=lambda: None,
        materialize_loaded_section=fail_materialization,
    )

    assert actions.load_document(source) is None
    assert requests == ["First"]
    assert workflow.direct_workflow is not None
    assert workflow.direct_workflow.source_workflow == payload
    assert source.read_bytes() == source_bytes
