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

"""Track explicit-save state for identified authored editor-section edits."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from PySide6.QtCore import QObject, Slot

from substitute.application.workflows.editor_projection_service import (
    WorkflowEditorProjectionService,
)
from substitute.application.workflows.unsaved_work_service import UnsavedWorkService
from substitute.domain.workflow import WorkflowState
from substitute.shared.logging.logger import get_logger, log_warning

_LOGGER = get_logger("presentation.shell.editor_section_unsaved_work_observer")


class SectionEditSignalPort(Protocol):
    """Expose the exact state object mutated by an authored editor operation."""

    def connect(self, callback: Callable[[object], None], /) -> object:
        """Register one section edit consumer."""


class EditorSectionUnsavedWorkObserver(QObject):
    """Follow the editor's lifetime and mark only an unambiguous document owner."""

    def __init__(
        self,
        *,
        parent: QObject,
        edits: SectionEditSignalPort,
        workflows: Callable[[], Mapping[str, WorkflowState]],
        unsaved_work: UnsavedWorkService,
        edits_muted: Callable[[], bool],
        request_autosave: Callable[[], None],
    ) -> None:
        """Connect the source signal with this QObject as its receiver context."""
        super().__init__(parent)
        self._workflows = workflows
        self._unsaved_work = unsaved_work
        self._edits_muted = edits_muted
        self._request_autosave = request_autosave
        self._projection = WorkflowEditorProjectionService()
        edits.connect(self._section_edited)

    @Slot(object)
    def _section_edited(self, section: object) -> None:
        """Dirty the actual section owner before scheduling recovery persistence."""
        if self._edits_muted():
            return
        owners = tuple(
            workflow_id
            for workflow_id, workflow in self._workflows().items()
            if any(
                candidate is section
                for candidate in self._projection.project(workflow).states.values()
            )
        )
        if len(owners) != 1:
            log_warning(
                _LOGGER,
                "Ignored editor field edit without unique workflow ownership",
                section_type=type(section).__name__,
                workflow_ids=owners,
                rejection_reason="unknown_or_ambiguous_editor_section",
            )
            return
        self._unsaved_work.mark_dirty(owners[0])
        self._request_autosave()


__all__ = ["EditorSectionUnsavedWorkObserver", "SectionEditSignalPort"]
