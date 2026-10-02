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

"""Tests for the shutdown recovery dialog contract."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QWidget

from substitute.app.bootstrap.lifecycle import (
    ManagedComfyCleanupOutcome,
    ManagedComfyCleanupResult,
)
from substitute.presentation.shell.shutdown_recovery_dialog import (
    ShutdownRecoveryDialog,
)
from tests.support.qt.lifecycle import destroy_qt_object, ensure_qt_application


pytestmark = pytest.mark.usefixtures("qt_clipboard_owner")


@pytest.fixture(params=(False, True), ids=("parentless", "parented"))
def shutdown_recovery_dialog(
    request: pytest.FixtureRequest,
) -> Iterator[ShutdownRecoveryDialog]:
    """Exercise both supported parent lifecycles with exact teardown owners."""

    application = ensure_qt_application()
    parent = QWidget() if request.param else None
    if parent is not None:
        parent.show()
    dialog = ShutdownRecoveryDialog(parent)
    yield dialog
    destroy_qt_object(dialog)
    if parent is not None:
        destroy_qt_object(parent)
    del application


def test_shutdown_recovery_dialog_uncertain_copy_matches_specification(
    shutdown_recovery_dialog: ShutdownRecoveryDialog,
) -> None:
    """The uncertain shutdown copy should match the required UX contract."""

    dialog = shutdown_recovery_dialog

    dialog.show_uncertain_outcome(
        _cleanup_result(ManagedComfyCleanupOutcome.UNCERTAIN_SUCCESS)
    )

    assert dialog.windowTitle() == "Could Not Finish Closing"
    assert (
        dialog.primary_label.text()
        == "Substitute could not confirm that shutdown finished."
    )
    assert (
        dialog.secondary_label.text()
        == "You can retry shutdown or close Substitute anyway."
    )


def test_shutdown_recovery_dialog_failure_copy_matches_specification(
    shutdown_recovery_dialog: ShutdownRecoveryDialog,
) -> None:
    """The failed shutdown copy should match the required UX contract."""

    dialog = shutdown_recovery_dialog

    dialog.show_failed_outcome(_cleanup_result(ManagedComfyCleanupOutcome.FAILURE))

    assert (
        dialog.primary_label.text() == "Substitute could not finish closing completely."
    )
    assert (
        dialog.secondary_label.text()
        == "You can retry shutdown or close Substitute anyway."
    )


def test_shutdown_recovery_dialog_retry_is_default_button(
    shutdown_recovery_dialog: ShutdownRecoveryDialog,
) -> None:
    """Enter should invoke the default retry callback without dismissing recovery."""

    dialog = shutdown_recovery_dialog
    calls: list[str] = []
    dialog.set_retry_callback(lambda: calls.append("retry"))
    dialog.set_force_close_callback(lambda: calls.append("force_close"))
    dialog.show_failed_outcome(_cleanup_result(ManagedComfyCleanupOutcome.FAILURE))
    dialog.show()

    assert dialog.retry_button.isDefault() is True
    QTest.keyClick(dialog, Qt.Key.Key_Return)
    assert calls == ["retry"]
    assert dialog.isVisible() is True


def test_shutdown_recovery_dialog_blocks_close_button_and_escape(
    shutdown_recovery_dialog: ShutdownRecoveryDialog,
) -> None:
    """The dialog should stay open until the coordinator handles an explicit action."""

    dialog = shutdown_recovery_dialog
    finished = QSignalSpy(dialog.finished)
    dialog.show_failed_outcome(_cleanup_result(ManagedComfyCleanupOutcome.FAILURE))
    dialog.show()

    assert dialog.windowFlags() & Qt.WindowType.WindowCloseButtonHint == 0
    assert dialog.isModal() is True

    dialog.close()
    assert dialog.isVisible() is True

    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.isVisible() is True
    assert finished.count() == 0

    dialog.allow_close()
    dialog.close()
    assert dialog.isVisible() is False
    assert finished.count() == 1
    assert finished.at(0) == [QDialog.DialogCode.Rejected]


@pytest.mark.parametrize(
    ("method", "result"),
    (
        ("accept", QDialog.DialogCode.Accepted),
        ("reject", QDialog.DialogCode.Rejected),
        ("done", 27),
    ),
)
def test_shutdown_recovery_dialog_programmatic_completion_is_immediate(
    shutdown_recovery_dialog: ShutdownRecoveryDialog,
    method: str,
    result: int,
) -> None:
    """Preserve direct QDialog completion independently of the user-close guard."""

    dialog = shutdown_recovery_dialog
    finished = QSignalSpy(dialog.finished)
    accepted = QSignalSpy(dialog.accepted)
    rejected = QSignalSpy(dialog.rejected)
    calls: list[str] = []
    dialog.set_retry_callback(lambda: calls.append("retry"))
    dialog.set_force_close_callback(lambda: calls.append("force_close"))
    dialog.show_failed_outcome(_cleanup_result(ManagedComfyCleanupOutcome.FAILURE))
    dialog.show()

    if method == "accept":
        dialog.accept()
    elif method == "reject":
        dialog.reject()
    else:
        dialog.done(result)

    assert dialog.isVisible() is False
    assert dialog.result() == result
    assert finished.count() == 1
    assert finished.at(0) == [result]
    assert accepted.count() == int(result == QDialog.DialogCode.Accepted)
    assert rejected.count() == int(result == QDialog.DialogCode.Rejected)
    assert calls == []


def test_shutdown_recovery_dialog_hides_details_by_default(
    shutdown_recovery_dialog: ShutdownRecoveryDialog,
) -> None:
    """Diagnostic details should stay hidden until the user explicitly reveals them."""

    dialog = shutdown_recovery_dialog
    dialog.show_uncertain_outcome(
        _cleanup_result(ManagedComfyCleanupOutcome.UNCERTAIN_SUCCESS)
    )

    assert dialog.details_editor.isHidden() is True
    assert dialog.details_toggle_button.text() == "Show Details"


def test_shutdown_recovery_dialog_details_are_selectable_and_copyable(
    shutdown_recovery_dialog: ShutdownRecoveryDialog,
) -> None:
    """The complete support report should be selectable and copied without alteration."""

    dialog = shutdown_recovery_dialog
    dialog.show_uncertain_outcome(
        _cleanup_result(ManagedComfyCleanupOutcome.UNCERTAIN_SUCCESS)
    )
    dialog.show()

    dialog.details_toggle_button.click()

    assert isinstance(dialog.details_editor, QPlainTextEdit)
    assert dialog.details_editor.isReadOnly() is True
    assert dialog.details_editor.isVisible() is True
    assert dialog.details_editor.textCursor().position() == 0
    assert dialog.details_toggle_button.text() == "Hide Details"
    detail_text = dialog.details_editor.toPlainText()
    assert "Support code: SS-SHUTDOWN-NATIVE-EXIT-TIMEOUT" in detail_text
    assert "Responsibility boundary: Managed runtime or operating-system" in detail_text
    assert "Diagnostic evidence:\nnative wait timed out" in detail_text

    dialog.copy_details_button.click()
    assert ensure_qt_application().clipboard().text() == detail_text

    dialog.details_toggle_button.click()
    assert dialog.details_editor.isHidden() is True
    assert dialog.details_toggle_button.text() == "Show Details"


def test_shutdown_recovery_dialog_actions_delegate_to_coordinator(
    shutdown_recovery_dialog: ShutdownRecoveryDialog,
) -> None:
    """Rapid explicit actions should remain coordinator-owned without dismissal."""

    dialog = shutdown_recovery_dialog
    finished = QSignalSpy(dialog.finished)
    calls: list[str] = []

    dialog.set_retry_callback(lambda: calls.append("retry"))
    dialog.set_force_close_callback(lambda: calls.append("force_close"))
    dialog.show_failed_outcome(_cleanup_result(ManagedComfyCleanupOutcome.FAILURE))
    dialog.show()
    for _ in range(3):
        dialog.retry_button.click()
        assert dialog.isVisible() is True
        dialog.force_close_button.click()
        assert dialog.isVisible() is True

    assert calls == ["retry", "force_close"] * 3
    assert finished.count() == 0


@pytest.mark.parametrize(
    "next_outcome",
    (ManagedComfyCleanupOutcome.FAILURE, ManagedComfyCleanupOutcome.UNCERTAIN_SUCCESS),
)
def test_shutdown_recovery_dialog_new_outcome_resets_and_copies_details(
    shutdown_recovery_dialog: ShutdownRecoveryDialog,
    next_outcome: ManagedComfyCleanupOutcome,
) -> None:
    """A replacement outcome should collapse details and replace copied evidence."""

    dialog = shutdown_recovery_dialog
    dialog.show_uncertain_outcome(
        _cleanup_result(ManagedComfyCleanupOutcome.UNCERTAIN_SUCCESS)
    )
    dialog.show()
    dialog.details_toggle_button.click()
    dialog.details_editor.selectAll()
    assert dialog.details_editor.textCursor().hasSelection() is True

    result = _cleanup_result(next_outcome)
    if next_outcome is ManagedComfyCleanupOutcome.FAILURE:
        dialog.show_failed_outcome(result)
        expected_evidence = "The termination command timed out before completion."
    else:
        dialog.show_uncertain_outcome(result)
        expected_evidence = (
            "Shutdown could not be confirmed before the verification timeout."
        )

    assert dialog.details_editor.isHidden() is True
    assert dialog.details_toggle_button.isChecked() is False
    assert dialog.details_toggle_button.text() == "Show Details"
    assert dialog.details_editor.textCursor().position() == 0
    assert dialog.details_editor.textCursor().hasSelection() is False
    assert expected_evidence in dialog.details_editor.toPlainText()
    dialog.copy_details_button.click()
    assert (
        ensure_qt_application().clipboard().text()
        == dialog.details_editor.toPlainText()
    )
    assert dialog.isVisible() is True


def _cleanup_result(
    outcome: ManagedComfyCleanupOutcome,
) -> ManagedComfyCleanupResult:
    """Build one shutdown result carrying support-relevant evidence."""

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
