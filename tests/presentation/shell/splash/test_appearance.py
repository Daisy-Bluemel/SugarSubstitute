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

"""Verify rendered splash contrast and the composed Linux corner shape."""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QEnterEvent, QMouseEvent
from PySide6.QtWidgets import QAbstractButton
import pytest

from substitute.presentation.shell.splash_window import SplashWindow
from tests.support.qt.lifecycle import destroy_qt_object


@pytest.mark.parametrize("theme_mode", ["dark", "light"])
@pytest.mark.parametrize("button_state", ["normal", "hover", "pressed"])
def test_splash_renders_themed_background_and_legible_close_control(
    theme_mode: str, button_state: str
) -> None:
    """Paint real chrome at scale one before deferred material or animation runs."""

    splash = SplashWindow(
        theme_mode=theme_mode,
        backdrop_mode=None,
        defer_animation_until_first_paint=True,
    )
    try:
        button = cast(QAbstractButton, splash.titleBar.closeBtn)
        QCoreApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
        center = QPointF(button.rect().center())
        if button_state in {"hover", "pressed"}:
            QCoreApplication.sendEvent(button, QEnterEvent(center, center, center))
        if button_state == "pressed":
            QCoreApplication.sendEvent(
                button,
                QMouseEvent(
                    QEvent.Type.MouseButtonPress,
                    center,
                    QPointF(button.mapToGlobal(center.toPoint())),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )

        rendered = splash.grab().toImage()
        assert rendered.devicePixelRatio() == 1.0
        base = QColor("#202020" if theme_mode == "dark" else "#f8f8f8")
        assert rendered.pixelColor(20, 50) == base
        offset = button.mapTo(splash, QPoint(0, 0))
        expected_button_background = {
            "normal": base,
            "hover": QColor("#e81123"),
            "pressed": QColor("#f1707a"),
        }[button_state]
        assert rendered.pixelColor(offset + QPoint(8, 16)) == expected_button_background
        glyph_pixels = [
            rendered.pixelColor(offset + QPoint(x, y))
            for x in range(17, 30)
            for y in range(10, 23)
        ]
        if theme_mode == "light" and button_state == "normal":
            assert min(color.lightness() for color in glyph_pixels) < 32
        else:
            assert max(color.lightness() for color in glyph_pixels) > 230
    finally:
        destroy_qt_object(splash)


@pytest.mark.platforms("linux")
def test_linux_splash_composes_a_rounded_native_mask() -> None:
    """Exclude the four restored-window corners while retaining edge centers."""

    splash = SplashWindow(backdrop_mode=None, defer_animation_until_first_paint=True)
    try:
        mask = splash.mask()
        assert not mask.isEmpty()
        for point in (
            splash.rect().topLeft(),
            splash.rect().topRight(),
            splash.rect().bottomLeft(),
            splash.rect().bottomRight(),
        ):
            assert not mask.contains(point)
        assert mask.contains(QPoint(splash.width() // 2, 0))
        assert mask.contains(splash.rect().center())
    finally:
        destroy_qt_object(splash)
