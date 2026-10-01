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

"""Project embedded canonical Cube nodes for generation-time asset staging."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass

from substitute.application.node_behavior.live_definition_authority import (
    LiveNodeDefinitionAuthority,
)
from substitute.domain.common import JsonObject


class CanonicalCubeAssetDefinitionError(RuntimeError):
    """Describe execution metadata that cannot safely accompany a staged node."""

    def __init__(
        self,
        *,
        section_key: str,
        node_name: str,
        class_type: str,
        reason: str,
    ) -> None:
        """Retain credential-free context for a generation preflight failure."""
        self.section_key = section_key
        self.node_name = node_name
        self.class_type = class_type
        self.reason = reason
        super().__init__(
            f"Invalid staged definition for {section_key}:{node_name} ({class_type}): {reason}"
        )


@dataclass(frozen=True)
class _CanonicalCubeAssetTarget:
    """Bind one execution proxy to its embedded document's metadata owner."""

    section_key: str
    node_name: str
    proxy: dict[str, object]
    node: dict[str, object]
    implementation: dict[str, object]

    def definition_error(
        self, class_type: str, reason: str
    ) -> CanonicalCubeAssetDefinitionError:
        """Build a failure without including transient execution values."""
        return CanonicalCubeAssetDefinitionError(
            section_key=self.section_key,
            node_name=self.node_name,
            class_type=class_type,
            reason=reason,
        )


@dataclass(frozen=True)
class CanonicalCubeAssetProjection:
    """Expose mutable asset-bearing node proxies over embedded Cube documents."""

    prompt: dict[str, object]
    class_type_targets: tuple[_CanonicalCubeAssetTarget, ...]

    def commit_class_types(
        self,
        live_definitions: LiveNodeDefinitionAuthority | None = None,
    ) -> None:
        """Commit changed classes with one live schema snapshot, preserving presets."""
        definitions_by_class: dict[str, Mapping[str, object]] = {}
        changes: list[tuple[_CanonicalCubeAssetTarget, str]] = []
        for target in self.class_type_targets:
            class_type = target.proxy.get("class_type")
            if not isinstance(class_type, str) or class_type == target.node.get(
                "class_type"
            ):
                continue
            if live_definitions is None:
                raise target.definition_error(
                    class_type, "live_definition_authority_missing"
                )
            if class_type not in definitions_by_class:
                try:
                    definitions_by_class[class_type] = (
                        live_definitions.get_required_definition(
                            class_type,
                            operation="canonical_asset_staging",
                            cube_aliases=(target.section_key,),
                            node_names=(target.node_name,),
                        )
                    )
                except (OSError, RuntimeError, TypeError, ValueError) as error:
                    raise target.definition_error(
                        class_type, "live_definition_unavailable"
                    ) from error
            _validate_execution_definition(
                target, class_type, definitions_by_class[class_type]
            )
            existing = target.implementation.get("definitions")
            if "definitions" in target.implementation and not isinstance(
                existing, dict
            ):
                raise target.definition_error(
                    class_type, "invalid_definition_container"
                )
            changes.append((target, class_type))
        for target, class_type in changes:
            definitions = target.implementation.setdefault("definitions", {})
            assert isinstance(definitions, dict)
            definitions[class_type] = deepcopy(dict(definitions_by_class[class_type]))
            target.node["class_type"] = class_type


def _validate_execution_definition(
    target: _CanonicalCubeAssetTarget,
    class_type: str,
    definition: Mapping[str, object],
) -> None:
    """Reject incomplete live schemas before they enter an execution document."""
    if definition.get("name") != class_type:
        raise target.definition_error(class_type, "live_definition_class_mismatch")
    groups = definition.get("input")
    outputs = definition.get("output")
    if (
        not isinstance(groups, Mapping)
        or not isinstance(outputs, Sequence)
        or isinstance(outputs, (str, bytes))
        or not all(isinstance(value, str) and value for value in outputs)
    ):
        raise target.definition_error(class_type, "malformed_live_definition")
    fields: dict[str, object] = {}
    for group_name in ("required", "optional"):
        group = groups.get(group_name, {})
        if not isinstance(group, Mapping):
            raise target.definition_error(class_type, "malformed_live_definition")
        fields.update({str(name): info for name, info in group.items()})
    inputs = target.proxy.get("inputs")
    assert isinstance(inputs, Mapping)
    for field_key in inputs:
        info = fields.get(str(field_key))
        if (
            not isinstance(info, Sequence)
            or isinstance(info, (str, bytes))
            or not info
            or not isinstance(info[0], (str, list, tuple))
            or not info[0]
        ):
            raise target.definition_error(
                class_type, f"missing_or_malformed_input:{field_key}"
            )


def project_canonical_cube_asset_nodes(
    workflow: JsonObject,
) -> CanonicalCubeAssetProjection | None:
    """Return staging proxies when a workflow uses canonical Cube definitions."""
    instances = workflow.get("nodes")
    definitions_container = workflow.get("definitions")
    if not isinstance(instances, list) or not isinstance(
        definitions_container, Mapping
    ):
        return None
    definitions = definitions_container.get("subgraphs")
    if not isinstance(definitions, list):
        return None
    documents = _documents_by_definition(definitions)
    prompt: dict[str, object] = {}
    class_type_targets: list[_CanonicalCubeAssetTarget] = []
    for instance in instances:
        if not isinstance(instance, Mapping):
            continue
        definition_id = instance.get("type")
        alias = _instance_alias(instance)
        document = (
            documents.get(definition_id) if isinstance(definition_id, str) else None
        )
        implementation = (
            document.get("implementation") if document is not None else None
        )
        if alias is None or not isinstance(implementation, dict):
            continue
        nodes = implementation.get("nodes")
        if not isinstance(nodes, dict):
            continue
        for node_name, raw_node in nodes.items():
            if not isinstance(raw_node, dict):
                continue
            inputs = raw_node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            proxy: dict[str, object] = {
                "class_type": raw_node.get("class_type"),
                "inputs": inputs,
                "_meta": {"title": f"{alias}.{node_name}"},
            }
            prompt[f"{alias}:{node_name}"] = proxy
            class_type_targets.append(
                _CanonicalCubeAssetTarget(
                    section_key=alias,
                    node_name=str(node_name),
                    proxy=proxy,
                    node=raw_node,
                    implementation=implementation,
                )
            )
    return CanonicalCubeAssetProjection(
        prompt=prompt, class_type_targets=tuple(class_type_targets)
    )


def _documents_by_definition(definitions: list[object]) -> dict[str, JsonObject]:
    """Index embedded canonical documents by subgraph definition id."""
    result: dict[str, JsonObject] = {}
    for definition in definitions:
        if not isinstance(definition, Mapping):
            continue
        definition_id = definition.get("id")
        extra = definition.get("extra")
        document = (
            extra.get("sugarcubes_document") if isinstance(extra, Mapping) else None
        )
        if isinstance(definition_id, str) and isinstance(document, dict):
            result[definition_id] = document
    return result


def _instance_alias(instance: Mapping[str, object]) -> str | None:
    """Read the stable authored alias from one marked Cube instance."""
    properties = instance.get("properties")
    marker = (
        properties.get("sugarcubes_cube") if isinstance(properties, Mapping) else None
    )
    alias = marker.get("instance_alias") if isinstance(marker, Mapping) else None
    return alias if isinstance(alias, str) and alias else None


__all__ = [
    "CanonicalCubeAssetDefinitionError",
    "CanonicalCubeAssetProjection",
    "project_canonical_cube_asset_nodes",
]
