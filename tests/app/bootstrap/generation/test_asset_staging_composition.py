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

"""Verify bootstrap composition of Comfy asset staging."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import cast

import pytest
import subprocess
import sys
import textwrap
from pathlib import Path

from substitute.app.bootstrap.asset_staging_composition import (
    build_comfy_asset_staging_service,
)
from substitute.domain.common import JsonObject
from substitute.domain.generation import ComfyStagedAsset
from tests.support.canonical_cube_graph import graph_backed_cube_workflow
from substitute.domain.onboarding import (
    ComfyEndpoint,
    ComfyTargetConfiguration,
    ComfyTargetMode,
    InstallationConfiguration,
    InstallationContext,
    RuntimeConfiguration,
)
from substitute.infrastructure.comfy import (
    LocalComfyAssetStager,
    RemoteUploadComfyAssetStager,
)


class _DefinitionGateway:
    """Reject metadata lookups during lazy staging composition."""

    def get_node_definition(self, node_class: str) -> JsonObject:
        """Keep cached network reads outside service construction."""
        raise AssertionError("Unexpected cached definition lookup")

    def get_required_node_definition(self, node_class: str) -> JsonObject:
        """Keep required network reads outside service construction."""
        raise AssertionError("Unexpected required definition lookup")


def _context(mode: ComfyTargetMode) -> InstallationContext:
    """Build a minimal installation context carrying target configuration."""

    installation = InstallationConfiguration.create_default(Path("E:/substitute"))
    return InstallationContext(
        installation=installation,
        runtime=RuntimeConfiguration.create_default(installation),
        comfy_target=ComfyTargetConfiguration(
            mode=mode,
            endpoint=ComfyEndpoint(host="127.0.0.1", port=8188),
            workspace_path=None,
            install_owned=mode is ComfyTargetMode.MANAGED_LOCAL,
            launch_owned=mode is ComfyTargetMode.MANAGED_LOCAL,
        ),
    )


def test_managed_local_composition_uses_local_asset_stager() -> None:
    """Managed local targets should use backend-authorized local staging."""

    service = build_comfy_asset_staging_service(
        _context(ComfyTargetMode.MANAGED_LOCAL),
        node_definition_gateway=_DefinitionGateway(),
    )

    assert isinstance(service.stager, LocalComfyAssetStager)
    assert (
        service.stager.endpoint
        == _context(ComfyTargetMode.MANAGED_LOCAL).comfy_target.endpoint
    )


def test_attached_local_composition_uses_local_asset_stager() -> None:
    """Attached local targets should use backend-authorized local staging."""

    service = build_comfy_asset_staging_service(
        _context(ComfyTargetMode.ATTACHED_LOCAL),
        node_definition_gateway=_DefinitionGateway(),
    )

    assert isinstance(service.stager, LocalComfyAssetStager)


def test_remote_composition_uses_remote_upload_asset_stager() -> None:
    """Remote targets should upload source files through Comfy."""

    service = build_comfy_asset_staging_service(
        _context(ComfyTargetMode.REMOTE), node_definition_gateway=_DefinitionGateway()
    )

    assert isinstance(service.stager, RemoteUploadComfyAssetStager)


def test_managed_local_composition_does_not_import_requests() -> None:
    """Managed-local staging composition should not pay remote HTTP imports."""

    code = textwrap.dedent(
        """
        import json
        import sys
        from pathlib import Path

        from substitute.app.bootstrap.asset_staging_composition import (
            build_comfy_asset_staging_service,
        )
        from substitute.domain.onboarding import (
            ComfyEndpoint,
            ComfyTargetConfiguration,
            ComfyTargetMode,
            InstallationConfiguration,
            InstallationContext,
            RuntimeConfiguration,
        )

        installation = InstallationConfiguration.create_default(Path("E:/substitute"))
        context = InstallationContext(
            installation=installation,
            runtime=RuntimeConfiguration.create_default(installation),
            comfy_target=ComfyTargetConfiguration(
                mode=ComfyTargetMode.MANAGED_LOCAL,
                endpoint=ComfyEndpoint(host="127.0.0.1", port=8188),
                workspace_path=None,
                install_owned=True,
                launch_owned=True,
            ),
        )
        class DefinitionGateway:
            def get_node_definition(self, node_class):
                raise AssertionError("Unexpected definition read")
            def get_required_node_definition(self, node_class):
                raise AssertionError("Unexpected definition read")
        build_comfy_asset_staging_service(context, node_definition_gateway=DefinitionGateway())
        print(json.dumps({"requests_loaded": "requests" in sys.modules}))
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[4],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert json.loads(completed.stdout.strip()) == {"requests_loaded": False}


def test_managed_staging_transports_supplied_live_definition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise factory wiring through canonical staging and external boundaries."""
    live_definition: JsonObject = {
        "name": "SubstituteBackendLoadImage",
        "input": {"required": {"image": ["STRING", {"default": ""}]}},
        "output": ["IMAGE", "MASK"],
    }
    required_reads: list[str] = []

    class LiveGateway(_DefinitionGateway):
        """Supply the installed backend class metadata only when staging requests it."""

        def get_required_node_definition(self, node_class: str) -> JsonObject:
            """Return the controlled external object_info response."""
            required_reads.append(node_class)
            return {"SubstituteBackendLoadImage": live_definition}

    def authorize(
        self: LocalComfyAssetStager,
        *,
        source_path: Path,
        target_subfolder: str,
        content_hash: str,
        node_class: str,
    ) -> ComfyStagedAsset:
        """Replace external authorization with an inert execution value."""
        assert node_class == "LoadImage"
        return ComfyStagedAsset(
            source_path=source_path,
            execution_value="inert-image-value",
            operation="authorized",
            execution_node_class="SubstituteBackendLoadImage",
        )

    monkeypatch.setattr(LocalComfyAssetStager, "stage_file_for_load_image", authorize)
    image = tmp_path / "image.png"
    image.write_bytes(b"image")
    workflow = graph_backed_cube_workflow("Image")
    workflow.cubes["Image"].buffer["nodes"] = {
        "image": {"class_type": "LoadImage", "inputs": {"image": str(image)}},
    }
    assert workflow.direct_workflow is not None
    payload = workflow.direct_workflow.source_workflow
    original = deepcopy(payload)
    service = build_comfy_asset_staging_service(
        _context(ComfyTargetMode.MANAGED_LOCAL),
        node_definition_gateway=LiveGateway(),
    )

    result = service.stage_payload(
        workflow_payload=payload,
        workflow_id="imported",
        workflow_name="Imported",
    )

    assert result.failures == ()
    assert required_reads == ["SubstituteBackendLoadImage"]
    assert payload == original
    definitions = cast(JsonObject, result.workflow_payload["definitions"])
    subgraph = cast(list[JsonObject], definitions["subgraphs"])[0]
    document = cast(
        JsonObject, cast(JsonObject, subgraph["extra"])["sugarcubes_document"]
    )
    implementation = cast(JsonObject, document["implementation"])
    assert (
        cast(JsonObject, implementation["definitions"])["SubstituteBackendLoadImage"]
        == live_definition
    )
    assert cast(JsonObject, implementation["nodes"])["image"] == {
        "class_type": "SubstituteBackendLoadImage",
        "inputs": {"image": "inert-image-value"},
    }
