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

"""Materialize exact mask products without choosing their persistence purpose."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol
from uuid import UUID

from cutecanvas import MaskExportSnapshot

from substitute.domain.workflow import WorkflowState
from substitute.presentation.canvas.input.input_mask_identity import (
    resolve_input_mask_id,
)
from substitute.shared.logging.logger import (
    get_logger,
    log_error,
    log_exception,
    log_info,
)

_LOGGER = get_logger("presentation.canvas.input.input_mask_product_materializer")


@dataclass(frozen=True, slots=True)
class InputMaskProductTarget:
    """Name one durable image and its exact serialized graph reference."""

    destination: Path
    authoring_path: Path


class MaskProductImageWriterPort(Protocol):
    """Persist detached mask pixels through the existing image IO owner."""

    def save_mask_image(self, *, destination: Path, image: object) -> bool:
        """Publish one complete mask image and report durable completion."""


class MaskProductAssociationPort(Protocol):
    """Describe detached-workflow mask association through workflow semantics."""

    def associate_project_input_mask(
        self,
        workflow: WorkflowState,
        *,
        section_key: str,
        node_name: str,
        relative_path: Path | str,
    ) -> bool:
        """Associate one copied graph input with a project mask snapshot."""

    def associate_project_ordered_input_mask(
        self,
        workflow: WorkflowState,
        *,
        section_key: str,
        node_name: str,
        region_id: UUID,
        relative_path: Path | str,
    ) -> bool:
        """Associate one copied ordered region with a project mask snapshot."""


class InputMaskProductMaterializer:
    """Apply captured masks to a detached workflow for an explicit consumer."""

    def __init__(
        self,
        *,
        canvas_io_service: MaskProductImageWriterPort,
        input_assets: MaskProductAssociationPort,
    ) -> None:
        """Bind persistence and workflow-copy collaborators."""
        self._canvas_io_service = canvas_io_service
        self._input_assets = input_assets

    def prepare_workflow(
        self,
        *,
        workflow_id: str,
        workflow: object,
        snapshots: Mapping[UUID, MaskExportSnapshot],
        workflow_name: str,
        target_for_snapshot: Callable[[MaskExportSnapshot], InputMaskProductTarget],
    ) -> object | None:
        """Return a copied workflow referencing exact bounded mask products."""
        if not isinstance(workflow, WorkflowState):
            return copy.deepcopy(workflow)
        prepared_workflow = copy.deepcopy(workflow)
        associations = self._mask_associations(workflow)
        if not associations:
            return prepared_workflow
        for association_key, region_id, raw_mask_id in associations:
            key = self._resolve_association_key(association_key)
            mask_id = resolve_input_mask_id(raw_mask_id)
            if (
                key is None
                or mask_id is None
                or not self._mask_belongs_to_workflow_input(workflow, mask_id)
            ):
                self._log_failure(
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    association_key=association_key,
                    mask_id=raw_mask_id,
                    reason="invalid_mask_association",
                )
                return None
            snapshot = snapshots.get(mask_id)
            if snapshot is None or snapshot.mask_id != mask_id:
                self._log_failure(
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    association_key=association_key,
                    mask_id=mask_id,
                    reason="missing_mask_snapshot",
                )
                return None
            try:
                target = target_for_snapshot(snapshot)
                destination = target.destination
                saved = self._canvas_io_service.save_mask_image(
                    destination=destination,
                    image=snapshot.image,
                )
            except (
                AttributeError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as error:
                log_exception(
                    _LOGGER,
                    "Exact Input mask revision persistence raised",
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    association_key=str(association_key),
                    mask_id=str(mask_id),
                    mask_revision=snapshot.revision,
                    error=error,
                )
                saved = False
            if not saved:
                self._log_failure(
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    association_key=association_key,
                    mask_id=mask_id,
                    reason="snapshot_persistence_failed",
                )
                return None
            cube_alias, node_name = key
            try:
                if region_id is None:
                    associated = self._input_assets.associate_project_input_mask(
                        prepared_workflow,
                        section_key=cube_alias,
                        node_name=node_name,
                        relative_path=target.authoring_path,
                    )
                else:
                    associated = (
                        self._input_assets.associate_project_ordered_input_mask(
                            prepared_workflow,
                            section_key=cube_alias,
                            node_name=node_name,
                            region_id=region_id,
                            relative_path=target.authoring_path,
                        )
                    )
            except (AttributeError, RuntimeError, TypeError, ValueError) as error:
                log_exception(
                    _LOGGER,
                    "Exact Input mask revision association raised",
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    association_key=str(association_key),
                    mask_id=str(mask_id),
                    mask_revision=snapshot.revision,
                    error=error,
                )
                associated = False
            if not associated:
                self._log_failure(
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    association_key=association_key,
                    mask_id=mask_id,
                    reason="product_association_failed",
                )
                return None
            log_info(
                _LOGGER,
                "Materialized exact Input mask revision for persistence",
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                cube_alias=cube_alias,
                node_name=node_name,
                region_id=str(region_id) if region_id is not None else "",
                mask_id=str(mask_id),
                composition_id=str(snapshot.composition_id),
                mask_revision=snapshot.revision,
                destination=str(destination),
            )
        return prepared_workflow

    @staticmethod
    def _mask_associations(
        workflow: WorkflowState,
    ) -> tuple[tuple[tuple[str, str], UUID | None, UUID], ...]:
        """Return scalar masks followed by each collection's exact authored order."""

        scalar = tuple(
            (entry.association_key, None, entry.mask_id)
            for entry in sorted(
                workflow.canvas.mask_entries.values(),
                key=lambda candidate: candidate.association_key,
            )
        )
        ordered = tuple(
            (collection.association_key, entry.region_id, entry.mask_id)
            for collection in sorted(
                workflow.canvas.regional_mask_collections.values(),
                key=lambda candidate: candidate.association_key,
            )
            for entry in collection.entries
            if entry.mask_id is not None
        )
        return scalar + ordered

    @staticmethod
    def _resolve_association_key(key: object) -> tuple[str, str] | None:
        """Return non-empty cube and node identities from one association key."""
        if not (isinstance(key, tuple) and len(key) == 2):
            return None
        cube_alias, node_name = key
        if not isinstance(cube_alias, str) or not isinstance(node_name, str):
            return None
        if not cube_alias or not node_name:
            return None
        return cube_alias, node_name

    @staticmethod
    def _mask_belongs_to_workflow_input(
        workflow: WorkflowState,
        mask_id: UUID,
    ) -> bool:
        """Require the mask to belong to one image retained by this workflow."""
        image_id = workflow.canvas.mask_image_owners().get(mask_id)
        if image_id is None:
            return False
        return workflow.canvas.image_entry_for_id(image_id) is not None

    @staticmethod
    def _log_failure(
        *,
        workflow_id: str,
        workflow_name: str,
        association_key: object,
        mask_id: object,
        reason: str,
    ) -> None:
        """Record a publication-blocking mask-product failure."""
        log_error(
            _LOGGER,
            "Failed to materialize exact Input mask revision for persistence",
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            association_key=str(association_key),
            mask_id=str(mask_id),
            failure_reason=reason,
        )


__all__ = [
    "InputMaskProductMaterializer",
    "InputMaskProductTarget",
    "MaskProductAssociationPort",
    "MaskProductImageWriterPort",
]
