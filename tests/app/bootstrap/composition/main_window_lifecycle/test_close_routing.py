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

"""Verify real frameless close ownership through bootstrap and frame reload."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from substitute.app.bootstrap import composition
from substitute.app.bootstrap.appearance_runtime import AppearanceRuntimeController
from substitute.app.bootstrap.custom_window import CustomWindow, ShutdownRequest
from substitute.app.bootstrap.main_window_runtime import MainWindowRuntime
from substitute.domain.onboarding import (
    ComfyEndpoint,
    ComfyTargetConfiguration,
    ComfyTargetMode,
    InstallationConfiguration,
    InstallationContext,
    RuntimeBootstrapStatus,
    RuntimeConfiguration,
)
from substitute.domain.onboarding.runtime_layout import runtime_layout_for_root
from substitute.presentation.shell.shell_resource_lifecycle import (
    ShellResourceLifecycle,
)
from substitute.presentation.shell.window_effects import ShellBackdropMode
from tests.support.qt.lifecycle import ensure_qt_application, destroy_widget_roots


class _Body(QWidget):
    """Provide unrelated body integration ports while retaining the real frame."""

    comfy_output_panel_visibility_changed = Signal(bool)

    def __init__(self, **_kwargs: object) -> None:
        """Compose inert body adapters without replacing titlebar or close signals."""
        super().__init__()
        self.shell_frame_integration_controller = SimpleNamespace(
            set_taskbar_progress_presenter=lambda _presenter: None,
            attach_app_orb_menu=lambda _orb: None,
            set_generation_titlebar_control_registry=lambda _registry: None,
            attach_startup_diagnostics_titlebar=lambda _button, _repository: None,
        )
        self.comfy_runtime_actions = SimpleNamespace(
            set_comfy_output_panel_visible=lambda _visible: None,
            is_comfy_output_panel_visible=lambda: False,
        )
        self.workspace_generation_actions = SimpleNamespace(
            on_generate_clicked=lambda: None,
            on_skip_generation_clicked=lambda: None,
            on_stop_generation_clicked=lambda: None,
        )
        self.generation_queue_controller = SimpleNamespace(
            show_for=lambda _widget: None,
            show_context_menu_for=lambda _widget: None,
        )
        self.generation_action_controller = SimpleNamespace(
            set_generation_selected_mode=lambda _mode: None,
        )


def _ready_context(root: Path) -> InstallationContext:
    """Provide a ready test installation without launching a backend or Python."""
    installation = InstallationConfiguration.create_default(root)
    return InstallationContext(
        installation=installation,
        runtime=RuntimeConfiguration(
            runtime_root=installation.runtime_dir,
            python_executable=runtime_layout_for_root(
                installation.runtime_dir
            ).python_executable,
            bootstrap_status=RuntimeBootstrapStatus.READY,
        ),
        comfy_target=ComfyTargetConfiguration(
            mode=ComfyTargetMode.REMOTE,
            endpoint=ComfyEndpoint(host="127.0.0.1", port=8188),
            workspace_path=None,
            install_owned=False,
            launch_owned=False,
        ),
    )


@pytest.mark.parametrize("reload_frame", [False, True], ids=["initial", "reloaded"])
def test_each_real_titlebar_click_requests_close_once_after_cancel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reload_frame: bool,
) -> None:
    """Keep each deliberate click and the common close-event path independently owned."""
    ensure_qt_application()
    lifecycle = ShellResourceLifecycle()
    requests: list[QWidget | None] = []
    owned_frames: list[CustomWindow] = []

    def create_owned_frame(
        *,
        appearance_runtime: AppearanceRuntimeController,
        shutdown_request: ShutdownRequest | None = None,
        backdrop_mode: ShellBackdropMode | None = ShellBackdropMode.MICA_ALT,
        create_body_material_surface: bool = False,
    ) -> CustomWindow:
        """Retain actual frames for cleanup even if later composition fails."""
        frame = CustomWindow(
            appearance_runtime=appearance_runtime,
            shutdown_request=shutdown_request,
            backdrop_mode=backdrop_mode,
            create_body_material_surface=create_body_material_surface,
        )
        frame.suppress_app_quit_on_close()
        owned_frames.append(frame)
        return frame

    appearance = SimpleNamespace(
        resolve_preferences=lambda: SimpleNamespace(
            effective_theme_mode=SimpleNamespace(value="dark"),
            effective_accent_color="#E91E63",
            effective_backdrop_mode=None,
        )
    )
    monkeypatch.setattr(
        composition, "_configure_control_registry_service", lambda: None
    )
    monkeypatch.setattr(
        composition,
        "_build_main_window_dependencies",
        lambda _runtime: SimpleNamespace(shell_resource_lifecycle=lifecycle),
    )
    monkeypatch.setattr(composition, "CustomWindow", create_owned_frame)
    monkeypatch.setattr(
        composition,
        "load_main_window_runtime",
        lambda: MainWindowRuntime(
            main_window_class=_Body,
            create_taskbar_progress_presenter=lambda _frame: object(),
        ),
    )
    monkeypatch.setattr(
        "substitute.presentation.shell.taskbar_progress.create_taskbar_progress_presenter",
        lambda _frame: object(),
    )
    try:
        frame = composition.show_main_window(
            _ready_context(tmp_path),
            comfy_output_stream=cast(Any, object()),
            shutdown_request=requests.append,
            runtime_services=cast(Any, SimpleNamespace(appearance_runtime=appearance)),
        )
        assert isinstance(frame, CustomWindow)
        body = composition.main_window_widget(frame)
        assert isinstance(body, _Body)
        if reload_frame:
            previous = frame
            frame = composition.reload_shell_frame(frame)
            assert frame is not previous
            assert composition.main_window_widget(frame) is body
            assert requests == []
            QCoreApplication.sendPostedEvents(previous, QEvent.Type.DeferredDelete)
            assert not isValid(previous)
            assert isValid(body)
        assert frame.isVisible()
        QTest.mouseClick(frame.titleBar.closeBtn, Qt.MouseButton.LeftButton)
        assert requests == [frame]
        assert frame.isVisible()
        assert composition.main_window_widget(frame) is body
        QTest.mouseClick(frame.titleBar.closeBtn, Qt.MouseButton.LeftButton)
        assert requests == [frame, frame]
        assert frame.isVisible()
        assert not frame.close()
        assert requests == [frame, frame, frame]
        assert frame.isVisible()
    finally:
        live_frames = [owner for owner in owned_frames if isValid(owner)]
        for owner in live_frames:
            owner.suppress_app_quit_on_close()
            owner.allow_direct_close()
        destroy_widget_roots(live_frames)
