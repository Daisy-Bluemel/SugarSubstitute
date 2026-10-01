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

"""Verify immutable explicit-save mask products through real persistence owners."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cutecanvas import MaskExportSnapshot
from PySide6.QtGui import QImage

from substitute.application.recipes import RecipeIoService
from substitute.application.recipes.workflow_recipe_save_service import (
    WorkflowRecipeSaveService,
)
from substitute.application.workflows.canvas_io_service import CanvasIoService
from substitute.application.workflows.input_asset_association_service import (
    InputAssetAssociationService,
)
from substitute.application.workflows.ordered_mask_graph_value_service import (
    OrderedMaskGraphValueService,
)
from substitute.application.workflows.workflow_asset_service import WorkflowAssetService
from substitute.application.workflows.workflow_graph_section_service import (
    WorkflowGraphSectionService,
)
from substitute.domain.workflow import CubeState, WorkflowState
from substitute.infrastructure.persistence import FileRecipeRepository, QtImageStore
from substitute.infrastructure.persistence.recipe_mask_product_store import (
    RecipeMaskProductStore,
)
from substitute.presentation.canvas.input.input_document_capture import (
    InputDocumentCapture,
)
from substitute.presentation.canvas.input.input_mask_product_materializer import (
    InputMaskProductMaterializer,
)
from substitute.presentation.canvas.input.input_recipe_save_preparation import (
    InputRecipeSavePreparation,
)
from tests.application.workflows.input_canvas.support import (
    _input_canvas_binding_service,
)
from tests.support.canonical_cube_graph import graph_backed_cube_workflow_from_states


class _Capture:
    """Model only the public detached canvas export boundary."""

    def __init__(self, workflow: WorkflowState) -> None:
        """Keep distinct pixels for every scalar and ordered mask identity."""

        self.workflow = workflow
        self.requests: list[tuple[UUID, ...]] = []
        self.fail = False
        self.snapshots = {
            mask_id: MaskExportSnapshot(mask_id, owner, 1, _image(40 + index * 70))
            for index, (mask_id, owner) in enumerate(
                workflow.canvas.mask_image_owners().items()
            )
        }

    def __call__(
        self, *, image_ids: tuple[UUID, ...], mask_ids: tuple[UUID, ...]
    ) -> InputDocumentCapture | None:
        """Require capture of the whole workflow regardless of active mask."""

        assert image_ids == ()
        self.requests.append(mask_ids)
        if self.fail:
            return None
        return InputDocumentCapture(
            images={}, masks={key: self.snapshots[key] for key in mask_ids}
        )


class _ImageIo(CanvasIoService):
    """Inject a precise PNG failure while keeping real encoding and filesystem IO."""

    def __init__(self) -> None:
        """Use the production atomic Qt image repository."""

        super().__init__(image_repository=QtImageStore())
        self.calls = 0
        self.fail_at: int | None = None

    def save_mask_image(self, *, destination: Path, image: object) -> bool:
        """Reject the selected write before publishing that product."""

        self.calls += 1
        return self.calls != self.fail_at and super().save_mask_image(
            destination=destination, image=image
        )


def _image(value: int) -> QImage:
    """Create small deterministic grayscale coverage without any Qt widgets."""

    image = QImage(7, 5, QImage.Format.Format_Grayscale8)
    image.fill(value)
    return image


def _workflow() -> WorkflowState:
    """Build two image surfaces containing scalar and ordered mask bindings."""

    nodes = {
        "image": {
            "class_type": "LoadImage",
            "inputs": {"image": "/original/first.png"},
        },
        "mask": {"class_type": "LoadImageMask", "inputs": {"image": "original.png"}},
        "consumer": {
            "class_type": "Blend",
            "inputs": {"image": ["image", 0], "mask": ["mask", 0]},
        },
        "other": {
            "class_type": "LoadImage",
            "inputs": {"image": "/original/other.png"},
        },
        "batch": {
            "class_type": "SimpleSyrup.LoadMaskBatch",
            "inputs": {"image": ["first.png", "second.png"]},
        },
        "batch_consumer": {
            "class_type": "Blend",
            "inputs": {"image": ["other", 0], "mask": ["batch", 0]},
        },
    }
    cube = CubeState(
        cube_id="test/Inpaint.cube",
        version="1.0.0",
        alias="Canvas",
        original_cube={},
        buffer={
            "nodes": nodes,
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
                        "class_type": nodes[name]["class_type"],
                        "value_type": "string",
                    }
                    for name in ("image", "mask", "other", "batch")
                ],
            },
        },
    )
    workflow = graph_backed_cube_workflow_from_states(cube)
    first_image, second_image = uuid4(), uuid4()
    workflow.canvas.bind_image("Canvas:image", first_image)
    workflow.canvas.bind_image("Canvas:other", second_image)
    workflow.canvas.bind_mask(("Canvas", "mask"), uuid4(), first_image)
    regions = workflow.canvas.ensure_regional_mask_collection(("Canvas", "batch"))
    regions.add_region(second_image, mask_id=uuid4())
    active = regions.add_region(second_image, mask_id=uuid4())
    workflow.canvas.input_image_uuid = second_image
    workflow.canvas.active_input_mask_uuid = active.mask_id
    return workflow


def _preparation(capture: _Capture, image_io: _ImageIo) -> InputRecipeSavePreparation:
    """Compose real binding, association, product storage, and mask materialization."""

    graphs = WorkflowGraphSectionService()
    associations = InputAssetAssociationService(
        bindings=_input_canvas_binding_service(),
        assets=WorkflowAssetService(graphs),
        ordered_graph_values=OrderedMaskGraphValueService(graphs),
    )
    return InputRecipeSavePreparation(
        capture_inputs=capture,
        materializer=InputMaskProductMaterializer(
            canvas_io_service=image_io, input_assets=associations
        ),
        products=RecipeMaskProductStore(),
        workflow_name_provider=lambda _identity: "Original tab",
    )


def _paths(workflow: WorkflowState) -> tuple[Path, ...]:
    """Read scalar and exact ordered graph values through their public owner."""

    graphs = WorkflowGraphSectionService()
    scalar = graphs.input_value(
        workflow, section_key="Canvas", node_name="mask", field_key="image"
    )
    ordered = graphs.input_value(
        workflow, section_key="Canvas", node_name="batch", field_key="image"
    )
    assert isinstance(scalar, str) and isinstance(ordered, list)
    assert all(isinstance(item, str) for item in ordered)
    return (Path(scalar), *(Path(str(item)) for item in ordered))


def test_save_prepares_all_masks_as_immutable_absolute_products(tmp_path: Path) -> None:
    """Inactive scalar masks and ordered regions must preserve exact pixels and source."""

    workflow = _workflow()
    before = deepcopy(workflow)
    capture = _Capture(workflow)
    destination = tmp_path / "outside projects" / "chosen.sugar"
    with _preparation(capture, _ImageIo()).prepare(
        workflow_id="workflow", workflow=workflow, destination=destination
    ) as prepared:
        paths = _paths(prepared)
        assert len(paths) == 3
        assert all(
            path.is_absolute() and path.is_relative_to(destination.parent)
            for path in paths
        )
        for mask_id, path in zip(workflow.canvas.mask_ids(), paths, strict=True):
            assert QImage(str(path)) == capture.snapshots[mask_id].image
        RecipeIoService(FileRecipeRepository()).save_workflow_recipe(
            destination, workflow_name="Original tab", workflow=prepared
        )
    assert capture.requests == [workflow.canvas.mask_ids()]
    assert workflow == before
    assert all(str(path) in destination.read_text() for path in paths)


def test_later_save_preserves_previous_products_even_when_revision_repeats(
    tmp_path: Path,
) -> None:
    """A second save after restore cannot overwrite a prior recipe's referenced pixels."""

    workflow = _workflow()
    capture = _Capture(workflow)
    preparation = _preparation(capture, _ImageIo())
    destination = tmp_path / "chosen.sugar"
    recipes = RecipeIoService(FileRecipeRepository())
    save = WorkflowRecipeSaveService(
        recipes=recipes, input_preparation=lambda: preparation
    )
    save.save(
        destination=destination,
        workflow_id="workflow",
        workflow_name="Original",
        workflow=workflow,
    )
    first_recipe = destination.read_bytes()
    first_products = {path: path.read_bytes() for path in tmp_path.rglob("*.png")}
    capture.snapshots = {
        identity: MaskExportSnapshot(identity, snapshot.composition_id, 1, _image(255))
        for identity, snapshot in capture.snapshots.items()
    }
    save.save(
        destination=destination,
        workflow_id="workflow",
        workflow_name="Original",
        workflow=workflow,
    )
    assert destination.read_bytes() != first_recipe
    assert any(
        path.read_bytes() == first_recipe
        for path in (tmp_path / "versions").glob("*.sugar")
    )
    assert all(path.read_bytes() == data for path, data in first_products.items())
    assert len(tuple(tmp_path.rglob("*.png"))) == 6


@pytest.mark.parametrize("failure", ("capture", "second_png", "recipe", "association"))
def test_failed_save_keeps_source_and_old_products_and_removes_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Late failures must leave only the previous durable recipe and pixel products."""

    workflow = _workflow()
    capture = _Capture(workflow)
    image_io = _ImageIo()
    preparation = _preparation(capture, image_io)
    destination = tmp_path / "chosen.sugar"
    destination.write_bytes(b"previous recipe")
    original = tmp_path / "original.png"
    assert _image(0).save(str(original))
    old_png = original.read_bytes()
    if failure == "capture":
        capture.fail = True
    elif failure == "second_png":
        image_io.fail_at = 2
    elif failure == "association":
        identity = uuid4()
        workflow.canvas.bind_mask(
            ("Missing", "mask"), identity, workflow.canvas.image_ids()[0]
        )
        capture.snapshots[identity] = MaskExportSnapshot(
            identity, workflow.canvas.image_ids()[0], 1, _image(5)
        )
    else:

        def reject_publication(*_args: object, **_kwargs: object) -> None:
            """Fail only the external recipe commit boundary after mask writes."""
            raise OSError("Recipe publication failed")

        monkeypatch.setattr(
            FileRecipeRepository, "save_recipe_document", reject_publication
        )
    before = deepcopy(workflow)
    save = WorkflowRecipeSaveService(
        recipes=RecipeIoService(FileRecipeRepository()),
        input_preparation=lambda: preparation,
    )
    with pytest.raises((RuntimeError, OSError)):
        save.save(
            destination=destination,
            workflow_id="workflow",
            workflow_name="Original",
            workflow=workflow,
        )
    assert workflow == before
    assert destination.read_bytes() == b"previous recipe"
    assert original.read_bytes() == old_png
    assert tuple(tmp_path.rglob("*.png")) == (original,)
    assert not tuple((tmp_path / "masks" / ".saved").glob("*"))
