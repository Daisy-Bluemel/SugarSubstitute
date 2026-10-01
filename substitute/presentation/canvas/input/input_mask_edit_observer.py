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

"""Identify authored Input mask pixel edits through public CuteCanvas signals."""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import QObject, Signal
from cutecanvas import CuteCanvas

from substitute.presentation.canvas.input.input_document_catalog import (
    InputDocumentCatalog,
)
from substitute.shared.logging.logger import get_logger, log_warning

_LOGGER = get_logger("presentation.canvas.input.input_mask_edit_observer")


class InputMaskEditObserver(QObject):
    """Publish the owning image for committed mask pixels and history replay."""

    imageEdited = Signal(object)

    def __init__(
        self,
        *,
        canvas: CuteCanvas,
        catalog: InputDocumentCatalog,
        parent: QObject,
    ) -> None:
        """Observe durable mask events independently of active image selection."""

        super().__init__(parent)
        self._catalog = catalog
        canvas.maskUndoStackChanged.connect(self._mask_history_changed)
        canvas.layerPixelsChanged.connect(self._layer_pixels_changed)

    def _mask_history_changed(self, mask_id: UUID) -> None:
        """Resolve an accepted mask commit or replay through document identity."""

        composition_id = self._catalog.composition_for_mask(mask_id)
        image_id = (
            None
            if composition_id is None
            else self._catalog.image_id_for_composition(composition_id)
        )
        if image_id is None:
            log_warning(
                _LOGGER,
                "Ignored Input mask edit without unique document ownership",
                mask_id=str(mask_id),
                rejection_reason="unknown_or_ambiguous_mask_composition",
            )
            return
        self.imageEdited.emit(image_id)

    def _layer_pixels_changed(
        self, _scene_id: UUID, _layer_id: UUID, resource_id: UUID
    ) -> None:
        """Forward generic durable pixel edits only for catalog-owned masks."""

        if self._catalog.contains_mask_resource(resource_id):
            self._mask_history_changed(resource_id)


__all__ = ["InputMaskEditObserver"]
