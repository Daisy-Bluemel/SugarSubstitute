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

"""Protect the shared Fluent shutdown recovery surface and translated layout."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, QTranslator
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import Dialog, PlainTextEdit, Theme  # type: ignore[import-untyped]

from substitute.app.bootstrap.lifecycle import (
    ManagedComfyCleanupOutcome,
    ManagedComfyCleanupResult,
)
from substitute.presentation.localization import LocalizedBodyLabel, LocalizedPushButton
from substitute.presentation.shell.shutdown_recovery_dialog import (
    ShutdownRecoveryDialog,
)
from tests.presentation.theme.support import fluent_theme, is_qfluent_managed
from tests.support.qt.lifecycle import destroy_qt_object
from tests.support.qt.semantic_wait import wait_for_qt_condition


@pytest.mark.parametrize("theme", [Theme.DARK, Theme.LIGHT])
def test_recovery_uses_shared_fluent_surface_and_controls(
    qt_application_owner: QApplication, theme: Theme
) -> None:
    """Recovery chrome and interactive controls must share application styling."""

    with fluent_theme(theme):
        dialog = ShutdownRecoveryDialog()
        try:
            dialog.show_uncertain_outcome(
                _cleanup_result(ManagedComfyCleanupOutcome.UNCERTAIN_SUCCESS)
            )
            dialog.show()
            assert isinstance(dialog, Dialog)
            assert dialog.primary_label is dialog.titleLabel
            assert dialog.secondary_label is dialog.contentLabel
            assert dialog.retry_button is dialog.yesButton
            assert dialog.force_close_button is dialog.cancelButton
            assert isinstance(dialog.warning_label, LocalizedBodyLabel)
            assert isinstance(dialog.details_toggle_button, LocalizedPushButton)
            assert isinstance(dialog.copy_details_button, LocalizedPushButton)
            assert isinstance(dialog.details_editor, PlainTextEdit)
            for widget in (
                dialog,
                dialog.retry_button,
                dialog.details_toggle_button,
                dialog.copy_details_button,
                dialog.details_editor,
            ):
                assert is_qfluent_managed(widget)
            _assert_readable_recovery(dialog)
            assert not dialog.grab().isNull()
        finally:
            destroy_qt_object(dialog)


class _ExpandedRecoveryTranslator(QTranslator):
    """Exercise application copy expansion without depending on catalog wording."""

    def isEmpty(self) -> bool:
        """Expose a populated catalog to Qt's live language-change dispatch."""

        return False

    def translate(
        self,
        context: str,
        source_text: str,
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str:
        """Expand only visible recovery copy through its production text owner."""

        del disambiguation, n
        if context != "AppText":
            return ""
        if source_text in {
            "Could Not Finish Closing",
            "Substitute could not confirm that shutdown finished.",
            "Substitute could not finish closing completely.",
            "You can retry shutdown or close Substitute anyway.",
            "If you close anyway, a background service may still be running.",
        }:
            return source_text + " A longer translated explanation." * 3
        if source_text in {
            "Retry",
            "Close Substitute Anyway",
            "Show Details",
            "Hide Details",
            "Copy Details",
        }:
            return source_text + " translated action"
        return ""


@pytest.mark.parametrize("theme", [Theme.DARK, Theme.LIGHT])
@pytest.mark.parametrize("expanded", [False, True], ids=["spanish", "expanded-copy"])
def test_live_localization_keeps_recovery_content_and_actions_readable(
    qt_application_owner: QApplication, theme: Theme, expanded: bool
) -> None:
    """Visible recovery copy must reflow around details after a live locale change."""

    with fluent_theme(theme):
        parent = QWidget()
        parent.resize(900, 700)
        parent.show()
        dialog = ShutdownRecoveryDialog(parent)
        translator = _ExpandedRecoveryTranslator() if expanded else QTranslator()
        try:
            if not expanded:
                root = Path(__file__).resolve().parents[4]
                assert translator.load(
                    str(
                        root
                        / "substitute/presentation/resources/i18n/sugarsubstitute_es_ES.qm"
                    )
                )
            dialog.show_failed_outcome(
                _cleanup_result(ManagedComfyCleanupOutcome.FAILURE)
            )
            dialog.show()
            wait_for_qt_condition(dialog.isVisible)
            _assert_readable_recovery(dialog)
            dialog.details_toggle_button.click()
            wait_for_qt_condition(dialog.details_editor.isVisible)
            _assert_readable_recovery(dialog)
            report = dialog.details_editor.toPlainText()
            before = _visible_copy(dialog)
            assert qt_application_owner.installTranslator(translator)
            wait_for_qt_condition(
                lambda: all(
                    current != previous
                    for current, previous in zip(
                        _visible_copy(dialog), before, strict=True
                    )
                ),
                description="all visible shutdown recovery copy retranslated",
            )
            wait_for_qt_condition(
                lambda: _recovery_text_fits(dialog),
                description="translated shutdown recovery labels and actions fit",
            )
            _assert_readable_recovery(dialog)
            assert dialog.details_editor.toPlainText() == report
            translated_hide = dialog.details_toggle_button.text()
            dialog.details_toggle_button.click()
            wait_for_qt_condition(dialog.details_editor.isHidden)
            wait_for_qt_condition(lambda: _recovery_text_fits(dialog))
            _assert_readable_recovery(dialog)
            assert dialog.details_toggle_button.text() != translated_hide
            dialog.details_toggle_button.click()
            wait_for_qt_condition(dialog.details_editor.isVisible)
            wait_for_qt_condition(lambda: _recovery_text_fits(dialog))
            _assert_readable_recovery(dialog)
            assert dialog.details_toggle_button.text() == translated_hide
            assert dialog.details_editor.toPlainText() == report
            assert not dialog.grab().isNull()
        finally:
            qt_application_owner.removeTranslator(translator)
            destroy_qt_object(dialog)
            destroy_qt_object(parent)


def _visible_copy(dialog: ShutdownRecoveryDialog) -> tuple[str, ...]:
    """Observe every localized recovery label and action independently."""

    return (
        dialog.windowTitle(),
        dialog.primary_label.text(),
        dialog.secondary_label.text(),
        dialog.warning_label.text(),
        dialog.retry_button.text(),
        dialog.force_close_button.text(),
        dialog.details_toggle_button.text(),
        dialog.copy_details_button.text(),
    )


def _recovery_text_fits(dialog: ShutdownRecoveryDialog) -> bool:
    """Identify settled text geometry without arbitrary event-loop pumping."""

    return all(
        label.height() >= label.heightForWidth(label.width())
        for label in (
            dialog.primary_label,
            dialog.secondary_label,
            dialog.warning_label,
        )
    ) and all(
        button.width() >= button.sizeHint().width()
        and button.height() >= button.sizeHint().height()
        for button in (
            dialog.retry_button,
            dialog.force_close_button,
            dialog.details_toggle_button,
            dialog.copy_details_button,
        )
    )


def _assert_readable_recovery(dialog: ShutdownRecoveryDialog) -> None:
    """Check content containment and intrinsic text fits across nested Fluent rows."""

    for label in (dialog.primary_label, dialog.secondary_label, dialog.warning_label):
        assert label.height() >= label.heightForWidth(label.width()), (
            label.text(),
            label.size(),
            label.heightForWidth(label.width()),
        )
    for button in (
        dialog.retry_button,
        dialog.force_close_button,
        dialog.details_toggle_button,
        dialog.copy_details_button,
    ):
        assert button.width() >= button.sizeHint().width(), (
            button.text(),
            button.size(),
            button.sizeHint(),
        )
        assert button.height() >= button.sizeHint().height(), (
            button.text(),
            button.size(),
            button.sizeHint(),
        )
    for widget in (
        dialog.primary_label,
        dialog.secondary_label,
        dialog.warning_label,
        dialog.retry_button,
        dialog.force_close_button,
        dialog.details_toggle_button,
        dialog.copy_details_button,
    ):
        assert widget.isVisible()
        bounds = QRect(widget.mapTo(dialog, QPoint()), widget.size())
        assert dialog.rect().contains(bounds)
    assert dialog.buttonGroup.isVisible()
    for button in (dialog.retry_button, dialog.force_close_button):
        assert dialog.buttonGroup.rect().contains(button.geometry())
    if dialog.details_editor.isVisible():
        editor = dialog.details_editor
        bounds = QRect(editor.mapTo(dialog, QPoint()), editor.size())
        assert dialog.rect().contains(bounds)
        assert editor.height() >= editor.minimumHeight()
        assert bounds.bottom() < dialog.buttonGroup.y()
    screen = dialog.screen()
    assert screen is not None
    assert dialog.width() <= screen.availableGeometry().width()
    assert dialog.height() <= screen.availableGeometry().height()


def _cleanup_result(
    outcome: ManagedComfyCleanupOutcome,
) -> ManagedComfyCleanupResult:
    """Provide real recovery content without mounting shutdown orchestration."""

    uncertain = outcome is ManagedComfyCleanupOutcome.UNCERTAIN_SUCCESS
    return ManagedComfyCleanupResult(
        cleanup_ran=True,
        outcome=outcome,
        managed_resource_present=True,
        live_process_present=True,
        metadata_present=True,
        used_persisted_metadata=False,
        termination_attempted=True,
        registry_cleared=False,
        pid=53792,
        host="127.0.0.1",
        port=8188,
        workspace=None,
        elapsed_ms=6734,
        taskkill_timeout=not uncertain,
        verification_timeout=uncertain,
        user_detail=(
            "Substitute could not confirm that shutdown finished."
            if uncertain
            else "Substitute could not finish closing completely."
        ),
        technical_detail=(
            "Shutdown could not be confirmed before the verification timeout."
            if uncertain
            else "The termination command timed out before completion."
        ),
        diagnostic_detail="native wait timed out",
    )
