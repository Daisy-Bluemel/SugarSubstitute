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

"""Compare rendered display and editable weight glyph placement."""

from __future__ import annotations

from math import ceil

import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from substitute.presentation.editor.prompt_editor.core.projection.tokens import (
    PromptProjectionToken,
    PromptProjectionTokenKind,
)
from substitute.presentation.editor.prompt_editor.projection.surface import (
    PromptProjectionSurface,
)
from tests.support.prompt_editor.projection_engine_support import surface_for
from tests.presentation.editor.prompt_editor.interactions.weight.mounting import (
    effective_token_for_paint,
)
from tests.support.prompt_editor.real_shell.scenario import (
    PromptEditorRealShellScenario,
)


def _render_viewport(
    viewport: QWidget, *, device_pixel_ratio: float, children: bool = True
) -> QImage:
    """Capture production viewport paint at the requested display scale."""

    image = QImage(
        QSize(
            ceil(viewport.width() * device_pixel_ratio),
            ceil(viewport.height() * device_pixel_ratio),
        ),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.setDevicePixelRatio(device_pixel_ratio)
    image.fill(QColor("transparent"))
    painter = QPainter(image)
    try:
        flags = QWidget.RenderFlag.DrawWindowBackground
        if children:
            flags |= QWidget.RenderFlag.DrawChildren
        viewport.render(painter, QPoint(), QRegion(), flags)
    finally:
        painter.end()
    return image


def _glyph_pixels(image: QImage) -> set[tuple[int, int]]:
    """Find marker pixels across the entire viewport, including displaced glyphs."""

    return {
        (x, y)
        for x in range(image.width())
        for y in range(image.height())
        if (color := image.pixelColor(x, y)).red() > 160
        and color.blue() > 160
        and color.green() < 100
    }


def _glyph_bounds(pixels: set[tuple[int, int]]) -> QRect:
    """Require visible target ink before comparing its complete bounds."""

    assert len(pixels) > 10, len(pixels)
    return QRect(
        min(x for x, _ in pixels),
        min(y for _, y in pixels),
        max(x for x, _ in pixels) - min(x for x, _ in pixels) + 1,
        max(y for _, y in pixels) - min(y for _, y in pixels) + 1,
    )


def _native_glyph_bounds(
    surface: PromptProjectionSurface, *, device_pixel_ratio: float
) -> QRect:
    """Isolate the selected native glyph without a caret or other marker text."""

    native_input = surface.exact_weight_editor
    assert native_input.selectedText() == native_input.text()
    background = _render_viewport(
        surface.viewport(), device_pixel_ratio=device_pixel_ratio, children=False
    )
    assert not _glyph_pixels(background), "non-target projection ink uses the marker"
    return _glyph_bounds(
        _glyph_pixels(
            _render_viewport(surface.viewport(), device_pixel_ratio=device_pixel_ratio)
        )
    )


def _assert_aligned(painted: QRect, editable: QRect, device_pixel_ratio: float) -> None:
    """Compare complete target bounds with the original raster tolerances."""

    tolerance = ceil(device_pixel_ratio)
    assert abs(editable.left() - painted.left()) <= tolerance, (painted, editable)
    assert abs(editable.top() - painted.top()) <= tolerance, (painted, editable)
    assert abs(editable.right() - painted.right()) <= tolerance + 1, (painted, editable)
    assert abs(editable.bottom() - painted.bottom()) <= tolerance, (painted, editable)


def _start_marked_weight(
    scenario: PromptEditorRealShellScenario,
    surface: PromptProjectionSurface,
    token: PromptProjectionToken,
    device_pixel_ratio: float,
) -> QRect:
    """Isolate the displayed weight while holding decoration and focus state fixed."""

    sentinel = scenario.shell.focus_sentinel
    sentinel.setFocus(Qt.FocusReason.OtherFocusReason)
    scenario.wait_until(
        lambda: QApplication.focusWidget() is sentinel,
        description="source caret absent from weight reference",
    )
    if token.kind is PromptProjectionTokenKind.EMPHASIS:
        surface.emphasis.set_overlay_accent_range(
            (token.source_start, token.source_end)
        )
    palette = QPalette(surface.palette())
    palette.setColor(QPalette.ColorRole.Text, QColor(255, 0, 255))
    surface.setPalette(palette)
    surface.refresh_geometry()
    weight_rect = surface.token_weight_edit_rect(token)
    assert weight_rect is not None
    before_flags = tuple(
        (item.token_id, effective_token_for_paint(surface, item).decoration_accented)
        for item in surface.projection_document().tokens
    )
    before = _render_viewport(
        surface.viewport(), device_pixel_ratio=device_pixel_ratio, children=False
    )
    native_input = surface.exact_weight_editor
    native_input.start(token)
    scenario.wait_for_queued_delivery()
    editing_token = native_input.token()
    assert editing_token is not None
    assert surface.token_weight_edit_rect(editing_token) == weight_rect
    assert (
        tuple(
            (
                item.token_id,
                effective_token_for_paint(surface, item).decoration_accented,
            )
            for item in surface.projection_document().tokens
        )
        == before_flags
    )
    background = _render_viewport(
        surface.viewport(), device_pixel_ratio=device_pixel_ratio, children=False
    )
    displayed_pixels = _glyph_pixels(before)
    background_pixels = _glyph_pixels(background)
    assert not background_pixels - displayed_pixels, "surrounding projection moved"
    painted = _glyph_bounds(displayed_pixels - background_pixels)

    neutral_palette = QPalette(palette)
    neutral_palette.setColor(QPalette.ColorRole.Text, QColor(32, 32, 32))
    surface.setPalette(neutral_palette)
    surface.refresh_geometry()
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 0, 255))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("transparent"))
    native_input.setPalette(palette)
    native_input.selectAll()
    return painted


@pytest.mark.parametrize(
    ("source", "value_text"),
    [
        ("(red cube:1.25), portrait", "1.25"),
        ("((atmospheric:2.80) perspective:1.15), portrait", "2.80"),
        ("<lora:detail:1.25>, portrait", "1.25"),
    ],
    ids=["emphasis", "nested-emphasis", "lora"],
)
@pytest.mark.parametrize("device_pixel_ratio", [1.0, 1.5, 2.0])
def test_weight_raster_alignment(
    real_shell_scenario: PromptEditorRealShellScenario,
    source: str,
    value_text: str,
    device_pixel_ratio: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Place painted and native-edit weight glyphs in the same viewport pixels."""

    field = real_shell_scenario.workflows.add_prompt_workflow(initial_text=source)
    real_shell_scenario.input.focus_editor(field)
    assert not field.editor.textCursor().hasSelection()
    surface = surface_for(field.editor)
    token = next(
        item
        for item in surface.projection_document().tokens
        if item.value_text == value_text
    )
    painted = _start_marked_weight(
        real_shell_scenario, surface, token, device_pixel_ratio
    )
    weight_rect = surface.token_weight_edit_rect(token)
    assert weight_rect is not None
    native_input = surface.exact_weight_editor
    editable = _native_glyph_bounds(surface, device_pixel_ratio=device_pixel_ratio)
    _assert_aligned(painted, editable, device_pixel_ratio)

    refresh_geometry = native_input.refresh_geometry
    for displacement in (-ceil(weight_rect.width()) - 8, ceil(weight_rect.width()) + 8):
        with monkeypatch.context() as displaced:

            def displace_native_input() -> None:
                """Inject wrong native placement after every real geometry refresh."""

                refresh_geometry()
                native_input.move(native_input.x() + displacement, native_input.y())

            displaced.setattr(native_input, "refresh_geometry", displace_native_input)
            native_input.refresh_geometry()
            assert surface.viewport().rect().contains(native_input.geometry())
            displaced_glyph = _native_glyph_bounds(
                surface, device_pixel_ratio=device_pixel_ratio
            )
            assert not displaced_glyph.intersects(painted)
            with pytest.raises(AssertionError):
                _assert_aligned(painted, displaced_glyph, device_pixel_ratio)
    native_input.refresh_geometry()
    _assert_aligned(
        painted,
        _native_glyph_bounds(surface, device_pixel_ratio=device_pixel_ratio),
        device_pixel_ratio,
    )

    QTest.keyClicks(native_input, "0.95")
    native_input.selectAll()
    real_shell_scenario.wait_for_queued_delivery()
    updated_glyph = _native_glyph_bounds(surface, device_pixel_ratio=device_pixel_ratio)

    assert native_input.text() == "0.95"
    assert field.editor.toPlainText() == source
    QTest.keyClick(native_input, Qt.Key.Key_Return)
    assert field.editor.toPlainText() == source.replace(value_text, "0.95", 1)
    updated_token = next(
        item
        for item in surface.projection_document().tokens
        if item.value_text == "0.95"
    )
    updated_painted = _start_marked_weight(
        real_shell_scenario, surface, updated_token, device_pixel_ratio
    )
    _assert_aligned(updated_painted, updated_glyph, device_pixel_ratio)
