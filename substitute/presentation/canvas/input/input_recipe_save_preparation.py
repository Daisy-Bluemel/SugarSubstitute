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

"""Capture live masks and prepare immutable products for explicit recipe saves."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol
from uuid import UUID

from cutecanvas import MaskExportSnapshot

from substitute.application.recipes.workflow_recipe_save_service import (
    RecipeMaskProductStorePort,
)
from substitute.domain.workflow import WorkflowState
from substitute.presentation.canvas.input.input_document_capture import (
    InputDocumentCapture,
)
from substitute.presentation.canvas.input.input_mask_product_materializer import (
    InputMaskProductMaterializer,
    InputMaskProductTarget,
)


class RecipeInputCapturePort(Protocol):
    """Capture explicit workflow identities without consulting the selected mask."""

    def __call__(
        self, *, image_ids: tuple[UUID, ...], mask_ids: tuple[UUID, ...]
    ) -> InputDocumentCapture | None:
        """Return detached products from one coherent Input document revision."""


class InputRecipeSavePreparation:
    """Keep a captured recipe copy and its exclusive products alive until commit."""

    def __init__(
        self,
        *,
        capture_inputs: RecipeInputCapturePort,
        materializer: InputMaskProductMaterializer,
        products: RecipeMaskProductStorePort,
        workflow_name_provider: Callable[[str], str],
    ) -> None:
        """Bind public document capture, common materialization, and save storage."""

        self._capture = capture_inputs
        self._materializer = materializer
        self._products = products
        self._workflow_name = workflow_name_provider

    @contextmanager
    def prepare(
        self, *, workflow_id: str, workflow: WorkflowState, destination: Path
    ) -> Iterator[WorkflowState]:
        """Capture synchronously before IO and publish only a fully prepared copy."""

        mask_ids = tuple(dict.fromkeys(workflow.canvas.mask_ids()))
        if any(not isinstance(mask_id, UUID) for mask_id in mask_ids):
            raise ValueError("Recipe contains an invalid Input mask identity")
        capture = self._capture(image_ids=(), mask_ids=mask_ids)
        if capture is None:
            raise RuntimeError("Could not capture coherent Input masks for recipe save")
        with self._products.create(destination) as directory:

            def target(snapshot: MaskExportSnapshot) -> InputMaskProductTarget:
                """Address each captured mask within this uniquely owned attempt."""

                path = directory / f"{snapshot.mask_id}.png"
                return InputMaskProductTarget(destination=path, authoring_path=path)

            prepared = self._materializer.prepare_workflow(
                workflow_id=workflow_id,
                workflow=workflow,
                snapshots=capture.masks,
                workflow_name=self._workflow_name(workflow_id),
                target_for_snapshot=target,
            )
            if not isinstance(prepared, WorkflowState):
                raise RuntimeError("Could not persist every Input mask for recipe save")
            yield prepared


__all__ = ["InputRecipeSavePreparation"]
