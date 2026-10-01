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

"""Mount the shell geometry owners without application services or native effects."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QStackedWidget, QWidget

from substitute.domain.workflow import WorkflowDocumentKind
from substitute.domain.workspace_snapshot import (
    ShellLayoutSnapshot,
    WorkspaceSnapshot,
    workspace_snapshot_from_json,
    workspace_snapshot_to_json,
)
from substitute.domain.workspace_snapshot.models import (
    WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
)
from substitute.presentation.cubes.cube_stack_metrics import CUBE_STACK_EXPANDED_WIDTH
from substitute.presentation.shell.app_orb_action_cluster import AppOrbCubeStackButton
from substitute.presentation.shell.cube_stack_presentation_controller import (
    CubeStackPresentationController,
)
from substitute.presentation.shell.generation_queue_controller import (
    GenerationQueueController,
)
from substitute.presentation.shell.generation_queue_panel_transition import (
    GenerationQueuePanelTransition,
)
from substitute.presentation.shell.main_window_workspace import WorkspaceSidePanelHost
from substitute.presentation.shell.shell_layout_restore_controller import (
    ShellLayoutRestoreController,
)
from substitute.presentation.shell.workspace_layout_controller import (
    WorkspaceLayoutController,
)
from substitute.presentation.shell.workspace_splitter_controller import (
    WorkspaceSplitterController,
)
from tests.support.qt.lifecycle import activate_widget_layouts


class _MaterialSurface:
    """Accept material requests outside the geometry persistence boundary."""

    def set_cube_stack_region_widget(self, widget: QStackedWidget | None) -> None:
        """Leave geometry independent of material rendering."""

    def set_cube_stack_wash_opacity(self, opacity: float) -> None:
        """Leave geometry independent of material opacity."""


class _OutputActions:
    """Keep the unrelated output log panel closed."""

    def is_comfy_output_panel_visible(self) -> bool:
        """Return the fixed hidden output state."""

        return False

    def set_comfy_output_panel_visible(self, visible: bool) -> None:
        """Reject accidental output state changes from the geometry scenario."""

        assert not visible


class _GenerationActions:
    """Accept queue chrome refresh without mounting generation controls."""

    def apply_generation_action_availability(self) -> None:
        """Leave generation controls outside the layout persistence boundary."""


class _SearchSurface:
    """Accept overlay reposition requests outside persisted geometry."""

    def position_search_box(self) -> None:
        """Leave the independent overlay unmounted."""


class LayoutHarness(QWidget):
    """Compose real splitter, presentation, workspace, and persistence owners."""

    def __init__(
        self, *, compact: bool, direct: bool, presentation_duration: int = 0
    ) -> None:
        """Mount the production zero-margin geometry with Qt's real splitter handle."""

        super().__init__()
        self._active_workspace_route = "workflow"
        self._remembered_workflow_splitter_sizes: tuple[int, ...] = ()
        self._pending_restored_shell_layout: ShellLayoutSnapshot | None = None
        self.autosave_requests = 0
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.editor_output_container = QWidget(self.splitter)
        self.canvas_host_container = QWidget(self.splitter)
        self.canvas_host_container.setMinimumWidth(120)
        self.sidePanelHost = WorkspaceSidePanelHost(self.splitter)
        self.sidePanelHost.set_panel_width(240)
        self.splitter.addWidget(self.editor_output_container)
        self.splitter.addWidget(self.canvas_host_container)
        self.splitter.addWidget(self.sidePanelHost)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.sidePanelHost.hide()
        self.cube_stack_container = QStackedWidget(self.editor_output_container)
        self.cube_stack_container.addWidget(QWidget())
        self.cube_stack_container.setFixedWidth(CUBE_STACK_EXPANDED_WIDTH)
        self.editor = QWidget(self.editor_output_container)
        self.editor.setMinimumWidth(320)
        details_layout = QHBoxLayout(self.editor_output_container)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(0)
        details_layout.addWidget(self.cube_stack_container)
        details_layout.addWidget(self.editor, 1)
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.splitter)
        self.editor_output_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.editor_output_splitter.hide()
        self.generation_action_controller = _GenerationActions()
        self.generation_queue_controller = GenerationQueueController(self)
        self._generation_queue_panel_transition = GenerationQueuePanelTransition(self)
        self.comfy_runtime_actions = _OutputActions()
        self.search_overlay_controller = _SearchSurface()
        self.workspace_splitter_controller = WorkspaceSplitterController(
            splitter=self.splitter,
            details_widget=self.editor_output_container,
            canvas_widget=self.canvas_host_container,
        )
        self.cube_stack_presentation_controller = CubeStackPresentationController(
            container=self.cube_stack_container,
            stacks=lambda: (),
            mode_button=AppOrbCubeStackButton(self),
            material_surface=_MaterialSurface(),
            active_editor_surface=lambda: None,
            splitter_controller=self.workspace_splitter_controller,
            position_search_box=lambda: None,
            request_autosave=self.request_session_autosave,
            duration_resolver=lambda _duration: presentation_duration,
            parent=self,
        )
        self.workspace_layout_controller = WorkspaceLayoutController(self)
        self.shell_layout_restore_controller = ShellLayoutRestoreController(self)
        self.resize(1159, 651)
        self.show()
        self.settle_layout()
        self.cube_stack_presentation_controller.restore_preference(compact)
        self.cube_stack_presentation_controller.activate_document_kind(
            WorkflowDocumentKind.DIRECT_COMFY
            if direct
            else WorkflowDocumentKind.CUBE_STACK,
            animated=False,
        )
        self.settle_layout()

    def active_editor_panel(self) -> QWidget:
        """Return the real editor whose effective width must not become intent."""

        return self.editor

    def request_session_autosave(self) -> None:
        """Record requests without a filesystem or timer dependency."""

        self.autosave_requests += 1

    def settle_layout(self) -> None:
        """Resolve the explicitly mounted layouts without event-loop polling."""

        activate_widget_layouts(self, self.editor_output_container)

    def move_divider(self, editor_width: int = 500) -> None:
        """Publish user geometry through the production splitter-moved owner."""

        effective = (
            self.cube_stack_presentation_controller.current_frame().container_width
        )
        available = sum(self.splitter.sizes())
        left = editor_width + effective
        self.splitter.setSizes([left, available - left, 0])
        self.settle_layout()
        self.workspace_layout_controller.handle_main_splitter_moved(left, 1)

    def capture(self) -> ShellLayoutSnapshot:
        """Capture and round-trip the existing public workspace persistence codec."""

        layout = self.shell_layout_restore_controller.capture_shell_layout_snapshot()
        assert layout is not None
        workspace = WorkspaceSnapshot(
            schema_version=WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
            workflows=(),
            tab_order=(),
            active_route="workflow",
            shell_layout=layout,
        )
        restored = workspace_snapshot_from_json(workspace_snapshot_to_json(workspace))
        assert restored.shell_layout is not None
        return restored.shell_layout

    def restore(self, snapshot: ShellLayoutSnapshot) -> None:
        """Apply both production restore passes after document availability is known."""

        self._pending_restored_shell_layout = snapshot
        for _pass in range(2):
            self.shell_layout_restore_controller.apply_deferred_restored_shell_layout(
                snapshot, finalize=False
            )
            self.settle_layout()
