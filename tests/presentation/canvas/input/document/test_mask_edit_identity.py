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

"""Verify public durable mask events retain their owning Input image identity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from substitute.application.workflows.unsaved_work_service import UnsavedWorkService
from substitute.domain.workflow import WorkflowState
from substitute.presentation.canvas.input.input_document_catalog import (
    InputDocumentCatalog,
)
from substitute.presentation.canvas.input.input_editable_document_change_tracker import (
    InputEditableDocumentChangeTracker,
)
from substitute.presentation.canvas.input.input_editable_document_lifecycle import (
    InputEditableDocumentLifecycle,
)
from substitute.presentation.shell.input_mask_unsaved_work_observer import (
    InputMaskUnsavedWorkObserver,
)
from substitute.presentation.canvas.input.input_mask_edit_observer import (
    InputMaskEditObserver,
)
from tests.support.cutecanvas.input_document import InputDocumentFactory


def _pixels(value: int) -> QImage:
    """Create detached grayscale pixels for real document operations."""

    image = QImage(24, 16, QImage.Format.Format_Grayscale8)
    image.fill(value)
    return image


def test_mask_commit_undo_redo_and_pixel_delete_publish_image_identity(
    qt_application_owner: QApplication,
    input_document_factory: InputDocumentFactory,
) -> None:
    """Durable mask pixels publish identity while selection history stays quiet."""

    document = input_document_factory()
    edits: list[UUID] = []
    document.mask_edits.imageEdited.connect(edits.append)
    image_id = uuid4()
    document.ensure_image_cached(image_id, _pixels(0), None)
    mask_id = document.create_blank_mask(image_id, _pixels(0).size())
    assert mask_id is not None
    assert edits == []

    assert document.canvas.replaceMaskImage(mask_id, _pixels(255))
    assert document.canvas.undoSceneEdit()
    assert document.canvas.redoSceneEdit()
    assert edits == [image_id] * 3
    assert document.canvas.setPixelSelection(_pixels(255), QRect(0, 0, 24, 16))
    assert document.canvas.undoSceneEdit()
    assert document.canvas.redoSceneEdit()
    assert edits == [image_id] * 3
    mask = document.canvas.listMasksForComposition(image_id)[0]
    assert mask.scene_id is not None and mask.layer_id is not None
    assert document.canvas.setSelectedLayer(mask.scene_id, mask.layer_id)
    assert document.tool_options.clear_selected_pixels()
    assert edits == [image_id] * 4
    assert document.canvas.undoSceneEdit()
    assert document.canvas.redoSceneEdit()
    assert edits == [image_id] * 6


def test_inactive_mask_edit_keeps_original_image_identity(
    qt_application_owner: QApplication,
    input_document_factory: InputDocumentFactory,
) -> None:
    """An inactive mask's public mutation must never adopt the selected image."""

    document = input_document_factory()
    first_id, selected_id = uuid4(), uuid4()
    document.ensure_image_cached(first_id, _pixels(0), None)
    first_mask = document.create_blank_mask(first_id, _pixels(0).size())
    assert first_mask is not None
    document.ensure_image_cached(selected_id, _pixels(0), None)
    assert document.create_blank_mask(selected_id, _pixels(0).size()) is not None
    edits: list[UUID] = []
    document.mask_edits.imageEdited.connect(edits.append)

    assert document.canvas.replaceMaskImage(first_mask, _pixels(255))

    assert document.current_image_id() == selected_id
    assert edits == [first_id]


def test_mask_materialization_selection_and_archive_restore_are_not_edits(
    tmp_path: Path,
    qt_application_owner: QApplication,
    input_document_factory: InputDocumentFactory,
) -> None:
    """Restored pixels and presentation activation do not create authored edits."""

    mask_path = tmp_path / "mask.png"
    assert _pixels(255).save(str(mask_path))
    document = input_document_factory()
    edits: list[UUID] = []
    document.mask_edits.imageEdited.connect(edits.append)
    first_id, second_id = uuid4(), uuid4()
    document.ensure_image_cached(first_id, _pixels(0), None)
    mask_id = document.load_mask_from_file(first_id, mask_path)
    assert mask_id is not None
    document.ensure_image_cached(second_id, _pixels(0), None)
    assert document.create_blank_mask(second_id, _pixels(0).size()) is not None
    assert document.set_current_image_id(first_id)
    assert document.set_active_mask_id(mask_id)
    assert document.set_current_image_id(second_id)
    assert edits == []
    archive = tmp_path / "document.ccanvas"
    document.editable_persistence.save_editable_document(archive)
    restored = input_document_factory()
    restored.mask_edits.imageEdited.connect(edits.append)
    restored.editable_persistence.restore_editable_document(archive)
    assert restored.set_current_image_id(first_id)
    assert restored.set_active_mask_id(mask_id)
    assert edits == []


@pytest.mark.parametrize("clear_pixels", (False, True))
def test_mask_autosave_sees_dirty_state_and_advanced_archive_revision(
    clear_pixels: bool,
    tmp_path: Path,
    qt_application_owner: QApplication,
    input_document_factory: InputDocumentFactory,
) -> None:
    """The first autosave after editing must persist new pixels instead of skipping."""

    document = input_document_factory()
    image_id = uuid4()
    document.ensure_image_cached(image_id, _pixels(0), None)
    mask_id = document.create_blank_mask(image_id, _pixels(0).size())
    assert mask_id is not None
    if clear_pixels:
        assert document.canvas.replaceMaskImage(mask_id, _pixels(255))
        mask = document.canvas.listMasksForComposition(image_id)[0]
        assert mask.scene_id is not None and mask.layer_id is not None
        assert document.canvas.setSelectedLayer(mask.scene_id, mask.layer_id)
        assert document.canvas.setPixelSelection(_pixels(255), QRect(0, 0, 24, 16))
    archive = tmp_path / "editable.ccanvas"
    lifecycle = InputEditableDocumentLifecycle(
        document=document.editable_persistence, archive_path=archive
    )
    lifecycle.prepare_session_persistence().persist()
    tracker = InputEditableDocumentChangeTracker(
        changes=(document.maskContentChanged,), mark_changed=lifecycle.mark_changed
    )
    workflow = WorkflowState()
    workflow.canvas.bind_image("Cube:Image", image_id)
    service = UnsavedWorkService()
    service.mark_saved("owner", tmp_path / "saved.sugar")
    autosaves: list[bool] = []
    invalidated: list[str] = []

    def autosave() -> None:
        """Capture the first requested recovery state through its real owner."""

        autosaves.append(service.state_for("owner").dirty)
        lifecycle.prepare_session_persistence().persist()

    observer = InputMaskUnsavedWorkObserver(
        edits=document.mask_edits.imageEdited,
        workflows=lambda: {"owner": workflow},
        unsaved_work=service,
        edits_muted=lambda: False,
        mark_workflow_changed=invalidated.append,
        request_autosave=autosave,
    )

    if clear_pixels:
        assert document.tool_options.clear_selected_pixels()
    else:
        assert document.canvas.replaceMaskImage(mask_id, _pixels(255))

    assert tracker is not None and observer is not None
    assert autosaves == [True]
    assert invalidated == ["owner"]
    restored = input_document_factory()
    restored.editable_persistence.restore_editable_document(archive)
    assert restored.export_mask_image(mask_id) == _pixels(0 if clear_pixels else 255)

    service.mark_saved("owner", tmp_path / "saved.sugar")
    assert document.canvas.undoSceneEdit()
    assert autosaves == [True, True]
    restored_undo = input_document_factory()
    restored_undo.editable_persistence.restore_editable_document(archive)
    assert restored_undo.export_mask_image(mask_id) == _pixels(
        255 if clear_pixels else 0
    )


@dataclass(frozen=True)
class _MaskIdentity:
    """Describe an external mask catalog result for ownership rejection tests."""

    mask_id: UUID
    layer_id: UUID | None = None


@pytest.mark.parametrize("composition_count", (0, 2))
def test_unowned_or_ambiguous_mask_event_does_not_publish_an_image(
    composition_count: int,
    qt_application_owner: QApplication,
    input_document_factory: InputDocumentFactory,
) -> None:
    """A public mask event must resolve uniquely before any workflow can be dirtied."""

    document = input_document_factory()
    mask = _MaskIdentity(uuid4())
    catalog = InputDocumentCatalog(lambda _composition_id: (mask,))
    for _index in range(composition_count):
        image_id = uuid4()
        catalog.record(image_id, image_id, path=None, payload_revision=0)
    observer = InputMaskEditObserver(
        canvas=document.canvas, catalog=catalog, parent=document
    )
    edits: list[UUID] = []
    observer.imageEdited.connect(edits.append)

    document.canvas.maskUndoStackChanged.emit(mask.mask_id)
    document.canvas.layerPixelsChanged.emit(uuid4(), uuid4(), mask.mask_id)

    assert edits == []
