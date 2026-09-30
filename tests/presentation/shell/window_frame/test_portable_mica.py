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

"""Verify the shell paints real wallpaper material and restores plain fallback."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import threading

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget
import pytest
from cutemica.wallpaper import WallpaperSnapshot, wallpaper_from_path  # type: ignore[import-untyped]

from substitute.presentation.shell.portable_mica_surface import PortableMicaSurface
from substitute.presentation.shell.window_backdrop import WindowBackdrop
from substitute.presentation.shell.window_effects import ShellBackdropMode
from substitute.presentation.shell.window_frame import SubstituteWindowFrame
import substitute.presentation.shell.window_frame as window_frame
from tests.support.qt.lifecycle import destroy_qt_object, ensure_qt_application
from tests.support.qt.semantic_wait import (
    wait_for_qt_condition,
    wait_for_queued_qt_turn,
)


@pytest.fixture(scope="module", autouse=True)
def portable_application() -> Iterator[QApplication]:
    """Retain one Qt application throughout this material integration module."""

    application = ensure_qt_application()
    yield application


@pytest.mark.platforms("linux")
def test_linux_shell_paints_wallpaper_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generate actual CuteMica pixels instead of accepting a no-op native call."""

    wallpaper = tmp_path / "red.png"
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor("#ff0000"))
    assert image.save(str(wallpaper))
    monkeypatch.setenv("SUGARSUBSTITUTE_MICA_WALLPAPER", str(wallpaper))
    monkeypatch.setattr(window_frame, "isDarkTheme", lambda: True)
    window = SubstituteWindowFrame(backdrop_mode=ShellBackdropMode.MICA_ALT)
    window.resize(240, 180)
    try:
        window.show()

        def has_red_material() -> bool:
            """Detect the red source through an otherwise empty shell body."""

            pixel = window.grab().toImage().pixelColor(100, 100)
            return bool(pixel.red() > pixel.green() + 5)

        wait_for_qt_condition(has_red_material, timeout_ms=5000)
    finally:
        window.close()
        destroy_qt_object(window)


class InactiveMaterialWindow(QWidget):
    """Reproduce the inactive Qt state reported during a native X11 WM move."""

    def isActiveWindow(self) -> bool:
        """Keep activation false independently of the offscreen platform plugin."""

        return False


def _wallpaper(path: Path, color: str) -> None:
    """Write one small opaque source image without image-processing dependencies."""

    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path))


def test_inactive_movement_uses_cached_geometry_slices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep colored material during deactivation and move it without regeneration."""

    wallpaper = tmp_path / "gradient.png"
    image = QImage(800, 600, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    gradient = QLinearGradient(0, 0, 800, 0)
    gradient.setColorAt(0, QColor("#ff0000"))
    gradient.setColorAt(1, QColor("#0000ff"))
    painter.fillRect(image.rect(), gradient)
    painter.end()
    assert image.save(str(wallpaper))
    monkeypatch.setenv("SUGARSUBSTITUTE_MICA_WALLPAPER", str(wallpaper))
    window = InactiveMaterialWindow()
    window.resize(180, 140)
    window.move(0, 0)
    surface = PortableMicaSurface(window, dark=True)
    try:
        window.show()
        wait_for_qt_condition(lambda: surface.ready, timeout_ms=5000)
        before = window.grab().toImage().pixelColor(80, 80)
        identity = surface.material_cache_signature
        generations = surface.generation_count
        window.move(300, 0)
        QApplication.sendEvent(window, QEvent(QEvent.Type.ScreenChangeInternal))
        QApplication.sendEvent(window, QEvent(QEvent.Type.DevicePixelRatioChange))
        after = window.grab().toImage().pixelColor(80, 80)
        assert window.isActiveWindow() is False
        assert before != after
        assert before.red() > before.blue()
        assert after.blue() > before.blue()
        assert surface.material_cache_signature == identity
        assert surface.generation_count == generations
    finally:
        surface.dispose()
        window.close()
        destroy_qt_object(window)


def test_switch_to_plain_releases_material_and_paints_opaque_theme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remove actual generated pixels immediately when Plain is requested."""

    source = tmp_path / "red.png"
    _wallpaper(source, "#ff0000")
    monkeypatch.setenv("SUGARSUBSTITUTE_MICA_WALLPAPER", str(source))
    window = QWidget()
    window.resize(180, 140)
    owner = WindowBackdrop(window, platform_name="linux")
    owner.apply("mica_alt", dark=True)
    try:
        window.show()
        wait_for_qt_condition(
            lambda: owner.provider_name == "cutemica", timeout_ms=5000
        )
        owner.apply(None, dark=True)
        assert owner.provider_name == "plain"
        assert window.grab().toImage().pixelColor(80, 80).name() == "#202020"
        owner.apply(None, dark=False)
        assert window.grab().toImage().pixelColor(80, 80).name() == "#f8f8f8"
    finally:
        owner.apply(None, dark=False)
        window.close()
        destroy_qt_object(window)


def test_failed_theme_regeneration_exposes_new_theme_plain_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never leave dark pixels behind light controls when new material fails."""

    source = tmp_path / "red.png"
    _wallpaper(source, "#ff0000")
    monkeypatch.setenv("SUGARSUBSTITUTE_MICA_WALLPAPER", str(source))
    window = QWidget()
    window.resize(180, 140)
    owner = WindowBackdrop(window, platform_name="linux")
    owner.apply("mica_alt", dark=True)
    try:
        window.show()
        wait_for_qt_condition(
            lambda: owner.provider_name == "cutemica", timeout_ms=5000
        )
        source.write_bytes(b"corrupt image")
        owner.apply("mica_alt", dark=False)
        surface = window.findChild(PortableMicaSurface)
        assert surface is not None
        wait_for_qt_condition(lambda: surface.last_error is not None, timeout_ms=5000)
        assert owner.provider_name == "plain"
        assert surface.ready is False
        assert window.grab().toImage().pixelColor(80, 80).name() == "#f8f8f8"
    finally:
        owner.apply(None, dark=False)
        window.close()
        destroy_qt_object(window)


def test_disappearing_source_is_reported_at_qt_callback_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contain metadata races during both theme refresh and source publication."""

    import sys
    from cutemica.providers.qt_screens import infer_qt_screen_bindings  # type: ignore[import-untyped]
    from substitute.presentation.shell.mica_material_controller import (
        MicaMaterialController,
    )
    from substitute.presentation.shell.portable_mica_surface import MicaTheme

    source = tmp_path / "red.png"
    _wallpaper(source, "#ff0000")
    owner = QObject()
    theme = MicaTheme(True, owner)
    controller = MicaMaterialController(
        wallpaper_from_path(source),
        infer_qt_screen_bindings(QApplication.screens()),
        theme,
        parent=owner,
    )
    errors = QSignalSpy(controller.error)
    callback_errors: list[object] = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: callback_errors.append(args))
    snapshot = controller.wallpaper
    source.unlink()
    try:
        theme.theme_changed.emit(theme.resolved)
        controller.set_wallpaper(snapshot)
        assert errors.count() == 2
        assert callback_errors == []
    finally:
        destroy_qt_object(owner)


@pytest.mark.parametrize("transient_failure", (False, True))
def test_discovery_is_off_gui_thread_and_recovers_same_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transient_failure: bool
) -> None:
    """Recover unchanged metadata after a failed poll without blocking Qt discovery."""

    from cutemica.geometry import ScreenBinding  # type: ignore[import-untyped]
    from substitute.infrastructure.appearance.mica_wallpaper_provider import (
        WatchedWallpaperProvider,
    )
    import substitute.presentation.shell.portable_mica_surface as surface_module

    source = tmp_path / "red.png"
    _wallpaper(source, "#ff0000")
    thread_ids: list[int] = []

    class IntermittentProvider(WatchedWallpaperProvider):
        """Fail one metadata observation at the external provider boundary."""

        def discover(self, bindings: tuple[ScreenBinding, ...]) -> WallpaperSnapshot:
            """Record discovery affinity and return the same unchanged source."""

            thread_ids.append(threading.get_ident())
            if transient_failure and len(thread_ids) == 2:
                raise RuntimeError("temporary provider failure")
            return super().discover(bindings)

    provider = IntermittentProvider(source)
    monkeypatch.setattr(
        surface_module, "create_mica_wallpaper_provider", lambda: provider
    )
    window = QWidget()
    window.resize(180, 140)
    surface = PortableMicaSurface(window, dark=True)
    try:
        window.show()
        wait_for_qt_condition(lambda: surface.ready, timeout_ms=5000)
        if transient_failure:
            wait_for_qt_condition(
                lambda: surface.last_error is not None, timeout_ms=5000
            )
            assert surface.ready is False
            wait_for_qt_condition(
                lambda: len(thread_ids) >= 3 and surface.ready, timeout_ms=5000
            )
        assert all(identity != threading.get_ident() for identity in thread_ids)
    finally:
        surface.dispose()
        window.close()
        destroy_qt_object(window)


def test_hidden_display_change_rebuilds_before_restored_presentation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain display invalidation when its queued rebuild runs while hidden."""

    source = tmp_path / "red.png"
    _wallpaper(source, "#ff0000")
    monkeypatch.setenv("SUGARSUBSTITUTE_MICA_WALLPAPER", str(source))
    window = QWidget()
    window.resize(180, 140)
    surface = PortableMicaSurface(window, dark=True)
    try:
        window.show()
        wait_for_qt_condition(lambda: surface.ready, timeout_ms=5000)
        previous = surface.generation_count
        window.hide()
        screen = window.screen()
        screen.logicalDotsPerInchChanged.emit(screen.logicalDotsPerInch())
        assert surface.ready is False
        wait_for_queued_qt_turn()
        window.show()
        wait_for_qt_condition(
            lambda: surface.generation_count > previous and surface.ready,
            timeout_ms=5000,
        )
    finally:
        surface.dispose()
        window.close()
        destroy_qt_object(window)
