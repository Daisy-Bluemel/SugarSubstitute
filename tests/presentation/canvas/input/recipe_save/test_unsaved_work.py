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

"""Exercise mask editing, close cancellation, and sequential explicit save outcomes."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from substitute.application.workflows.canvas_io_service import CanvasIoService
from substitute.application.workflows.input_asset_association_service import (
    InputAssetAssociationService,
)
from substitute.application.workflows.ordered_mask_graph_value_service import (
    OrderedMaskGraphValueService,
)
from substitute.application.workflows.unsaved_work_service import UnsavedWorkDecision
from substitute.application.workflows.workflow_asset_service import WorkflowAssetService
from substitute.application.workflows.workflow_graph_section_service import (
    WorkflowGraphSectionService,
)
from substitute.domain.workflow import CubeState
from substitute.infrastructure.persistence import QtImageStore
from substitute.infrastructure.persistence.recipe_mask_product_store import (
    RecipeMaskProductStore,
)
from substitute.presentation.canvas.input.input_mask_product_materializer import (
    InputMaskProductMaterializer,
)
from substitute.presentation.canvas.input.input_recipe_save_preparation import (
    InputRecipeSavePreparation,
)
from substitute.presentation.shell.input_mask_unsaved_work_observer import (
    InputMaskUnsavedWorkObserver,
)
from substitute.presentation.shell.unsaved_work_controller import UnsavedWorkController
from tests.application.workflows.input_canvas.support import (
    _input_canvas_binding_service,
)
from tests.presentation.shell.recipe_save.support import SaveView
from tests.support.canonical_cube_graph import graph_backed_cube_workflow_from_states
from tests.support.cutecanvas.input_document import InputDocumentFactory


class _MaskWriter(CanvasIoService):
    """Allow a deterministic storage rejection while retaining real PNG writes."""

    def __init__(self) -> None:
        """Use production image persistence with a controllable failure boundary."""

        super().__init__(image_repository=QtImageStore())
        self.reject = False
        self.written: list[Path] = []

    def save_mask_image(self, *, destination: Path, image: object) -> bool:
        """Reject before publication or persist the actual captured image."""

        if self.reject:
            return False
        saved = super().save_mask_image(destination=destination, image=image)
        if saved:
            self.written.append(destination)
        return saved


class _CancelPrompt:
    """Return the user's Cancel decision at the close-confirmation boundary."""

    def __init__(self) -> None:
        """Keep the names of documents that required a decision."""

        self.names: list[str] = []

    def decide(self, *, parent: QWidget, workflow_name: str) -> UnsavedWorkDecision:
        """Record the visible document and refuse its closure."""

        self.names.append(workflow_name)
        return UnsavedWorkDecision.CANCEL


def test_mask_edit_requires_close_decision_until_successful_explicit_save(
    tmp_path: Path,
    qt_application_owner: QApplication,
    input_document_factory: InputDocumentFactory,
) -> None:
    """A real authored mask survives Cancel and failed Save, then saves cleanly."""

    cube = CubeState(
        cube_id="test/Inpaint.cube",
        version="1.0.0",
        alias="Canvas",
        original_cube={},
        buffer={
            "nodes": {
                "image": {"class_type": "LoadImage", "inputs": {"image": "source.png"}},
                "mask": {
                    "class_type": "LoadImageMask",
                    "inputs": {"image": "mask.png"},
                },
                "consumer": {
                    "class_type": "Blend",
                    "inputs": {"image": ["image", 0], "mask": ["mask", 0]},
                },
            },
            "inputs": {},
            "outputs": {},
            "surface": {
                "default_flavor_id": "default",
                "controls": [
                    {
                        "control_id": name,
                        "symbol": name,
                        "input_name": "image",
                        "label": name,
                        "class_type": class_type,
                        "value_type": "string",
                    }
                    for name, class_type in (
                        ("image", "LoadImage"),
                        ("mask", "LoadImageMask"),
                    )
                ],
            },
        },
    )
    workflow = graph_backed_cube_workflow_from_states(cube)
    view = SaveView(tmp_path, workflow)
    document = input_document_factory()
    image_id = uuid4()
    pixels = QImage(24, 16, QImage.Format.Format_Grayscale8)
    pixels.fill(0)
    document.ensure_image_cached(image_id, pixels, None)
    mask_id = document.create_blank_mask(image_id, pixels.size())
    assert mask_id is not None
    workflow.canvas.bind_image("Canvas:image", image_id)
    workflow.canvas.bind_mask(("Canvas", "mask"), mask_id, image_id)
    graphs = WorkflowGraphSectionService()
    writer = _MaskWriter()
    view.input_recipe_save_preparation = InputRecipeSavePreparation(
        capture_inputs=document.export_capture.capture,
        materializer=InputMaskProductMaterializer(
            canvas_io_service=writer,
            input_assets=InputAssetAssociationService(
                bindings=_input_canvas_binding_service(),
                assets=WorkflowAssetService(graphs),
                ordered_graph_values=OrderedMaskGraphValueService(graphs),
            ),
        ),
        products=RecipeMaskProductStore(),
        workflow_name_provider=lambda _workflow_id: "Recipe",
    )
    invalidated: list[str] = []
    autosaves: list[None] = []
    observer = InputMaskUnsavedWorkObserver(
        edits=document.mask_edits.imageEdited,
        workflows=lambda: view.workflow_session_service.workflows,
        unsaved_work=view.unsaved_work_service,
        edits_muted=lambda: False,
        mark_workflow_changed=invalidated.append,
        request_autosave=lambda: autosaves.append(None),
    )
    save = view.workspace_file_actions.recipe_save_actions.on_save_clicked
    assert save()
    baseline = view.destination.read_bytes()
    assert not view.unsaved_work_service.state_for("workflow").dirty
    prompt = _CancelPrompt()
    close = UnsavedWorkController(view, prompt=prompt)
    assert close.confirm_workflow_close("workflow")
    assert prompt.names == []

    pixels.fill(255)
    assert document.canvas.replaceMaskImage(mask_id, pixels)
    assert observer is not None
    assert view.unsaved_work_service.state_for("workflow").dirty
    assert close.confirm_workflow_close("workflow") is False
    assert prompt.names == ["Recipe"]
    assert view.get_active_workflow() is workflow
    writer.reject = True
    assert save() is False
    assert view.unsaved_work_service.state_for("workflow").dirty
    assert view.destination.read_bytes() == baseline
    assert document.export_mask_image(mask_id) == pixels

    writer.reject = False
    assert save()
    assert not view.unsaved_work_service.state_for("workflow").dirty
    assert QImage(str(writer.written[-1])) == pixels
    assert close.confirm_workflow_close("workflow")
    assert prompt.names == ["Recipe"]

    assert document.canvas.undoSceneEdit()
    assert view.unsaved_work_service.state_for("workflow").dirty
    assert save()
    assert not view.unsaved_work_service.state_for("workflow").dirty
    assert document.canvas.redoSceneEdit()
    assert view.unsaved_work_service.state_for("workflow").dirty
    assert save()
    assert not view.unsaved_work_service.state_for("workflow").dirty
    assert QImage(str(writer.written[-1])) == pixels
    assert invalidated == ["workflow"] * 3
    assert autosaves == [None] * 3
