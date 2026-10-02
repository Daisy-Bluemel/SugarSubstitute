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

"""Protect complete editable Input recovery at both startup entry points."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest
from cutecanvas import PreparedDocumentRestore, prepare_document_restore
from PySide6.QtGui import QImage

from substitute.application.workspace_state import WorkspaceMaterializationService
from substitute.domain.workflow import WorkflowState
from substitute.domain.workspace_snapshot import (
    InputImageReference,
    InputMaskReference,
    WorkflowSnapshot,
    WorkspaceSnapshot,
)
from substitute.domain.workspace_snapshot.models import (
    WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
)
from substitute.presentation.shell.shell_workspace_materialization_port import (
    ShellWorkspaceMaterializationPort,
)
from tests.support.cutecanvas.input_document import InputDocumentFactory
from .startup_restore_support import PreparedArchive, RestoreShell


def _pixels(value: int) -> QImage:
    """Create exact mask data independent of paint geometry or native input."""
    image = QImage(24, 16, QImage.Format.Format_Grayscale8)
    image.fill(value)
    return image


@pytest.mark.parametrize("prehydrated", (False, True), ids=("ordinary", "prehydrated"))
@pytest.mark.parametrize("prepared", (False, True), ids=("disk", "prepared"))
def test_startup_restores_editable_pixels_and_all_identities_before_media(
    tmp_path: Path,
    input_document_factory: InputDocumentFactory,
    prehydrated: bool,
    prepared: bool,
) -> None:
    """Unsaved mask pixels and every composition survive both startup paths."""
    archive = tmp_path / "editable.ccanvas"
    source = input_document_factory()
    image_id, inactive_id = uuid4(), uuid4()
    image_path, mask_path = tmp_path / "image.png", tmp_path / "mask.png"
    assert _pixels(0).save(str(image_path))
    assert _pixels(0).save(str(mask_path))
    source.ensure_image_cached(image_id, _pixels(0), image_path)
    mask_id = source.create_blank_mask(image_id, _pixels(0).size())
    assert mask_id is not None
    assert source.canvas.replaceMaskImage(mask_id, _pixels(255))
    source.ensure_image_cached(inactive_id, _pixels(0), None)
    inactive_mask_id = source.create_blank_mask(inactive_id, _pixels(0).size())
    assert inactive_mask_id is not None
    assert source.canvas.replaceMaskImage(inactive_mask_id, _pixels(127))
    assert source.set_mask_visual_opacity(inactive_mask_id, 0.37)
    inactive_layer = source.canvas.listMasksForComposition(inactive_id)[0]
    assert inactive_layer.scene_id is not None and inactive_layer.layer_id is not None
    source.editable_persistence.save_editable_document(archive)
    source.close()
    archive_bytes = archive.read_bytes()

    workflow = WorkflowState()
    workflow.canvas.bind_image("Cube:image", image_id)
    workflow.canvas.bind_mask(("Cube", "mask"), mask_id, image_id)
    workflow.canvas.input_image_uuid = image_id
    workflow.canvas.active_input_mask_uuid = mask_id
    snapshot = WorkspaceSnapshot(
        schema_version=WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
        workflows=(
            WorkflowSnapshot(
                workflow_id="restored",
                tab_label="Restored",
                workflow=workflow,
                document_dirty=True,
                document_source_path=tmp_path / "saved.sugar",
                input_images=(
                    InputImageReference(
                        image_id=str(image_id), path=image_path, sequence=0
                    ),
                ),
                input_masks=(
                    InputMaskReference(
                        mask_id=str(mask_id),
                        image_id=str(image_id),
                        path=mask_path,
                        association_key=("Cube", "mask"),
                    ),
                ),
            ),
        ),
        tab_order=("restored",),
        active_route="restored",
        active_workflow_id="restored",
    )
    document = input_document_factory()
    shell = RestoreShell(document, archive, mask_id)
    if prepared:
        shell._restore_asset_preload = PreparedArchive(
            prepare_document_restore(archive)
        )
        # A valid prepared archive must be used without decoding the path again.
        archive.write_bytes(b"prepared authority already owns the decoded archive")
    controller = shell.workspace_restore_controller

    if prehydrated:
        assert controller.prehydrate_initial_workspace(snapshot)
        assert shell.shell_prehydrated_restore_controller.prepare_initial_workspace_restore_runtime()
    else:
        assert controller.restore_initial_workspace_snapshot(snapshot)

    assert shell.canvas_io_service.mask_at_image_load == [_pixels(255)]
    assert set(document.canvas.compositionIDs()) == {image_id, inactive_id}
    assert document.contains_mask(image_id, mask_id)
    assert document.contains_mask(inactive_id, inactive_mask_id)
    assert document.export_mask_image(mask_id) == _pixels(255)
    assert document.export_mask_image(inactive_mask_id) == _pixels(127)
    restored_layer = document.canvas.listMasksForComposition(inactive_id)[0]
    assert restored_layer.scene_id == inactive_layer.scene_id
    assert restored_layer.layer_id == inactive_layer.layer_id
    assert document.mask_visual_opacity(inactive_mask_id) == pytest.approx(0.37)
    restored = shell.workflow_session_service.workflows["restored"]
    entry = restored.canvas.mask_entry(("Cube", "mask"))
    assert entry is not None and entry.mask_id == mask_id
    assert restored.canvas.active_input_mask_uuid == mask_id
    state = shell.unsaved_work_service.state_for("restored")
    assert state.dirty and state.source_path == tmp_path / "saved.sugar"
    if not prepared:
        shell.input_editable_document_lifecycle.prepare_session_persistence().persist()
        assert archive.read_bytes() == archive_bytes

    # A prehydration failure can fall back to ordinary restore after live state exists.
    assert document.canvas.replaceMaskImage(mask_id, _pixels(63))
    assert controller.restore_initial_workspace_snapshot(snapshot)
    assert document.export_mask_image(mask_id) == _pixels(63)
    assert document.contains_mask(inactive_id, inactive_mask_id)


@pytest.mark.parametrize("append", (False, True), ids=("open", "import"))
def test_live_recipe_materialization_does_not_replay_session_archive(
    tmp_path: Path,
    input_document_factory: InputDocumentFactory,
    append: bool,
) -> None:
    """Recipe opens and imports must not admit stale startup document authority."""
    archive = tmp_path / "editable.ccanvas"
    source = input_document_factory()
    stale_id = uuid4()
    source.ensure_image_cached(stale_id, _pixels(0), None)
    stale_mask = source.create_blank_mask(stale_id, _pixels(0).size())
    assert stale_mask is not None
    assert source.canvas.replaceMaskImage(stale_mask, _pixels(255))
    source.editable_persistence.save_editable_document(archive)
    source.close()
    document = input_document_factory()
    shell = RestoreShell(document, archive, stale_mask)
    snapshot = WorkspaceSnapshot(
        schema_version=WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
        workflows=(
            WorkflowSnapshot(
                workflow_id="opened", tab_label="Opened", workflow=WorkflowState()
            ),
        ),
        tab_order=("opened",),
        active_route="opened",
        active_workflow_id="opened",
    )
    service = WorkspaceMaterializationService()
    port = ShellWorkspaceMaterializationPort(shell)

    result = (
        service.materialize_into_existing_workspace(snapshot, port)
        if append
        else service.materialize(snapshot, port)
    )

    assert result.warnings == ()
    assert shell.workflow_session_service.active_workflow_id == "opened"
    assert not document.contains(stale_id)
    assert not document.contains_mask(stale_id, stale_mask)
    assert shell.input_editable_document_lifecycle.restored_composition_ids == ()


@pytest.mark.parametrize("archive_kind", ("missing", "invalid", "missing_manifest"))
def test_startup_without_usable_archive_falls_back_to_file_mask(
    tmp_path: Path,
    input_document_factory: InputDocumentFactory,
    archive_kind: str,
) -> None:
    """Missing or rejected editable authority leaves file-backed startup usable."""
    archive = tmp_path / "editable.ccanvas"
    if archive_kind == "invalid":
        archive.write_bytes(b"invalid editable document")
    elif archive_kind == "missing_manifest":
        with ZipFile(archive, "w") as container:
            container.writestr("unexpected-member", b"retain these bytes")
    rejected_bytes = archive.read_bytes() if archive.is_file() else None
    image_id, original_mask_id = uuid4(), uuid4()
    image_path, mask_path = tmp_path / "image.png", tmp_path / "mask.png"
    assert _pixels(0).save(str(image_path))
    assert _pixels(127).save(str(mask_path))
    workflow = WorkflowState()
    workflow.canvas.bind_image("Cube:image", image_id)
    workflow.canvas.bind_mask(("Cube", "mask"), original_mask_id, image_id)
    workflow.canvas.input_image_uuid = image_id
    snapshot = WorkspaceSnapshot(
        schema_version=WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
        workflows=(
            WorkflowSnapshot(
                workflow_id="restored",
                tab_label="Restored",
                workflow=workflow,
                input_images=(
                    InputImageReference(
                        image_id=str(image_id), path=image_path, sequence=0
                    ),
                ),
                input_masks=(
                    InputMaskReference(
                        mask_id=str(original_mask_id),
                        image_id=str(image_id),
                        path=mask_path,
                        association_key=("Cube", "mask"),
                    ),
                ),
            ),
        ),
        tab_order=("restored",),
        active_route="restored",
        active_workflow_id="restored",
    )
    document = input_document_factory()
    shell = RestoreShell(document, archive, original_mask_id)

    assert shell.workspace_restore_controller.restore_initial_workspace_snapshot(
        snapshot
    )

    assert shell.canvas_io_service.mask_at_image_load == [None]
    restored = shell.workflow_session_service.workflows["restored"]
    entry = restored.canvas.mask_entry(("Cube", "mask"))
    assert entry is not None and entry.mask_id != original_mask_id
    assert document.contains_mask(image_id, entry.mask_id)
    assert document.export_mask_image(entry.mask_id) == _pixels(127)
    assert shell.input_editable_document_lifecycle.restored_composition_ids == ()
    assert shell.restore_finalized.finalized
    if rejected_bytes is not None:
        recovery_paths = tuple(tmp_path.glob("editable.ccanvas.rejected-*.recovery"))
        assert len(recovery_paths) == 1
        assert recovery_paths[0].read_bytes() == rejected_bytes
        shell.input_editable_document_lifecycle.prepare_session_persistence().persist()
        rebuilt = input_document_factory()
        rebuilt.editable_persistence.restore_editable_document(archive)
        assert rebuilt.contains_mask(image_id, entry.mask_id)
        assert rebuilt.export_mask_image(entry.mask_id) == _pixels(127)
        assert recovery_paths[0].read_bytes() == rejected_bytes


def test_startup_does_not_classify_installation_errors_as_rejected_archive(
    tmp_path: Path,
    input_document_factory: InputDocumentFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only decode failures may retire an archive; unrelated install bugs propagate."""
    archive = tmp_path / "editable.ccanvas"
    source = input_document_factory()
    image_id = uuid4()
    source.ensure_image_cached(image_id, _pixels(0), None)
    source.editable_persistence.save_editable_document(archive)
    source.close()
    original_bytes = archive.read_bytes()
    document = input_document_factory()
    shell = RestoreShell(document, archive, uuid4())
    snapshot = WorkspaceSnapshot(
        schema_version=WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
        workflows=(),
        tab_order=(),
        active_route="",
        active_workflow_id="",
    )

    def fail_install(prepared: PreparedDocumentRestore) -> tuple[object, ...]:
        """Inject an internal installation bug after successful archive decoding."""
        raise KeyError("installation invariant")

    monkeypatch.setattr(
        document.editable_persistence,
        "restore_prepared_editable_document",
        fail_install,
    )

    with pytest.raises(KeyError, match="installation invariant"):
        shell.workspace_restore_controller.restore_initial_workspace_snapshot(snapshot)

    assert archive.read_bytes() == original_bytes
    assert list(tmp_path.glob("editable.ccanvas.rejected-*.recovery")) == []
