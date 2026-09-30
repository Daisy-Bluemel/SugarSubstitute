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

"""Verify complete material publication and removed-display recovery."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import cast

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPixmap, QScreen
from PySide6.QtWidgets import QApplication, QWidget
import pytest
from cutemica.geometry import Rect, ScreenBinding  # type: ignore[import-untyped]
from cutemica.wallpaper import WallpaperSnapshot, wallpaper_from_path  # type: ignore[import-untyped]

from substitute.infrastructure.appearance.mica_wallpaper_provider import (
    WatchedWallpaperProvider,
)
from substitute.presentation.shell.window_backdrop import WindowBackdrop
from substitute.presentation.shell.portable_mica_surface import (
    MicaTheme,
    PortableMicaSurface,
)
import substitute.presentation.shell.portable_mica_surface as surface_module
from tests.support.qt.lifecycle import destroy_qt_object, ensure_qt_application
from tests.support.qt.semantic_wait import wait_for_qt_condition


@pytest.fixture(scope="module", autouse=True)
def portable_application() -> Iterator[QApplication]:
    """Keep Qt native wrappers alive throughout the publication scenarios."""

    application = ensure_qt_application()
    yield application


def _source(path: Path) -> None:
    """Write a small material source for the real discovery boundary."""

    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(path))


@pytest.mark.parametrize("invalidate_before_finish", (False, True))
def test_material_is_published_only_after_every_display_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalidate_before_finish: bool
) -> None:
    """Avoid mixed-source display textures or claiming an incomplete material set."""

    source = tmp_path / "red.png"
    _source(source)
    monkeypatch.setenv("SUGARSUBSTITUTE_MICA_WALLPAPER", str(source))
    bindings = tuple(
        ScreenBinding(name, Rect(x, 0, 100, 100), name, Rect(x, 0, 100, 100), 1.0)
        for name, x in (("left", 0), ("right", 100))
    )
    controllers: list[ControlledController] = []

    class ControlledController(QObject):
        """Fake only the external renderer's per-screen completion boundary."""

        material_ready = Signal(str, QPixmap, float)
        generation_started = Signal(int)
        generation_finished = Signal(int)
        error = Signal(str)

        def __init__(
            self,
            wallpaper: WallpaperSnapshot,
            selected: tuple[ScreenBinding, ...],
            theme: MicaTheme,
            *,
            parent: QObject,
        ) -> None:
            """Retain the immutable display contract used by the real presenter."""

            super().__init__(parent)
            self.bindings = selected
            self.fallback_color = (32, 32, 32)
            controllers.append(self)

        def update_wallpaper(self, wallpaper: WallpaperSnapshot) -> bool:
            """Accept repeated successful metadata without changing generation."""

            return True

        def refresh(self) -> None:
            """Start generation while leaving completion under test control."""

            self.generation_started.emit(1)

    monkeypatch.setattr(
        surface_module, "infer_qt_screen_bindings", lambda _screens: bindings
    )
    monkeypatch.setattr(surface_module, "MicaMaterialController", ControlledController)
    window = QWidget()
    window.resize(100, 100)
    surface = PortableMicaSurface(window, dark=True)
    try:
        window.show()
        wait_for_qt_condition(lambda: surface.generation_count == 1)
        controller = controllers[0]
        texture = QPixmap(25, 25)
        texture.fill(QColor("red"))
        controller.material_ready.emit(bindings[0].cache_key, texture, 1.0)
        assert surface.ready is False
        controller.material_ready.emit(bindings[1].cache_key, texture, 1.0)
        assert surface.ready is False
        if invalidate_before_finish:
            window.hide()
            screen = window.screen()
            screen.logicalDotsPerInchChanged.emit(screen.logicalDotsPerInch())
            assert surface.ready is False
        controller.generation_finished.emit(1)
        assert surface.ready is not invalidate_before_finish
        assert len(surface.material_cache_signature) == 2
    finally:
        surface.dispose()
        window.close()
        destroy_qt_object(window)


def test_removed_display_wrapper_does_not_block_next_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recover after Qt deletes a display before the deferred topology rebuild."""

    source = tmp_path / "red.png"
    _source(source)
    monkeypatch.setenv("SUGARSUBSTITUTE_MICA_WALLPAPER", str(source))
    actual_screens = QGuiApplication.screens()

    class Display(QObject):
        """Model the QObject lifetime of a removable native display."""

        geometryChanged = Signal(QRect)
        logicalDotsPerInchChanged = Signal(float)
        physicalDotsPerInchChanged = Signal(float)

        def geometry(self) -> QRect:
            """Expose one bounded display rectangle."""

            return QRect(0, 0, 200, 200)

        def devicePixelRatio(self) -> float:
            """Use logical and physical pixels at the same scale."""

            return 1.0

        def name(self) -> str:
            """Return stable discovery identity for the removable display."""

            return "removable"

    display = Display()
    current = [cast(QScreen, display)]
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: current))
    window = QWidget()
    window.resize(100, 100)
    surface = PortableMicaSurface(window, dark=True)
    try:
        window.show()
        wait_for_qt_condition(lambda: surface.ready, timeout_ms=5000)
        previous = surface.generation_count
        destroy_qt_object(display)
        current = actual_screens
        application = QGuiApplication.instance()
        assert isinstance(application, QGuiApplication)
        application.screenAdded.emit(actual_screens[0])
        wait_for_qt_condition(
            lambda: surface.generation_count > previous and surface.ready,
            timeout_ms=5000,
        )
        assert surface.last_error is None
    finally:
        surface.dispose()
        window.close()
        destroy_qt_object(window)


def test_rejected_new_source_cannot_republish_previous_wallpaper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep Plain when a new source disappears after discovery but before acceptance."""

    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _source(first)
    _source(second)
    selected = wallpaper_from_path(first)
    missing = wallpaper_from_path(second)
    calls: list[WallpaperSnapshot] = []

    class RacingProvider(WatchedWallpaperProvider):
        """Return a snapshot whose file may disappear before its queued delivery."""

        def discover(self, bindings: tuple[ScreenBinding, ...]) -> WallpaperSnapshot:
            """Publish the test-controlled result of the external discovery query."""

            calls.append(selected)
            return selected

    monkeypatch.setattr(
        surface_module, "create_mica_wallpaper_provider", lambda: RacingProvider(first)
    )
    window = QWidget()
    window.resize(100, 100)
    owner = WindowBackdrop(window, platform_name="linux")
    owner.apply("mica_alt", dark=True)
    surface = window.findChild(PortableMicaSurface)
    assert surface is not None
    try:
        window.show()
        wait_for_qt_condition(lambda: surface.ready, timeout_ms=5000)
        previous = surface.generation_count
        selected = missing
        second.unlink()
        wait_for_qt_condition(
            lambda: (
                len(calls) >= 2
                and (
                    surface.last_error is not None
                    or surface.generation_count > previous
                )
            ),
            timeout_ms=5000,
        )
        assert surface.last_error is not None
        assert surface.ready is False
        assert surface.generation_count == previous
        assert owner.provider_name == "plain"
        assert window.grab().toImage().pixelColor(50, 50).name() == "#202020"
    finally:
        owner.apply(None, dark=True)
        window.close()
        destroy_qt_object(window)
