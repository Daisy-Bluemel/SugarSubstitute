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

"""Contract tests for authoritative external input-asset field semantics."""

from __future__ import annotations

import pytest

from substitute.application.workflows.input_asset_field_policy import (
    InputAssetFieldPolicy,
)
from substitute.application.workflows.input_asset_field_service import (
    InputAssetFieldService,
)
from substitute.domain.workflow import InputAssetCardinality, InputAssetRole


def test_live_metadata_owns_custom_ordered_mask_semantics() -> None:
    """Live upload, cardinality, and output metadata should form one contract."""

    fields = InputAssetFieldPolicy().fields_for_node(
        "CustomMaskBatch",
        {
            "input": {
                "required": {
                    "files": [
                        "LIST",
                        {"image_upload": True, "allow_batch": True},
                    ]
                }
            },
            "output": ["MASK"],
        },
    )

    assert len(fields) == 1
    assert fields[0].field_key == "files"
    assert fields[0].preferred_role is InputAssetRole.MASK
    assert fields[0].cardinality is InputAssetCardinality.ORDERED


def test_output_folder_picker_is_not_an_input_asset() -> None:
    """Output-folder selectors should remain outside input transport ownership."""

    fields = InputAssetFieldPolicy().fields_for_node(
        "OutputBrowser",
        {
            "input": {
                "required": {
                    "image": [
                        "LIST",
                        {"image_upload": True, "image_folder": "output"},
                    ]
                }
            },
            "output": ["IMAGE"],
        },
    )

    assert fields == ()


def test_legacy_contracts_recover_roles_before_live_metadata_arrives() -> None:
    """Built-in image and mask fields should remain typed during restore."""

    policy = InputAssetFieldPolicy()

    image_field = policy.fields_for_node("LoadImage", {})[0]
    mask_field = policy.fields_for_node("LoadImageMask", {})[0]
    ordered_field = policy.fields_for_node("SimpleSyrup.LoadMaskBatch", {})[0]

    assert image_field.preferred_role is InputAssetRole.IMAGE
    assert mask_field.preferred_role is InputAssetRole.MASK
    assert ordered_field.preferred_role is InputAssetRole.MASK
    assert ordered_field.cardinality is InputAssetCardinality.ORDERED


@pytest.mark.parametrize("upload_key", ["audio_upload", "video_upload", "file_upload"])
def test_preserved_upload_reference_does_not_authorize_image_staging(
    upload_key: str,
) -> None:
    """Preserving a backend filename cannot acquire image/mask transport roles."""
    policy = InputAssetFieldPolicy()
    field_info: list[object] = ["COMBO", {upload_key: True, "options": ["old.ext"]}]
    assert policy.preserves_file_reference(
        class_type="CustomSource", field_key="resource", field_info=field_info
    )
    assert not policy.is_asset_field(
        class_type="CustomSource", field_key="resource", field_info=field_info
    )
    assert (
        policy.fields_for_node(
            "CustomSource",
            {"input": {"required": {"resource": field_info}}, "output": ["VIDEO"]},
        )
        == ()
    )


def test_output_folder_reference_preserves_name_without_input_staging() -> None:
    """A declared output-file selector still owns its authored reference."""
    policy = InputAssetFieldPolicy()
    field_info: list[object] = [
        "COMBO",
        {"image_upload": True, "image_folder": "output"},
    ]
    assert policy.preserves_file_reference(
        class_type="CustomSource", field_key="resource", field_info=field_info
    )
    assert not policy.is_asset_field(
        class_type="CustomSource", field_key="resource", field_info=field_info
    )


@pytest.mark.parametrize("upload_key", ["audio_upload", "video_upload", "file_upload"])
def test_non_image_uploads_never_become_graph_staging_targets(upload_key: str) -> None:
    """Path-looking upload references stay outside image transport discovery."""
    graph: dict[str, object] = {
        "nodes": {
            "custom": {
                "class_type": "CustomSource",
                "inputs": {"resource": "/private/asset.ext"},
            }
        }
    }
    definitions: dict[str, dict[str, object]] = {
        "CustomSource": {
            "input": {"required": {"resource": ["COMBO", {upload_key: True}]}},
            "output": ["VIDEO"],
        }
    }
    assert (
        InputAssetFieldService().fields_for_graph(graph, node_definitions=definitions)
        == ()
    )
