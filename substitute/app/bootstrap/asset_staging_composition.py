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

"""Compose local or remote execution asset staging with live node metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING

from substitute.domain.onboarding import InstallationContext

if TYPE_CHECKING:
    from substitute.application.generation.asset_staging_service import (
        ComfyAssetStagingService,
    )
    from substitute.application.generation.input_asset_staging_plan_service import (
        InputAssetStagingPlanService,
    )
    from substitute.application.ports import NodeDefinitionGateway


def build_comfy_asset_staging_service(
    context: InstallationContext,
    *,
    node_definition_gateway: NodeDefinitionGateway,
    input_asset_staging_plan_service: InputAssetStagingPlanService | None = None,
) -> ComfyAssetStagingService:
    """Compose target-specific Comfy asset staging at the bootstrap boundary."""

    from substitute.application.node_behavior.live_definition_authority import (
        LiveNodeDefinitionAuthority,
    )
    from substitute.application.generation.asset_staging_service import (
        ComfyAssetStagingService,
    )
    from substitute.application.ports.comfy_asset_stager import ComfyAssetStager
    from substitute.domain.onboarding import ComfyTargetMode
    from substitute.infrastructure.comfy import (
        LocalComfyAssetStager,
        RemoteUploadComfyAssetStager,
    )

    if context.comfy_target.mode is ComfyTargetMode.REMOTE:
        stager: ComfyAssetStager = RemoteUploadComfyAssetStager(
            endpoint=context.comfy_target.endpoint
        )
        ordered_stager = stager
    else:
        stager = LocalComfyAssetStager(endpoint=context.comfy_target.endpoint)
        ordered_stager = RemoteUploadComfyAssetStager(
            endpoint=context.comfy_target.endpoint
        )
    return ComfyAssetStagingService.with_projects_dir(
        stager=stager,
        ordered_stager=ordered_stager,
        projects_dir=context.projects_dir,
        input_asset_staging_plan_service=input_asset_staging_plan_service,
        live_node_definitions=LiveNodeDefinitionAuthority(node_definition_gateway),
    )


__all__ = ["build_comfy_asset_staging_service"]
