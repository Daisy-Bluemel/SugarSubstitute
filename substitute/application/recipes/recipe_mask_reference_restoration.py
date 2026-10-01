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

"""Restore explicit scalar mask provenance at the canonical recipe load boundary."""

from __future__ import annotations

from pathlib import Path

from substitute.application.workflows.input_canvas_binding_service import (
    InputCanvasBindingService,
)
from substitute.application.workflows.workflow_asset_service import WorkflowAssetService
from substitute.application.workflows.workflow_graph_section_service import (
    WorkflowGraphSectionService,
)
from substitute.domain.workflow import (
    InputAssetCardinality,
    LocalFileAssetRef,
    WorkflowState,
)


class RecipeMaskReferenceRestoration:
    """Register loaded absolute mask paths without changing authored graph values."""

    def __init__(
        self,
        *,
        bindings: InputCanvasBindingService,
        graphs: WorkflowGraphSectionService,
        assets: WorkflowAssetService,
    ) -> None:
        """Reuse graph binding and metadata ownership without introducing membership."""

        self._bindings = bindings
        self._graphs = graphs
        self._assets = assets

    def restore(self, workflow: WorkflowState) -> None:
        """Promote only proven recipe scalar paths through the asset authority."""

        for section_key in self._graphs.section_keys(workflow):
            for binding in self._bindings.plan(workflow, section_key).mask_bindings:
                if binding.mask_endpoint.cardinality is InputAssetCardinality.ORDERED:
                    continue
                value = self._graphs.input_value(
                    workflow,
                    section_key=section_key,
                    node_name=binding.mask_node_name,
                    field_key=binding.mask_field_key,
                )
                if not isinstance(value, str) or not Path(value).is_absolute():
                    continue
                if not self._assets.associate_input_mask(
                    workflow,
                    section_key=section_key,
                    node_name=binding.mask_node_name,
                    field_key=binding.mask_field_key,
                    asset_ref=LocalFileAssetRef(value),
                ):
                    raise RuntimeError(
                        "Could not restore an explicit recipe mask reference"
                    )


__all__ = ["RecipeMaskReferenceRestoration"]
