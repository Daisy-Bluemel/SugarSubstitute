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

"""Verify native weight placement independently of platform layout fractions."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QFontMetricsF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from substitute.application.prompt_editor.document.service import PromptDocumentService
from substitute.application.prompt_editor.projection.syntax_service import (
    PromptSyntaxService,
)
from substitute.presentation.editor.prompt_editor.core.projection.document import (
    PromptProjectionDisplayMode,
    PromptProjectionDocument,
)
from substitute.presentation.editor.prompt_editor.core.projection.tokens import (
    PromptProjectionToken,
)
from substitute.presentation.editor.prompt_editor.projection.builder import (
    PromptProjectionBuilder,
)
from substitute.presentation.editor.prompt_editor.projection.exact_weight_editor import (
    PromptExactWeightEditor,
)
from substitute.presentation.editor.prompt_editor.projection.inline_renderer_typography import (
    inline_weight_font,
)
from substitute.presentation.editor.prompt_editor.projection.session import (
    PromptProjectionSession,
)
from tests.support.prompt_editor.autocomplete_support import (
    EmptyPromptWildcardCatalogGateway,
    prompt_syntax_profile,
)
from tests.support.qt.lifecycle import destroy_widget_roots, ensure_qt_application
from tests.support.qt.semantic_wait import wait_for_qt_condition


class _PreparedWeightHost(QWidget):
    """Supply prepared geometry while keeping projection and native editing real."""

    def __init__(self) -> None:
        """Create an emphasis projection with caller-controlled viewport geometry."""

        super().__init__()
        self._session = PromptProjectionSession()
        self._source = PromptDocumentService().build_document_view("(cat:1.25)")
        self._plan = PromptSyntaxService(
            EmptyPromptWildcardCatalogGateway()
        ).build_render_plan(self._source, prompt_syntax_profile("emphasis"))
        self._builder = PromptProjectionBuilder()
        self._document = PromptProjectionDocument.empty()
        self.rebuild_projection()
        metrics = QFontMetricsF(inline_weight_font(self.font()))
        self.slot = QRectF(
            104.90625, 30.25, metrics.horizontalAdvance("1.25"), metrics.height()
        )
        self.input = PromptExactWeightEditor(
            self, rebuild_projection=self.rebuild_projection
        )
        self.resize(360, 140)

    def viewport(self) -> QWidget:
        """Return the real parent receiving resize and paint events."""

        return self

    def projection_document(self) -> PromptProjectionDocument:
        """Return the current source-backed semantic projection."""

        return self._document

    def token_weight_edit_rect(self, token: PromptProjectionToken) -> QRectF:
        """Supply the prepared slot at the native geometry adapter's boundary."""

        assert token.token_id == self._document.tokens[0].token_id
        return QRectF(self.slot)

    def rebuild_projection(self) -> None:
        """Publish exact-edit state through the production projection builder."""

        self._document = self._builder.build_projection(
            self._source,
            self._plan,
            display_mode=PromptProjectionDisplayMode.PROJECTED,
            session=self._session,
        )


@pytest.fixture
def weight_host() -> Iterator[_PreparedWeightHost]:
    """Own one native input and its prepared-geometry host per test."""

    ensure_qt_application()
    host = _PreparedWeightHost()
    host.show()
    host.activateWindow()
    try:
        yield host
    finally:
        destroy_widget_roots([host])


def _cursor_origin(editor: PromptExactWeightEditor) -> float:
    """Read the native caret center in viewport coordinates."""

    rect = editor.inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle)
    assert isinstance(rect, QRect)
    return editor.x() + rect.left() + rect.width() / 2.0


@pytest.mark.parametrize(
    "left", [104.25, 104.49, 104.5, 104.51, 104.75, 104.90625, 0.0, -2.49, -2.5, -2.51]
)
def test_native_weight_uses_nearest_horizontal_origin(
    weight_host: _PreparedWeightHost, left: float
) -> None:
    """Round either side of the midpoint without losing padded native capacity."""

    weight_host.slot.moveLeft(left)
    padded = weight_host.slot.adjusted(-2, -1, 2, 1).toAlignedRect()
    editor = weight_host.input
    editor.start(weight_host.projection_document().tokens[0])
    editor.setCursorPosition(0)

    assert editor.x() + 2 == pytest.approx(weight_host.slot.left(), abs=0.5)
    assert editor.geometry().top() == padded.top()
    assert editor.geometry().size() == padded.size()
    start_origin = _cursor_origin(editor)
    editor.setCursorPosition(len(editor.text()))
    assert _cursor_origin(editor) - start_origin == pytest.approx(
        QFontMetricsF(editor.font()).horizontalAdvance(editor.text()), abs=0.75
    )
    assert weight_host.projection_document().source_text == "(cat:1.25)"


def test_native_weight_refresh_preserves_edits_selection_and_undo(
    weight_host: _PreparedWeightHost,
) -> None:
    """Follow changed slots and viewport sizes without resetting native edit state."""

    editor = weight_host.input
    editor.start(weight_host.projection_document().tokens[0])
    wait_for_qt_condition(editor.hasFocus, description="native weight focus")
    QTest.keyClicks(editor, "123.95")
    weight_host.slot.setWidth(
        QFontMetricsF(editor.font()).horizontalAdvance(editor.text())
    )
    editor.setSelection(1, 3)
    selection = (
        editor.cursorPosition(),
        editor.selectionStart(),
        editor.selectedText(),
    )
    for left, width in ((110.49, 380), (120.51, 420), (104.90625, 360)):
        weight_host.slot.moveLeft(left)
        weight_host.resize(width, 150)
        editor.refresh_geometry()
        editor.refresh_geometry()
        assert editor.text() == "123.95"
        assert (
            editor.cursorPosition(),
            editor.selectionStart(),
            editor.selectedText(),
        ) == selection
        assert editor.hasFocus()
        assert (
            editor.geometry().size()
            == weight_host.slot.adjusted(-2, -1, 2, 1).toAlignedRect().size()
        )
    editor.setCursorPosition(0)
    assert editor.x() + 2 == pytest.approx(weight_host.slot.left(), abs=0.75)
    editor.undo()
    assert editor.text() == "1.25"
    editor.redo()
    assert editor.text() == "123.95"
    assert weight_host.projection_document().source_text == "(cat:1.25)"
