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

"""Present conservative dirty-document decisions on the shared Fluent surface."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QWidget

from substitute.application.workflows.unsaved_work_service import UnsavedWorkDecision
from substitute.presentation.dialogs.localized_fluent_dialogs import (
    LocalizedMessageBoxBase,
)
from substitute.presentation.localization import (
    LocalizedBodyLabel,
    LocalizedCaptionLabel,
    LocalizedPushButton,
    LocalizedSubtitleLabel,
)
from sugarsubstitute_shared.localization import app_text
from sugarsubstitute_shared.presentation.localization import (
    set_localized_text,
    set_localized_window_title,
)

_DISCARD_RESULT = 2


class UnsavedWorkDialog(LocalizedMessageBoxBase):
    """Keep Save, Don't Save, and Cancel distinct throughout the modal fade."""

    def __init__(self, *, parent: QWidget, workflow_name: str) -> None:
        """Build the application's standard modal without changing document state."""

        super().__init__(parent)
        self._decision = UnsavedWorkDecision.CANCEL
        self._finishing = False
        self.setClosableOnMaskClicked(False)
        self.widget.setFixedWidth(520)
        set_localized_window_title(self, "Unsaved work")
        self.title_label = LocalizedSubtitleLabel(app_text("Unsaved work"), self.widget)
        self.message_label = LocalizedBodyLabel(
            app_text("Save changes to “%1” before continuing?", workflow_name),
            self.widget,
        )
        self.recovery_label = LocalizedCaptionLabel(
            app_text(
                "A recovery copy is kept, but explicit saves are the durable project file."
            ),
            self.widget,
        )
        for label in (self.title_label, self.message_label, self.recovery_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            self.viewLayout.addWidget(label)

        set_localized_text(self.yesButton, "Save")
        self.discard_button = LocalizedPushButton(
            app_text("Don't Save"), self.buttonGroup
        )
        self.discard_button.clicked.connect(self._discard)
        self.buttonLayout.insertWidget(1, self.discard_button, 1)
        self.yesButton.setDefault(True)
        QWidget.setTabOrder(self.yesButton, self.discard_button)
        QWidget.setTabOrder(self.discard_button, self.cancelButton)

    @property
    def decision(self) -> UnsavedWorkDecision:
        """Return Cancel until an explicit action commits another outcome."""

        return self._decision

    def done(self, result: int) -> None:
        """Lock the first choice while QFluent animates the dialog's dismissal."""

        if self._finishing:
            return
        self._finishing = True
        if result == QDialog.DialogCode.Accepted:
            self._decision = UnsavedWorkDecision.SAVE
        elif result == _DISCARD_RESULT:
            self._decision = UnsavedWorkDecision.DISCARD
        else:
            self._decision = UnsavedWorkDecision.CANCEL
        self.buttonGroup.setEnabled(False)
        super().done(result)

    def _discard(self) -> None:
        """Continue without an explicit save only after the dedicated action."""

        self.done(_DISCARD_RESULT)


__all__ = ["UnsavedWorkDialog"]
