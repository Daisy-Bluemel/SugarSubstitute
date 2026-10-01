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

"""Install per-workflow prompt harness surfaces with shell-owned identity and lifetime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from PySide6.QtWidgets import QWidget

from substitute.presentation.editor.panel.overrides_controller import (
    GlobalOverridesManager,
)
from substitute.presentation.editor.panel.view import EditorPanel
from substitute.presentation.workflows.cube_stack_view import CubeStack
from tests.support.execution import immediate_editor_panel_execution_factories

if TYPE_CHECKING:
    from tests.support.prompt_editor.real_shell.session import PromptEditorRealShell


def install_prompt_workflow_surface(
    shell: PromptEditorRealShell, workflow_id: str
) -> None:
    """Install real workflow widgets used by coordinator route switching."""

    cube_stack = shell.cube_stacks.get(workflow_id)
    if cube_stack is None:
        cube_stack = CubeStack(shell)
        cube_stack.setObjectName(f"{workflow_id}-cube-stack")
        shell.cube_stack_presentation_controller.prepare_stack(cube_stack)
        shell.cube_stacks[workflow_id] = cube_stack
        shell.cube_stack_container.addWidget(cast(QWidget, cube_stack))
    editor_panel = shell.editor_panels.get(workflow_id)
    if editor_panel is None:
        editor_panel = EditorPanel(
            node_definition_gateway=shell.node_definition_gateway,
            prompt_autocomplete_gateway=shell.prompt_autocomplete_gateway,
            prompt_wildcard_catalog_gateway=(shell.prompt_wildcard_catalog_gateway),
            node_behavior_service=shell.node_behavior_service,
            node_presentation_service=shell.node_presentation_service,
            danbooru_url_import_service=shell.danbooru_url_import_service,
            danbooru_wiki_service=shell.danbooru_wiki_service,
            prompt_lora_catalog_service=shell.prompt_lora_catalog_service,
            prompt_spellcheck_service=shell.prompt_spellcheck_service,
            prompt_feature_profile_service=cast(
                Any,
                shell.prompt_feature_profile_service,
            ),
            wheel_adjustment_mode=shell.prompt_wheel_adjustment_mode,
            model_catalog_service=shell.model_catalog_service,
            thumbnail_asset_repository=shell.thumbnail_asset_repository,
            user_preset_service=shell.user_preset_service,
            workflow_id=workflow_id,
            editor_panel_execution_factories=(
                immediate_editor_panel_execution_factories()
            ),
        )
        editor_panel.mainwindow = shell
        editor_panel.setObjectName(f"{workflow_id}-editor-panel")
        editor_panel.setMinimumWidth(412)
        shell.main_window_signal_binder.connect_editor_panel_signals(editor_panel)
        shell.editor_panels[workflow_id] = editor_panel
        shell.editor_panel_container.addWidget(editor_panel)
    if workflow_id not in shell.override_managers:
        manager = GlobalOverridesManager(
            shell,
            pinned_override_service=shell.pinned_override_service,
            node_definition_gateway=shell.node_definition_gateway,
            prompt_autocomplete_gateway=shell.prompt_autocomplete_gateway,
            prompt_wildcard_catalog_gateway=shell.prompt_wildcard_catalog_gateway,
            prompt_lora_catalog_service=shell.prompt_lora_catalog_service,
            model_choice_snapshot_controller=(
                editor_panel.model_choice_snapshot_controller
            ),
            thumbnail_asset_repository=shell.thumbnail_asset_repository,
        )
        shell.override_managers[workflow_id] = manager
