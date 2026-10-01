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

"""Mark the owning workflow unsaved after identified authored mask pixel edits."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol
from uuid import UUID

from substitute.application.workflows.unsaved_work_service import UnsavedWorkService
from substitute.domain.workflow import WorkflowState
from substitute.shared.logging.logger import get_logger, log_warning

_LOGGER = get_logger("presentation.shell.input_mask_unsaved_work_observer")


class MaskEditSignalPort(Protocol):
    """Expose identified authored mask pixel events without owning their source."""

    def connect(self, callback: Callable[[UUID], None]) -> object:
        """Register one listener for the original Input image identity."""


class InputMaskUnsavedWorkObserver:
    """Keep mask edit ownership separate from tab selection and recovery saves."""

    def __init__(
        self,
        *,
        edits: MaskEditSignalPort,
        workflows: Callable[[], Mapping[str, WorkflowState]],
        unsaved_work: UnsavedWorkService,
        edits_muted: Callable[[], bool],
        mark_workflow_changed: Callable[[str], None],
        request_autosave: Callable[[], None],
    ) -> None:
        """Bind authoritative membership and the shell's restoration mute policy."""

        self._workflows = workflows
        self._unsaved_work = unsaved_work
        self._edits_muted = edits_muted
        self._mark_workflow_changed = mark_workflow_changed
        self._request_autosave = request_autosave
        edits.connect(self._mask_edited)

    def _mask_edited(self, image_id: UUID) -> None:
        """Dirty one unambiguous owner before capturing its recovery snapshot."""

        if self._edits_muted():
            return
        owners = tuple(
            workflow_id
            for workflow_id, workflow in self._workflows().items()
            if workflow.canvas.image_entry_for_id(image_id) is not None
        )
        if len(owners) != 1:
            log_warning(
                _LOGGER,
                "Ignored Input mask edit without unique workflow ownership",
                image_id=str(image_id),
                workflow_ids=owners,
                rejection_reason="unknown_or_ambiguous_image_workflow",
            )
            return
        self._unsaved_work.mark_dirty(owners[0])
        self._mark_workflow_changed(owners[0])
        self._request_autosave()


__all__ = ["InputMaskUnsavedWorkObserver"]
