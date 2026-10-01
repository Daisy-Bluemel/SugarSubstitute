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

"""Display a blocking shutdown surface while Substitute is still closing."""

from __future__ import annotations

from functools import partial

from sugarsubstitute_shared.presentation.localization import (
    set_localized_text,
    set_localized_window_title,
    translate_application_message,
)

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QLabel, QWidget
from qfluentwidgets import Dialog  # type: ignore[import-untyped]


class ShutdownProgressDialog(Dialog):  # type: ignore[misc]
    """Use standalone Fluent chrome while preserving immediate shutdown closure."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the lightweight shutdown surface and its fixed copy."""

        self._allow_close = False
        super().__init__(
            translate_application_message("Closing Substitute..."),
            translate_application_message("Please wait a moment."),
            parent,
        )
        set_localized_window_title(self, "Closing Substitute")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setTitleBarVisible(False)
        self.buttonGroup.hide()
        self.headline_label: QLabel = self.titleLabel
        self.body_label: QLabel = self.contentLabel
        self.headline_label.setWordWrap(True)
        self.body_label.setWordWrap(True)
        for label, source in (
            (self.headline_label, "Closing Substitute..."),
            (self.body_label, "Please wait a moment."),
        ):
            set_localized_text(
                label,
                source,
                property_setter=partial(self._set_progress_text, label),
            )

    def _set_progress_text(self, label: QLabel, text: str) -> None:
        """Fit the standard layout after each localized label update."""

        label.setText(text)
        self.textLayout.invalidate()
        self.vBoxLayout.invalidate()
        width = 360
        height = max(
            self.vBoxLayout.minimumSize().height(),
            self.vBoxLayout.totalHeightForWidth(width),
        )
        self.setFixedSize(QSize(width, height))
        self.vBoxLayout.activate()

    def allow_close(self) -> None:
        """Permit the dialog to close after shutdown completes or is bypassed."""

        self._allow_close = True

    def done(self, result: int) -> None:
        """Keep hidden Fluent actions inert until the coordinator releases the UI."""

        if self._allow_close:
            super().done(result)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Block user-initiated closes while shutdown is still in progress."""

        if not self._allow_close:
            event.ignore()
            return
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Ignore Escape while shutdown is still active."""

        if not self._allow_close and event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)
