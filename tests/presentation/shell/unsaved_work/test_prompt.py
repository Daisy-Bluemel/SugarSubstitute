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

"""Exercise the production dirty-document modal through its decision boundary."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from shiboken6 import delete
import pytest

from substitute.application.workflows.unsaved_work_service import UnsavedWorkDecision
from substitute.presentation.dialogs.unsaved_work_dialog import UnsavedWorkDialog
from substitute.presentation.shell.unsaved_work_controller import QtUnsavedWorkPrompt


@pytest.mark.parametrize("expected", list(UnsavedWorkDecision))
def test_prompt_uses_shared_fluent_surface(
    qt_application_owner: QApplication, expected: UnsavedWorkDecision
) -> None:
    """Dirty-work decisions must use the same full-frame Fluent owner as app dialogs."""

    parent = QWidget()
    parent.resize(900, 640)
    parent.show()
    observed: list[bool] = []
    owned_dialogs: list[QDialog] = []
    timer = QTimer(parent)
    timer.setInterval(1)

    def dismiss() -> None:
        """Observe and cancel the actual modal once its event loop is entered."""

        modal = next(
            (child for child in parent.findChildren(QDialog) if child.isVisible()), None
        )
        if modal is None:
            return
        timer.stop()
        observed.append(isinstance(modal, UnsavedWorkDialog))
        owned_dialogs.append(modal)
        if isinstance(modal, UnsavedWorkDialog):
            button = {
                UnsavedWorkDecision.SAVE: modal.yesButton,
                UnsavedWorkDecision.DISCARD: modal.discard_button,
                UnsavedWorkDecision.CANCEL: modal.cancelButton,
            }[expected]
            button.click()
        else:
            modal.reject()

    timer.timeout.connect(dismiss)
    timer.start()
    deadline = QTimer(parent)
    deadline.setSingleShot(True)
    expired: list[bool] = []

    def fail_at_deadline() -> None:
        """Bound a broken modal without leaving a nested event loop running."""

        expired.append(True)
        for child in parent.findChildren(QDialog):
            QDialog.done(child, 0)

    deadline.timeout.connect(fail_at_deadline)
    deadline.start(3000)
    try:
        result = QtUnsavedWorkPrompt().decide(
            parent=parent, workflow_name="Portrait Study"
        )
        assert not expired
        assert observed == [True]
        assert result is expected
        for modal in owned_dialogs:
            QCoreApplication.sendPostedEvents(modal, QEvent.Type.DeferredDelete)
        assert parent.findChildren(QDialog) == []
    finally:
        timer.stop()
        deadline.stop()
        delete(parent)
