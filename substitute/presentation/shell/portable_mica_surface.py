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

"""Own portable wallpaper material and its window-bound observation lifecycle."""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QPixmap, QScreen
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid
from cutemica.enums import ResolvedTheme  # type: ignore[import-untyped]
from cutemica.providers.qt_screens import infer_qt_screen_bindings  # type: ignore[import-untyped]
from cutemica.providers.window_geometry import (  # type: ignore[import-untyped]
    WindowGeometryProvider,
    create_window_geometry_provider,
)
from cutemica.wallpaper import WallpaperSnapshot  # type: ignore[import-untyped]

from substitute.infrastructure.appearance.mica_wallpaper_provider import (
    create_mica_wallpaper_provider,
)
from substitute.presentation.shell.mica_backdrop_presenter import MicaBackdropPresenter
from substitute.presentation.shell.mica_material_controller import (
    MicaMaterialController,
)
from substitute.presentation.shell.mica_wallpaper_observer import MicaWallpaperObserver
from substitute.shared.logging.logger import get_logger, log_warning

_LOGGER = get_logger("presentation.shell.portable_mica_surface")


class MicaTheme(QObject):
    """Adapt the application's resolved theme without a second desktop poller."""

    theme_changed = Signal(object)

    def __init__(self, dark: bool, parent: QObject) -> None:
        """Retain the one theme resolved by the application appearance owner."""

        super().__init__(parent)
        self.resolved = ResolvedTheme.DARK if dark else ResolvedTheme.LIGHT


class PortableMicaSurface(QObject):
    """Keep renderer state and source monitoring scoped to one shell window.

    The only retained images are CuteMica's bounded process-lifetime per-display
    textures. Movement presents cached geometry; source, theme and screen changes
    create new material. A failed generation exposes the shell's opaque base.
    """

    state_changed = Signal(bool)

    def __init__(self, window: QWidget, *, dark: bool) -> None:
        """Observe the window and defer discovery until it is actually shown."""

        super().__init__(window)
        self._window = window
        self._dark = dark
        self._ready = False
        self._last_error: str | None = None
        self._failed_generation = False
        self._disposed = False
        self._dirty = True
        self._pending_screens: set[str] = set()
        self._controller: MicaMaterialController | None = None
        self._presenter: MicaBackdropPresenter | None = None
        self._theme: MicaTheme | None = None
        self._monitor: MicaWallpaperObserver | None = None
        self._geometry: WindowGeometryProvider | None = None
        self._screens: list[QScreen] = []
        self._provider_name = "unavailable"
        self._generation_count = 0
        self._initialize_timer = QTimer(self)
        self._initialize_timer.setSingleShot(True)
        self._initialize_timer.timeout.connect(self._initialize)
        window.installEventFilter(self)
        application = QGuiApplication.instance()
        if isinstance(application, QGuiApplication):
            application.screenAdded.connect(self._schedule_rebuild)
            application.screenRemoved.connect(self._schedule_rebuild)
        if window.isVisible():
            self._initialize_timer.start(0)

    @property
    def ready(self) -> bool:
        """Report whether actual generated material is currently presented."""

        return self._ready

    @property
    def last_error(self) -> str | None:
        """Expose the latest discovery or rendering failure for diagnostics."""

        return self._last_error

    @property
    def wallpaper_provider_name(self) -> str:
        """Describe source discovery without exposing its image path."""

        return self._provider_name

    @property
    def material_cache_signature(self) -> tuple[tuple[str, int], ...]:
        """Expose immutable texture identities for material diagnostics."""

        if self._presenter is None:
            return ()
        return cast(
            tuple[tuple[str, int], ...], self._presenter.material_cache_signature
        )

    @property
    def generation_count(self) -> int:
        """Report generation starts independently of movement and repainting."""

        return self._generation_count

    def set_dark(self, dark: bool) -> None:
        """Replace old-theme textures before attempting the next generation."""

        if dark == self._dark:
            return
        self._dark = dark
        self._release_components()
        self._initialize_timer.start(0)

    def dispose(self) -> None:
        """Stop all observation and detach the painted child before owner deletion."""

        if self._disposed:
            return
        self._disposed = True
        self._initialize_timer.stop()
        self._window.removeEventFilter(self)
        application = QGuiApplication.instance()
        if isinstance(application, QGuiApplication):
            application.screenAdded.disconnect(self._schedule_rebuild)
            application.screenRemoved.disconnect(self._schedule_rebuild)
        self._disconnect_screens()
        self._release_components()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Present cached movement and rebuild only for display identity changes."""

        if self._disposed or watched is not self._window:
            return False
        kind = event.type()
        if kind in {QEvent.Type.Move, QEvent.Type.Resize}:
            self._present(immediate=True)
        elif kind == QEvent.Type.Show:
            if self._dirty or self._controller is None:
                self._initialize_timer.start(0)
            elif self._monitor is not None:
                self._monitor.start()
                self._present(immediate=False)
        elif kind == QEvent.Type.Hide:
            if self._monitor is not None:
                self._monitor.stop()
        elif kind in {
            QEvent.Type.ScreenChangeInternal,
            QEvent.Type.DevicePixelRatioChange,
        }:
            self._present(immediate=True)
        return False

    @Slot()
    def _schedule_rebuild(self) -> None:
        """Coalesce topology changes outside the movement hot path."""

        if not self._disposed:
            self._dirty = True
            if self._presenter is not None:
                self._presenter.hide()
            self._set_ready(False)
            self._initialize_timer.start(0)

    @Slot()
    def _initialize(self) -> None:
        """Bind current screens and start nonblocking desktop source observation."""

        if self._disposed or not self._window.isVisible():
            return
        self._release_components()
        self._dirty = False
        try:
            screens = list(QGuiApplication.screens())
            bindings = infer_qt_screen_bindings(screens)
            provider = create_mica_wallpaper_provider()
            self._provider_name = str(provider.name)
            self._geometry = create_window_geometry_provider(bindings)
            observer = MicaWallpaperObserver(provider, bindings, parent=self)
            self._monitor = observer
            observer.snapshot_ready.connect(self._on_wallpaper_changed)
            observer.failed.connect(self._on_failure)
            self._disconnect_screens()
            self._screens = screens
            for screen in screens:
                screen.geometryChanged.connect(self._schedule_rebuild)
                screen.logicalDotsPerInchChanged.connect(self._schedule_rebuild)
                screen.physicalDotsPerInchChanged.connect(self._schedule_rebuild)
            observer.start()
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            self._on_failure(str(error))
            self._release_components()

    @Slot(int)
    def _on_generation_started(self, _generation: int) -> None:
        """Allow publication only from a generation that has not failed."""

        self._last_error = None
        self._generation_count += 1
        self._failed_generation = False
        self._pending_screens = (
            {str(binding.cache_key) for binding in self._controller.bindings}
            if self._controller is not None
            else set()
        )
        if self._presenter is not None:
            self._presenter.hide()
        self._set_ready(False)

    @Slot(str, QPixmap, float)
    def _on_material_ready(self, key: str, _material: QPixmap, _elapsed: float) -> None:
        """Track per-screen publication without displaying a mixed generation."""

        self._pending_screens.discard(key)

    @Slot(int)
    def _on_generation_finished(self, _generation: int) -> None:
        """Present only a complete successful set of current display materials."""

        if (
            self._dirty
            or self._disposed
            or self._failed_generation
            or self._pending_screens
            or self._presenter is None
        ):
            return
        self._presenter.show()
        self._presenter.lower()
        self._present(immediate=False)
        self._set_ready(True)

    @Slot(object)
    def _on_wallpaper_changed(self, value: object) -> None:
        """Initialize or update material, retrying equal metadata after a failure."""

        if not isinstance(value, WallpaperSnapshot) or self._dirty or self._disposed:
            return
        if not self._window.isVisible():
            return
        try:
            if self._controller is None:
                bindings = infer_qt_screen_bindings(self._screens)
                self._theme = MicaTheme(self._dark, self)
                controller = MicaMaterialController(
                    value, bindings, self._theme, parent=self
                )
                self._controller = controller
                presenter = MicaBackdropPresenter(controller, self._window)
                self._presenter = presenter
                presenter.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                presenter.setGeometry(self._window.rect())
                presenter.hide()
                controller.material_ready.connect(self._on_material_ready)
                controller.error.connect(self._on_failure)
                controller.generation_started.connect(self._on_generation_started)
                controller.generation_finished.connect(self._on_generation_finished)
                self._present(immediate=False)
                controller.refresh()
            else:
                was_failed = self._failed_generation
                previous_generation = self._generation_count
                accepted = self._controller.update_wallpaper(value)
                if (
                    accepted
                    and was_failed
                    and self._generation_count == previous_generation
                ):
                    self._controller.refresh()
        except (OSError, RuntimeError, ValueError) as error:
            self._on_failure(str(error))

    @Slot(str)
    def _on_failure(self, reason: str) -> None:
        """Expose the themed plain surface and retain actionable failure context."""

        self._last_error = reason
        self._failed_generation = True
        if self._presenter is not None:
            self._presenter.hide()
        self._set_ready(False)
        log_warning(
            _LOGGER,
            "Portable Mica unavailable; using Plain",
            provider=self._provider_name,
            error=reason,
        )

    def _set_ready(self, ready: bool) -> None:
        """Publish effective material state only when it changes."""

        if ready != self._ready:
            self._ready = ready
            self.state_changed.emit(ready)

    def _present(self, *, immediate: bool) -> None:
        """Sample one current client rectangle and paint already prepared textures."""

        if self._presenter is None or self._geometry is None:
            return
        self._presenter.setGeometry(self._window.rect())
        self._presenter.present(
            self._geometry.snapshot(self._window), immediate=immediate
        )

    def _disconnect_screens(self) -> None:
        """Detach former display metadata signals before replacing their bindings."""

        previous, self._screens = self._screens, []
        for screen in previous:
            if isValid(screen):
                screen.geometryChanged.disconnect(self._schedule_rebuild)
                screen.logicalDotsPerInchChanged.disconnect(self._schedule_rebuild)
                screen.physicalDotsPerInchChanged.disconnect(self._schedule_rebuild)

    def _release_components(self) -> None:
        """Disconnect old publication signals before hiding and deleting a renderer."""

        if self._monitor is not None:
            self._monitor.stop()
            self._monitor.snapshot_ready.disconnect(self._on_wallpaper_changed)
            self._monitor.failed.disconnect(self._on_failure)
            self._monitor.deleteLater()
            self._monitor = None
        if self._controller is not None:
            self._controller.material_ready.disconnect(self._on_material_ready)
            self._controller.error.disconnect(self._on_failure)
            self._controller.generation_started.disconnect(self._on_generation_started)
            self._controller.generation_finished.disconnect(
                self._on_generation_finished
            )
            self._controller.deleteLater()
            self._controller = None
        if self._presenter is not None:
            self._presenter.hide()
            self._presenter.deleteLater()
            self._presenter = None
        if self._theme is not None:
            self._theme.deleteLater()
            self._theme = None
        self._geometry = None
        self._set_ready(False)
