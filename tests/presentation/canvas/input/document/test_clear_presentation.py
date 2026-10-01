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

"""Prove empty Input routes remove visible pixels while retaining document data."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4
from zipfile import ZipFile

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from cutecanvas import CuteCanvas
import pytest

from tests.support.cutecanvas.input_document import InputDocumentFactory
from tests.support.qt.semantic_wait import wait_for_qt_condition


def _image(color: QColor) -> QImage:
    """Create small distinct opaque sources for a real rendered route transition."""

    image = QImage(64, 48, QImage.Format.Format_ARGB32)
    image.fill(color)
    return image


def _archive_members(path: Path) -> dict[str, bytes]:
    """Compare persisted authority independently of ZIP container timestamps."""

    with ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.mark.parametrize("with_mask", [False, True])
def test_clear_route_blanks_view_and_retains_complete_editable_document(
    with_mask: bool,
    input_document_factory: InputDocumentFactory,
    qt_application_owner: QApplication,
    tmp_path: Path,
) -> None:
    """Clear real painted content repeatedly without losing sources or mask bytes."""

    _ = qt_application_owner
    document = input_document_factory()
    canvas = document.canvas
    canvas.resize(320, 240)
    canvas.show()
    blank = canvas.grab().toImage()
    center = QPoint(160, 120)
    red = QColor(222, 11, 21)
    blue = QColor(11, 21, 222)
    first_id, second_id = uuid4(), uuid4()
    document.ensure_image_cached(first_id, _image(red), None)
    document.ensure_image_cached(second_id, _image(blue), None)
    assert document.set_current_image_id(first_id)
    mask_id: UUID | None = None
    mask_before: QImage | None = None
    if with_mask:
        mask_id = document.create_blank_mask(first_id, QSize(64, 48))
        assert mask_id is not None
        coverage = QImage(64, 48, QImage.Format.Format_Grayscale8)
        coverage.fill(0)
        painter = QPainter(coverage)
        painter.fillRect(0, 0, 16, 8, QColor("white"))
        painter.end()
        assert canvas.replaceMaskImage(mask_id, coverage)
        exported = document.export_mask_image(mask_id)
        assert exported is not None
        mask_before = exported.copy()
        assert mask_before.pixelColor(0, 0).red() == 255
        assert mask_before.pixelColor(32, 24).red() == 0

    assert document.set_current_image_id(second_id)
    canvas.setZoomFit()
    wait_for_qt_condition(
        lambda: canvas.grab().toImage().pixelColor(center) == blue,
        description="the second cached image is visible",
    )
    assert document.set_current_image_id(first_id)
    canvas.setZoomFit()
    wait_for_qt_condition(
        lambda: canvas.grab().toImage().pixelColor(center) == red,
        description="the first cached image is visible",
    )
    before_path = tmp_path / "before.cute"
    document.editable_persistence.save_editable_document(before_path)
    authority_before = _archive_members(before_path)

    for _ in range(2):
        assert document.set_current_image_id(None)
        assert document.current_image_id() is None
        wait_for_qt_condition(
            lambda: canvas.grab().toImage() == blank,
            description="an empty Input route paints its original blank surface",
        )
        assert set(canvas.compositionIDs()) == {first_id, second_id}
        assert document.contains(first_id) and document.contains(second_id)
        if mask_id is not None:
            assert document.export_mask_image(mask_id) == mask_before
        after_path = tmp_path / "after.cute"
        document.editable_persistence.save_editable_document(after_path)
        assert _archive_members(after_path) == authority_before

    for image_id, expected in ((second_id, blue), (first_id, red)):
        assert document.set_current_image_id(image_id)
        canvas.setZoomFit()
        wait_for_qt_condition(
            lambda: canvas.grab().toImage().pixelColor(center) == expected,
            description="a retained image reopens with its original pixels",
        )
    if mask_id is not None:
        assert document.export_mask_image(mask_id) == mask_before


def test_clear_route_publishes_empty_tool_context(
    input_document_factory: InputDocumentFactory,
    qt_application_owner: QApplication,
) -> None:
    """Notify capability and option consumers when the visible image disappears."""

    _ = qt_application_owner
    document = input_document_factory()
    document.canvas.resize(320, 240)
    document.canvas.show()
    image_id = uuid4()
    document.ensure_image_cached(image_id, _image(QColor("red")), None)
    assert document.set_current_image_id(image_id)
    mask_id = document.create_blank_mask(image_id, QSize(64, 48))
    assert mask_id is not None
    assert document.set_active_mask_id(mask_id)
    wait_for_qt_condition(
        lambda: document.tool_context.snapshot.has_active_mask,
        description="the initial mask capabilities are published",
    )
    contexts: list[UUID | None] = []
    option_contexts: list[UUID | None] = []
    document.tool_context.changed.connect(
        lambda: contexts.append(document.tool_context.snapshot.image_id)
    )
    document.tool_options.editorContextChanged.connect(
        lambda: option_contexts.append(document.current_image_id())
    )
    wait_for_qt_condition(
        lambda: bool(contexts) and contexts[-1] == image_id,
        description="the initial active capabilities reach consumers",
    )

    assert document.set_current_image_id(None)

    wait_for_qt_condition(
        lambda: document.tool_context.snapshot.image_id is None,
        description="empty Input capability context",
    )
    wait_for_qt_condition(
        lambda: bool(contexts) and contexts[-1] is None,
        description="empty Input capability publication",
    )
    assert option_contexts and option_contexts[-1] is None
    assert not document.tool_context.snapshot.has_active_mask
    assert not document.tool_context.snapshot.has_pixel_selection
    assert document.tool_options.mask_layers() == ()
    assert document.active_mask_id() == mask_id

    assert document.set_current_image_id(image_id)
    wait_for_qt_condition(
        lambda: document.tool_context.snapshot.has_active_mask,
        description="reopening restores the retained selected mask capabilities",
    )
    assert document.active_mask_id() == mask_id


def test_clear_during_held_stroke_preserves_rollback_after_reopening(
    input_document_factory: InputDocumentFactory,
    qt_application_owner: QApplication,
    tmp_path: Path,
) -> None:
    """A cancelled pointer preview must never reappear over unchanged mask data."""

    _ = qt_application_owner
    document = input_document_factory()
    canvas = document.canvas
    canvas.resize(320, 240)
    canvas.show()
    blank = canvas.grab().toImage()
    image_id = uuid4()
    white = QColor("white")
    document.ensure_image_cached(image_id, _image(white), None)
    assert document.set_current_image_id(image_id)
    mask_id = document.create_blank_mask(image_id, QSize(64, 48))
    assert mask_id is not None
    assert document.set_active_mask_id(mask_id)
    assert document.set_canvas_operation(CuteCanvas.CONTROL_MODE_DRAW_BRUSH)
    canvas.setBrushSize(8)
    canvas.setZoomFit()
    center = QPoint(160, 120)
    wait_for_qt_condition(
        lambda: canvas.grab().toImage().pixelColor(center) == white,
        description="the source is visible before a brush gesture",
    )
    exported = document.export_mask_image(mask_id)
    assert exported is not None
    mask_before = exported.copy()
    history_before = canvas.getMaskUndoState(mask_id)
    assert history_before is not None
    before_path = tmp_path / "before.cute"
    document.editable_persistence.save_editable_document(before_path)
    authority_before = _archive_members(before_path)
    QTest.mousePress(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center
    )
    try:
        wait_for_qt_condition(
            lambda: canvas.grab().toImage().pixelColor(center) != white,
            description="the held brush gesture visibly paints provisional pixels",
        )
        assert document.set_current_image_id(None)
        wait_for_qt_condition(
            lambda: canvas.grab().toImage() == blank,
            description="clearing hides the held brush preview",
        )
        assert document.export_mask_image(mask_id) == mask_before
        assert canvas.getMaskUndoState(mask_id) == history_before
    finally:
        QTest.mouseRelease(
            canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center
        )
    assert canvas.grab().toImage() == blank
    assert document.export_mask_image(mask_id) == mask_before
    after_path = tmp_path / "after.cute"
    document.editable_persistence.save_editable_document(after_path)
    assert _archive_members(after_path) == authority_before

    assert document.set_current_image_id(image_id)
    canvas.setZoomFit()
    wait_for_qt_condition(
        lambda: canvas.grab().toImage().pixelColor(center) == white,
        description="reopening cannot resurrect cancelled brush preview pixels",
    )
    assert document.active_mask_id() == mask_id
    assert document.set_canvas_operation(CuteCanvas.CONTROL_MODE_DRAW_BRUSH)
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center
    )

    def fresh_stroke_committed() -> bool:
        """Require valid changed mask pixels, never accept a failed export."""

        exported_mask = document.export_mask_image(mask_id)
        return exported_mask is not None and exported_mask != mask_before

    wait_for_qt_condition(
        fresh_stroke_committed,
        description="a new brush gesture still commits after the cancelled one",
    )
