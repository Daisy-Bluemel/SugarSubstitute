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

"""Display the single recovery surface for uncertain or failed shutdown."""

from __future__ import annotations

from sugarsubstitute_shared.presentation.localization import (
    ApplicationText,
    apply_application_text,
    app_text,
    render_application_text,
    set_localized_text,
    set_localized_window_title,
)
from substitute.presentation.localization import (
    LocalizedBodyLabel,
    LocalizedPushButton,
)

from collections.abc import Callable

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLayout,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import Dialog, PlainTextEdit  # type: ignore[import-untyped]

from substitute.app.bootstrap.lifecycle import ManagedComfyCleanupResult
from substitute.app.bootstrap.shutdown_recovery_report import (
    build_shutdown_recovery_report,
)


class ShutdownRecoveryDialog(Dialog):  # type: ignore[misc]
    """Render the retry-or-force-close recovery surface."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the recovery dialog widgets and button wiring."""

        self._allow_close = False
        super().__init__("", "", parent)
        set_localized_window_title(self, "Could Not Finish Closing")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setTitleBarVisible(False)
        self.vBoxLayout.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        self.setMinimumSize(600, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setResizeEnabled(True)

        self.primary_label: QLabel = self.titleLabel
        self.secondary_label: QLabel = self.contentLabel
        self.warning_label = LocalizedBodyLabel(
            app_text("If you close anyway, a background service may still be running."),
            self,
        )
        self.details_toggle_button = LocalizedPushButton(app_text("Show Details"), self)
        self.details_toggle_button.setCheckable(True)
        self.copy_details_button = LocalizedPushButton(app_text("Copy Details"), self)
        self.details_editor = PlainTextEdit(self)
        self.retry_button = self.yesButton
        self.force_close_button = self.cancelButton
        # Fluent's stock actions dismiss before notifying their consumer. Recovery
        # must stay open when the coordinator declines a retry of active cleanup.
        self.retry_button.clicked.disconnect()
        self.force_close_button.clicked.disconnect()
        set_localized_text(self.retry_button, "Retry")
        set_localized_text(self.force_close_button, "Close Substitute Anyway")

        self.primary_label.setWordWrap(True)
        self.secondary_label.setWordWrap(True)
        self.warning_label.setWordWrap(True)
        self.details_editor.setReadOnly(True)
        self.details_editor.setMinimumHeight(220)
        self.details_editor.setTabChangesFocus(True)
        self.details_editor.hide()
        self.retry_button.setDefault(True)
        self.details_toggle_button.clicked.connect(self._toggle_details_visibility)
        self.copy_details_button.clicked.connect(self._copy_details)

        details_button_row = QHBoxLayout()
        details_button_row.addWidget(self.details_toggle_button)
        details_button_row.addStretch(1)
        details_button_row.addWidget(self.copy_details_button)

        self.textLayout.addWidget(self.warning_label)
        self.textLayout.addLayout(details_button_row)
        self.textLayout.addWidget(self.details_editor)
        self._fit_layout()

    def event(self, event: QEvent) -> bool:
        """Refit wrapped recovery copy when localization changes the shared layout."""

        handled = bool(super().event(event))
        if event.type() == QEvent.Type.LayoutRequest:
            self._fit_layout()
        return handled

    def _fit_layout(self) -> None:
        """Fit wrapped text and details without QWidget's two-thirds-screen cap."""

        layout: QVBoxLayout = self.vBoxLayout
        width = max(600, layout.minimumSize().width())
        height = max(layout.minimumSize().height(), layout.totalHeightForWidth(width))
        self.resize(QSize(width, height))
        layout.activate()

    def show_uncertain_outcome(self, result: ManagedComfyCleanupResult) -> None:
        """Render the recovery copy for an uncertain shutdown outcome."""

        self._set_copy(
            primary_text=app_text(
                "Substitute could not confirm that shutdown finished."
            ),
            secondary_text=app_text(
                "You can retry shutdown or close Substitute anyway."
            ),
            detail_text=build_shutdown_recovery_report(result),
        )

    def show_failed_outcome(self, result: ManagedComfyCleanupResult) -> None:
        """Render the recovery copy for a failed shutdown outcome."""

        self._set_copy(
            primary_text=app_text("Substitute could not finish closing completely."),
            secondary_text=app_text(
                "You can retry shutdown or close Substitute anyway."
            ),
            detail_text=build_shutdown_recovery_report(result),
        )

    def set_retry_callback(self, callback: Callable[[], None]) -> None:
        """Connect the retry action to one coordinator callback."""

        self.retry_button.clicked.connect(callback)

    def set_force_close_callback(self, callback: Callable[[], None]) -> None:
        """Connect the force-close action to one coordinator callback."""

        self.force_close_button.clicked.connect(callback)

    def allow_close(self) -> None:
        """Permit the dialog to close after one explicit coordinator action."""

        self._allow_close = True

    def closeEvent(self, event: QCloseEvent) -> None:
        """Block user-initiated closes while the dialog is active."""

        if not self._allow_close:
            event.ignore()
            return
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Ignore Escape so the dialog can only close through explicit actions."""

        if not self._allow_close and event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)

    def _set_copy(
        self,
        *,
        primary_text: ApplicationText,
        secondary_text: ApplicationText,
        detail_text: ApplicationText,
    ) -> None:
        """Apply one recovery copy set and reset the details expander."""

        apply_application_text(self.primary_label, primary_text)
        apply_application_text(self.secondary_label, secondary_text)
        self.details_editor.setPlainText(render_application_text(detail_text))
        self.details_editor.moveCursor(QTextCursor.MoveOperation.Start)
        self.details_toggle_button.setChecked(False)
        set_localized_text(self.details_toggle_button, "Show Details")
        self.details_editor.hide()
        self._fit_layout()

    def _toggle_details_visibility(self) -> None:
        """Toggle the visibility of the sanitized detail text."""

        details_visible = self.details_toggle_button.isChecked()
        set_localized_text(
            self.details_toggle_button,
            "Hide Details" if details_visible else "Show Details",
        )
        self.details_editor.setVisible(details_visible)
        self._fit_layout()

    def _copy_details(self) -> None:
        """Copy the complete support report exactly as displayed."""

        QGuiApplication.clipboard().setText(self.details_editor.toPlainText())
