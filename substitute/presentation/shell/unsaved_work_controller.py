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

"""Present Save, Don't Save, or Cancel at destructive workflow boundaries."""

from __future__ import annotations

from typing import Any, Protocol, cast

from PySide6.QtWidgets import QWidget

from substitute.application.workflows.unsaved_work_service import (
    UnsavedWorkDecision,
)
from substitute.presentation.dialogs.unsaved_work_dialog import UnsavedWorkDialog


class UnsavedWorkPrompt(Protocol):
    """Choose how one dirty workflow should be handled."""

    def decide(
        self,
        *,
        parent: QWidget,
        workflow_name: str,
    ) -> UnsavedWorkDecision:
        """Return the user's explicit dirty-document decision."""


class QtUnsavedWorkPrompt:
    """Render dirty-document decisions with the application's shared Fluent modal."""

    def decide(
        self,
        *,
        parent: QWidget,
        workflow_name: str,
    ) -> UnsavedWorkDecision:
        """Return one explicit decision and release this prompt's dialog owner."""

        dialog = UnsavedWorkDialog(parent=parent, workflow_name=workflow_name)
        try:
            dialog.exec()
            return dialog.decision
        finally:
            dialog.deleteLater()


class UnsavedWorkController:
    """Coordinate dirty-document decisions with shell save and activation owners."""

    def __init__(
        self,
        shell: Any,
        *,
        prompt: UnsavedWorkPrompt | None = None,
    ) -> None:
        """Store the shell and the user-decision boundary."""

        self._shell = shell
        self._prompt = prompt or QtUnsavedWorkPrompt()

    def confirm_workflow_close(self, workflow_id: str) -> bool:
        """Return whether one workflow may be closed without losing work."""

        state = self._shell.unsaved_work_service.state_for(workflow_id)
        if not state.dirty:
            return True
        return self._resolve_workflow(workflow_id)

    def confirm_shutdown(self) -> bool:
        """Resolve every dirty workflow before maintenance or app shutdown."""

        ordered_ids = tuple(self._shell.workflow_tabbar.workflow_ids_in_order())
        dirty_ids = self._shell.unsaved_work_service.dirty_workflow_ids(ordered_ids)
        return all(self._resolve_workflow(workflow_id) for workflow_id in dirty_ids)

    def _resolve_workflow(self, workflow_id: str) -> bool:
        """Apply one explicit dirty-work decision and report continuation."""

        item = self._shell.workflow_tabbar.itemMap.get(workflow_id)
        workflow_name = item.text() if item is not None else workflow_id
        decision = self._prompt.decide(
            parent=cast(QWidget, self._shell),
            workflow_name=str(workflow_name),
        )
        if decision is UnsavedWorkDecision.CANCEL:
            return False
        if decision is UnsavedWorkDecision.DISCARD:
            return True
        active_id = self._shell.workflow_session_service.active_workflow_id
        if active_id != workflow_id:
            self._shell.workflow_workspace.activate_workflow(
                workflow_id,
                source="unsaved_work_save",
            )
        return bool(
            self._shell.workspace_file_actions.recipe_save_actions.on_save_clicked()
        )


__all__ = [
    "QtUnsavedWorkPrompt",
    "UnsavedWorkController",
    "UnsavedWorkPrompt",
]
