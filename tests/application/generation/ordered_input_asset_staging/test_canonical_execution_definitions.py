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

"""Verify live execution definitions accompany staged canonical Cube assets."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest
from sugarsubstitute_shared.presentation.localization import render_application_text

from substitute.application.generation import (
    GenerationService,
    PreparedGenerationRequest,
)
from substitute.application.ports.comfy_gateway import ComfyGateway
from substitute.application.recipes.recipe_io_service import RecipeIoService
from substitute.infrastructure.persistence.file_recipe_repository import (
    FileRecipeRepository,
)
from tests.application.generation.generation_service.support import (
    _FakeGateway,
    _CallbackRecorder,
    _build_generation_callbacks,
)

from substitute.application.node_behavior.live_definition_authority import (
    LiveNodeDefinitionAuthority,
)

from substitute.application.generation.asset_staging_service import (
    ComfyAssetStagingService,
)
from substitute.domain.common import JsonObject
from substitute.domain.generation import ComfyStagedAsset
from substitute.domain.workflow import CubeState, WorkflowState
from tests.support.canonical_cube_graph import graph_backed_cube_workflow_from_states


class _AuthorizedStager:
    """Replace local paths at the external staging boundary with inert values."""

    def stage_file_for_load_image(
        self,
        *,
        source_path: Path,
        target_subfolder: str,
        content_hash: str,
        node_class: str,
    ) -> ComfyStagedAsset:
        """Supply the backend-selected execution class without real authorization."""
        return ComfyStagedAsset(
            source_path=source_path,
            execution_value=f"inert:{source_path.name}",
            operation="authorized",
            execution_node_class=f"SubstituteBackend{node_class}",
        )


def _workflow(tmp_path: Path) -> WorkflowState:
    """Build two canonical sections retaining independent images, masks and presets."""
    cubes: list[CubeState] = []
    for alias in ("First", "Second"):
        image = tmp_path / f"{alias}-image.png"
        mask = tmp_path / f"{alias}-mask.png"
        image.write_bytes(b"image")
        mask.write_bytes(b"mask")
        nodes: JsonObject = {
            "image": {"class_type": "LoadImage", "inputs": {"image": str(image)}},
            "mask": {
                "class_type": "LoadImageMask",
                "inputs": {"image": str(mask), "channel": "green"},
            },
        }
        buffer: JsonObject = {
            "nodes": nodes,
            "inputs": {},
            "outputs": {},
            "layout": {},
            "definitions": {"Unrelated": {"preserved": True}},
            "subgraphs": [],
            "surface": {"default_flavor_id": "default", "controls": []},
            "flavors": {
                "authored": [
                    {
                        "id": "default",
                        "name": "Default",
                        "values": {
                            "image.image": str(image),
                            "mask.image": str(mask),
                            "mask.channel": "green",
                        },
                    }
                ]
            },
        }
        cubes.append(
            CubeState(
                cube_id=f"test/{alias}.cube",
                version="1.0.0",
                alias=alias,
                original_cube=deepcopy(buffer),
                buffer=buffer,
            )
        )
    return graph_backed_cube_workflow_from_states(*cubes)


def _documents(payload: JsonObject) -> tuple[JsonObject, ...]:
    """Expose embedded documents for assertions without reproducing staging rules."""
    definitions = cast(JsonObject, payload["definitions"])
    subgraphs = cast(list[JsonObject], definitions["subgraphs"])
    return tuple(
        cast(JsonObject, cast(JsonObject, subgraph["extra"])["sugarcubes_document"])
        for subgraph in subgraphs
    )


def test_canonical_class_replacement_requires_live_definition_authority(
    tmp_path: Path,
) -> None:
    """Fail staging before queue when replacement-class metadata cannot be obtained."""
    workflow = _workflow(tmp_path)
    assert workflow.direct_workflow is not None
    payload = workflow.direct_workflow.source_workflow
    original = deepcopy(payload)

    result = ComfyAssetStagingService(stager=_AuthorizedStager()).stage_payload(
        workflow_payload=payload,
        workflow_id="imported",
        workflow_name="Imported",
        workflow=workflow,
    )

    assert result.failures
    assert str(result.failures[0].message) == "Generation preflight failed"
    assert payload == original


class _DefinitionGateway:
    """Return per-class live schemas from the external Comfy metadata boundary."""

    def __init__(self, definitions: dict[str, JsonObject]) -> None:
        """Keep the source payload mutable to prove defensive snapshot transport."""
        self.definitions = definitions
        self.required_calls: list[str] = []

    def get_node_definition(self, node_class: str) -> JsonObject:
        """Reject cached reads for correctness-sensitive execution metadata."""
        raise AssertionError("Execution schemas must use the required live lookup.")

    def get_required_node_definition(self, node_class: str) -> JsonObject:
        """Return the backend's class-keyed object_info payload."""
        self.required_calls.append(node_class)
        definition = self.definitions.get(node_class)
        return {} if definition is None else {node_class: definition}


def _definitions() -> dict[str, JsonObject]:
    """Declare distinct backend execution signatures at the external boundary."""
    return {
        "SubstituteBackendLoadImage": {
            "name": "SubstituteBackendLoadImage",
            "input": {"required": {"image": ["STRING", {"default": ""}]}},
            "output": ["IMAGE", "MASK"],
            "backend_metadata": {"origin": "live"},
        },
        "SubstituteBackendLoadImageMask": {
            "name": "SubstituteBackendLoadImageMask",
            "input": {
                "required": {
                    "image": ["STRING", {"default": ""}],
                    "channel": [["alpha", "red", "green", "blue"]],
                }
            },
            "output": ["MASK"],
        },
    }


def test_canonical_staging_transports_truthful_execution_schemas(
    tmp_path: Path,
) -> None:
    """Keep each changed node and schema coherent without changing authored data."""
    workflow = _workflow(tmp_path)
    assert workflow.direct_workflow is not None
    payload = workflow.direct_workflow.source_workflow
    original = deepcopy(payload)
    live_definitions = _definitions()
    gateway = _DefinitionGateway(live_definitions)
    service = ComfyAssetStagingService.with_projects_dir(
        stager=_AuthorizedStager(),
        projects_dir=tmp_path,
        live_node_definitions=LiveNodeDefinitionAuthority(gateway),
    )

    result = service.stage_payload(
        workflow_payload=payload,
        workflow_id="imported",
        workflow_name="Imported",
        workflow=workflow,
    )

    assert result.failures == ()
    assert len(result.staged_assets) == 4
    assert gateway.required_calls == [
        "SubstituteBackendLoadImage",
        "SubstituteBackendLoadImageMask",
    ]
    assert payload == original
    for alias, document, original_document in zip(
        ("First", "Second"),
        _documents(result.workflow_payload),
        _documents(original),
        strict=True,
    ):
        implementation = cast(JsonObject, document["implementation"])
        definitions = cast(JsonObject, implementation["definitions"])
        assert definitions == {"Unrelated": {"preserved": True}, **live_definitions}
        nodes = cast(JsonObject, implementation["nodes"])
        assert nodes["image"] == {
            "class_type": "SubstituteBackendLoadImage",
            "inputs": {"image": f"inert:{alias}-image.png"},
        }
        assert nodes["mask"] == {
            "class_type": "SubstituteBackendLoadImageMask",
            "inputs": {"image": f"inert:{alias}-mask.png", "channel": "green"},
        }
        assert document["flavors"] == original_document["flavors"]
    live_definitions["SubstituteBackendLoadImage"]["output"] = []
    first_implementation = cast(
        JsonObject, _documents(result.workflow_payload)[0]["implementation"]
    )
    transported = cast(JsonObject, first_implementation["definitions"])
    assert cast(JsonObject, transported["SubstituteBackendLoadImage"])["output"] == [
        "IMAGE",
        "MASK",
    ]


@pytest.mark.parametrize(
    ("invalid_definition", "reason"),
    [
        (None, "live_definition_unavailable"),
        (
            {"name": "Unrelated", "input": {}, "output": []},
            "live_definition_class_mismatch",
        ),
        (
            {"name": "SubstituteBackendLoadImage", "input": [], "output": ["IMAGE"]},
            "malformed_live_definition",
        ),
        (
            {
                "name": "SubstituteBackendLoadImage",
                "input": {"required": {}},
                "output": ["IMAGE"],
            },
            "missing_or_malformed_input:image",
        ),
        (
            {
                "name": "SubstituteBackendLoadImage",
                "input": {"required": {"image": "STRING"}},
                "output": ["IMAGE"],
            },
            "missing_or_malformed_input:image",
        ),
    ],
    ids=["unavailable", "mismatched", "malformed", "missing-field", "malformed-field"],
)
def test_canonical_staging_rejects_invalid_live_definition(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    invalid_definition: JsonObject | None,
    reason: str,
) -> None:
    """Fail with a credential-free diagnostic instead of trusting embedded schemas."""
    workflow = _workflow(tmp_path)
    assert workflow.direct_workflow is not None
    payload = workflow.direct_workflow.source_workflow
    # A supplied execution-class schema cannot substitute for current backend authority.
    for document in _documents(payload):
        implementation = cast(JsonObject, document["implementation"])
        cast(JsonObject, implementation["definitions"])[
            "SubstituteBackendLoadImage"
        ] = _definitions()["SubstituteBackendLoadImage"]
    original = deepcopy(payload)
    live_definitions = _definitions()
    if invalid_definition is None:
        live_definitions.pop("SubstituteBackendLoadImage")
    else:
        live_definitions["SubstituteBackendLoadImage"] = invalid_definition
    result = ComfyAssetStagingService(
        stager=_AuthorizedStager(),
        live_node_definitions=LiveNodeDefinitionAuthority(
            _DefinitionGateway(live_definitions)
        ),
    ).stage_payload(
        workflow_payload=payload,
        workflow_id="imported",
        workflow_name="Imported",
        workflow=workflow,
    )

    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.node_id == "First:image"
    assert failure.node_class == "SubstituteBackendLoadImage"
    assert failure.input_name == "inputs"
    assert failure.source_value == ""
    assert str(failure.message) == "Generation preflight failed"
    assert reason in caplog.text
    assert payload == original


def test_canonical_mask_staging_requires_its_live_channel_metadata(
    tmp_path: Path,
) -> None:
    """Reject incomplete mask schemas before committing any replacement class."""
    workflow = _workflow(tmp_path)
    assert workflow.direct_workflow is not None
    live_definitions = _definitions()
    mask_definition = live_definitions["SubstituteBackendLoadImageMask"]
    cast(JsonObject, cast(JsonObject, mask_definition["input"])["required"]).pop(
        "channel"
    )

    result = ComfyAssetStagingService(
        stager=_AuthorizedStager(),
        live_node_definitions=LiveNodeDefinitionAuthority(
            _DefinitionGateway(live_definitions)
        ),
    ).stage_payload(
        workflow_payload=workflow.direct_workflow.source_workflow,
        workflow_id="imported",
        workflow_name="Imported",
        workflow=workflow,
    )

    assert len(result.failures) == 1
    assert result.failures[0].node_id == "First:mask"
    for document in _documents(result.workflow_payload):
        nodes = cast(JsonObject, cast(JsonObject, document["implementation"])["nodes"])
        assert cast(JsonObject, nodes["image"])["class_type"] == "LoadImage"
        assert cast(JsonObject, nodes["mask"])["class_type"] == "LoadImageMask"


class _RemoteStager:
    """Return uploaded input names without replacing the backend node classes."""

    def stage_file_for_load_image(
        self,
        *,
        source_path: Path,
        target_subfolder: str,
        content_hash: str,
        node_class: str,
    ) -> ComfyStagedAsset:
        """Model remote upload without authorizing local execution nodes."""
        return ComfyStagedAsset(
            source_path=source_path,
            execution_value=f"uploads/{source_path.name}",
            operation="uploaded",
        )


def test_remote_canonical_staging_preserves_definition_and_flavor_metadata(
    tmp_path: Path,
) -> None:
    """Leave unchanged classes on the normal remote path without schema lookup."""
    workflow = _workflow(tmp_path)
    assert workflow.direct_workflow is not None
    payload = workflow.direct_workflow.source_workflow
    original = deepcopy(payload)
    gateway = _DefinitionGateway({})
    result = ComfyAssetStagingService(
        stager=_RemoteStager(),
        live_node_definitions=LiveNodeDefinitionAuthority(gateway),
    ).stage_payload(
        workflow_payload=payload,
        workflow_id="imported",
        workflow_name="Imported",
        workflow=workflow,
    )

    assert result.failures == ()
    assert gateway.required_calls == []
    assert payload == original
    for alias, document, original_document in zip(
        ("First", "Second"),
        _documents(result.workflow_payload),
        _documents(original),
        strict=True,
    ):
        implementation = cast(JsonObject, document["implementation"])
        assert implementation["definitions"] == {"Unrelated": {"preserved": True}}
        nodes = cast(JsonObject, implementation["nodes"])
        assert nodes["image"] == {
            "class_type": "LoadImage",
            "inputs": {"image": f"uploads/{alias}-image.png"},
        }
        assert nodes["mask"] == {
            "class_type": "LoadImageMask",
            "inputs": {"image": f"uploads/{alias}-mask.png", "channel": "green"},
        }
        assert document["flavors"] == original_document["flavors"]


def test_missing_execution_metadata_stops_generation_before_queue(
    tmp_path: Path,
) -> None:
    """Carry the real staging failure through generation without reaching transport."""
    workflow = _workflow(tmp_path)
    assert workflow.direct_workflow is not None
    gateway = _FakeGateway(queue_results=[])
    recorder = _CallbackRecorder([], [], [], [], [], [])
    service = GenerationService(
        recipe_io_service=RecipeIoService(FileRecipeRepository()),
        comfy_gateway=cast(ComfyGateway, gateway),
        asset_staging_service=ComfyAssetStagingService(
            stager=_AuthorizedStager(),
            live_node_definitions=LiveNodeDefinitionAuthority(_DefinitionGateway({})),
        ),
        output_dir=tmp_path,
    )

    result = service.run_prepared_generation(
        request=PreparedGenerationRequest(
            workflow_id="imported",
            workflow_name="Imported",
            cube_workflow=workflow.direct_workflow.source_workflow,
        ),
        callbacks=_build_generation_callbacks(recorder),
    )

    assert result.started is False
    assert result.failure is not None
    assert result.failure.stage == "stage"
    assert "Generation preflight failed" in render_application_text(
        result.failure.message
    )
    assert gateway.queue_calls == []
    assert gateway.connect_calls == []
    assert recorder.failures == [result.failure]
