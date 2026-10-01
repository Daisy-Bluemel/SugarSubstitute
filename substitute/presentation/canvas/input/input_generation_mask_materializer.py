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

"""Choose generation-owned paths for exact detached Input mask products."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol
from uuid import UUID

from cutecanvas import MaskExportSnapshot

from substitute.domain.workflow import WorkflowState
from substitute.presentation.canvas.input.input_mask_product_materializer import (
    InputMaskProductMaterializer,
    InputMaskProductTarget,
    MaskProductAssociationPort,
    MaskProductImageWriterPort,
)


class GenerationMaskCanvasIoPort(MaskProductImageWriterPort, Protocol):
    """Resolve generation snapshots within their workflow project."""

    def resolve_mask_save_path(
        self, *, workflow_name: str, mask_filename: str, projects_dir: Path
    ) -> Path:
        """Return the existing generation mask storage destination."""


class InputGenerationMaskMaterializer:
    """Keep generation namespace policy separate from shared product persistence."""

    def __init__(
        self,
        *,
        canvas_io_service: GenerationMaskCanvasIoPort,
        input_assets: MaskProductAssociationPort,
        workflow_name_provider: Callable[[str], str],
        projects_dir_provider: Callable[[], Path],
    ) -> None:
        """Bind existing generation context and the common mask-product owner."""

        self._canvas_io = canvas_io_service
        self._workflow_name = workflow_name_provider
        self._projects_dir = projects_dir_provider
        self._products = InputMaskProductMaterializer(
            canvas_io_service=canvas_io_service, input_assets=input_assets
        )

    def prepare_workflow(
        self,
        *,
        workflow_id: str,
        workflow: object,
        snapshots: Mapping[UUID, MaskExportSnapshot],
    ) -> object | None:
        """Preserve exact generation paths and detached workflow associations."""

        if not isinstance(workflow, WorkflowState) or not workflow.canvas.mask_ids():
            return copy.deepcopy(workflow)
        workflow_name = self._workflow_name(workflow_id)
        projects_dir = self._projects_dir()

        def target(snapshot: MaskExportSnapshot) -> InputMaskProductTarget:
            """Retain the established per-mask generation revision namespace."""

            relative = (
                Path(".generation") / str(snapshot.mask_id) / f"{snapshot.revision}.png"
            )
            return InputMaskProductTarget(
                destination=self._canvas_io.resolve_mask_save_path(
                    workflow_name=workflow_name,
                    mask_filename=relative.as_posix(),
                    projects_dir=projects_dir,
                ),
                authoring_path=relative,
            )

        return self._products.prepare_workflow(
            workflow_id=workflow_id,
            workflow=workflow,
            snapshots=snapshots,
            workflow_name=workflow_name,
            target_for_snapshot=target,
        )


__all__ = ["InputGenerationMaskMaterializer"]
