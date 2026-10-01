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

"""Verify Fluent dirty-work decisions, keyboard safety, and localized content."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTranslator
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget
import pytest
from qfluentwidgets import Theme  # type: ignore[import-untyped]
from shiboken6 import delete

from substitute.application.workflows.unsaved_work_service import UnsavedWorkDecision
from substitute.presentation.dialogs.unsaved_work_dialog import UnsavedWorkDialog
from tests.support.qt.semantic_wait import wait_for_qt_condition, wait_for_qt_signal
from tests.presentation.theme.support import fluent_theme


@pytest.fixture
def dialog(qt_application_owner: QApplication) -> Iterator[UnsavedWorkDialog]:
    """Own only the frame, modal, timers, and animations created for this case."""

    parent = QWidget()
    parent.resize(900, 640)
    parent.show()
    modal = UnsavedWorkDialog(parent=parent, workflow_name="Portrait <b>Study</b>")
    modal.show()
    wait_for_qt_condition(modal.yesButton.hasFocus, description="default Save focus")
    try:
        yield modal
    finally:
        delete(parent)


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("save", UnsavedWorkDecision.SAVE),
        ("discard", UnsavedWorkDecision.DISCARD),
        ("cancel", UnsavedWorkDecision.CANCEL),
        ("escape", UnsavedWorkDecision.CANCEL),
        ("close", UnsavedWorkDecision.CANCEL),
        ("return", UnsavedWorkDecision.SAVE),
        ("tab-return", UnsavedWorkDecision.DISCARD),
        ("two-tabs-return", UnsavedWorkDecision.CANCEL),
    ],
)
def test_user_actions_return_distinct_decisions(
    dialog: UnsavedWorkDialog,
    action: str,
    expected: UnsavedWorkDecision,
) -> None:
    """Only Save and the explicit Don't Save action may continue closure."""

    finished = QSignalSpy(dialog.finished)
    assert dialog.yesButton.isDefault()
    assert dialog.yesButton.hasFocus()
    if action in {"save", "discard", "cancel"}:
        button = {
            "save": dialog.yesButton,
            "discard": dialog.discard_button,
            "cancel": dialog.cancelButton,
        }[action]
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    elif action == "close":
        dialog.close()
    else:
        if action in {"tab-return", "two-tabs-return"}:
            QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Tab)
        if action == "two-tabs-return":
            QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Tab)
        key = Qt.Key.Key_Escape if action == "escape" else Qt.Key.Key_Return
        QTest.keyClick(dialog.focusWidget(), key)
    wait_for_qt_signal(finished)
    assert finished.count() == 1
    assert dialog.decision is expected
    assert not dialog.isVisible()


def test_mask_click_keeps_the_choice_open(dialog: UnsavedWorkDialog) -> None:
    """Clicking outside the card must never discard or accept document edits."""

    finished = QSignalSpy(dialog.finished)
    QTest.mouseClick(dialog.windowMask, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    assert dialog.isVisible()
    assert dialog.decision is UnsavedWorkDecision.CANCEL
    assert finished.count() == 0
    QTest.keyClick(dialog.yesButton, Qt.Key.Key_Escape)
    wait_for_qt_signal(finished)
    assert dialog.decision is UnsavedWorkDecision.CANCEL


@pytest.mark.parametrize("first", ["save", "discard", "cancel"])
def test_dismissal_keeps_first_decision_during_fade(
    dialog: UnsavedWorkDialog, first: str
) -> None:
    """Late keyboard or button delivery cannot overwrite a choice during fade-out."""

    finished = QSignalSpy(dialog.finished)
    button, expected = {
        "save": (dialog.yesButton, UnsavedWorkDecision.SAVE),
        "discard": (dialog.discard_button, UnsavedWorkDecision.DISCARD),
        "cancel": (dialog.cancelButton, UnsavedWorkDecision.CANCEL),
    }[first]
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert not dialog.buttonGroup.isEnabled()
    dialog.reject()
    dialog.accept()
    dialog.discard_button.click()
    wait_for_qt_signal(finished)
    assert finished.count() == 1
    assert dialog.decision is expected


@pytest.mark.parametrize("theme", [Theme.DARK, Theme.LIGHT])
def test_shared_surface_keeps_actions_and_plain_authored_name(
    qt_application_owner: QApplication, theme: Theme
) -> None:
    """Both shared palettes retain usable controls and literal workflow names."""

    with fluent_theme(theme):
        parent = QWidget()
        parent.resize(900, 640)
        parent.show()
        dialog = UnsavedWorkDialog(parent=parent, workflow_name="Portrait <b>Study</b>")
        try:
            dialog.show()
            wait_for_qt_condition(dialog.isVisible)
            assert dialog.message_label.text() == (
                "Save changes to “Portrait <b>Study</b>” before continuing?"
            )
            assert dialog.message_label.textFormat() is Qt.TextFormat.PlainText
            assert dialog.windowMask.geometry() == parent.rect()
            assert [
                dialog.yesButton.text(),
                dialog.discard_button.text(),
                dialog.cancelButton.text(),
            ] == ["Save", "Don't Save", "Cancel"]
            for button in (
                dialog.yesButton,
                dialog.discard_button,
                dialog.cancelButton,
            ):
                assert button.isVisible() and button.isEnabled()
                assert dialog.buttonGroup.rect().contains(button.geometry())
                assert button.width() >= button.sizeHint().width()
            assert not dialog.widget.grab().isNull()
        finally:
            delete(parent)


@pytest.mark.parametrize(
    ("locale", "title", "save", "discard", "cancel"),
    [
        ("es_ES", "Trabajo sin guardar", "Guardar", "No guardar", "Cancelar"),
        ("ja_JP", "未保存の作業", "保存", "保存しない", "キャンセル"),
    ],
)
def test_live_translation_preserves_outcomes_and_authored_name(
    dialog: UnsavedWorkDialog,
    qt_application_owner: QApplication,
    locale: str,
    title: str,
    save: str,
    discard: str,
    cancel: str,
) -> None:
    """Installed catalogs retranslate modal chrome without interpreting the name."""

    root = Path(__file__).resolve().parents[4]
    translator = QTranslator()
    assert translator.load(
        str(
            root / f"substitute/presentation/resources/i18n/sugarsubstitute_{locale}.qm"
        )
    )
    qt_application_owner.installTranslator(translator)
    try:
        wait_for_qt_condition(lambda: dialog.title_label.text() == title)
        assert dialog.windowTitle() == title
        assert "Portrait <b>Study</b>" in dialog.message_label.text()
        assert "%1" not in dialog.message_label.text()
        assert [
            dialog.yesButton.text(),
            dialog.discard_button.text(),
            dialog.cancelButton.text(),
        ] == [save, discard, cancel]
        assert dialog.decision is UnsavedWorkDecision.CANCEL
        finished = QSignalSpy(dialog.finished)
        QTest.mouseClick(dialog.cancelButton, Qt.MouseButton.LeftButton)
        wait_for_qt_signal(finished)
        assert dialog.decision is UnsavedWorkDecision.CANCEL
    finally:
        qt_application_owner.removeTranslator(translator)


@pytest.mark.parametrize("size", [(900, 640), (560, 360)])
@pytest.mark.parametrize(
    "name", ["Portrait Study " * 16, "非常に長いワークフロー名" * 16]
)
def test_long_workflow_name_keeps_content_and_actions_inside_owner(
    qt_application_owner: QApplication, size: tuple[int, int], name: str
) -> None:
    """Wrapping a long document name must not hide text or decision buttons."""

    parent = QWidget()
    parent.resize(*size)
    parent.show()
    dialog = UnsavedWorkDialog(parent=parent, workflow_name=name)
    try:
        dialog.show()
        wait_for_qt_condition(dialog.yesButton.hasFocus)
        assert dialog.rect().contains(dialog.widget.geometry())
        assert name in dialog.message_label.text()
        for label in (dialog.title_label, dialog.message_label, dialog.recovery_label):
            assert dialog.widget.rect().contains(label.geometry())
            assert label.height() >= label.heightForWidth(label.width())
        assert dialog.widget.rect().contains(dialog.buttonGroup.geometry())
        for button in (dialog.yesButton, dialog.discard_button, dialog.cancelButton):
            assert dialog.buttonGroup.rect().contains(button.geometry())
            assert button.width() >= button.sizeHint().width()
        finished = QSignalSpy(dialog.finished)
        QTest.mouseClick(dialog.cancelButton, Qt.MouseButton.LeftButton)
        wait_for_qt_signal(finished)
        assert dialog.decision is UnsavedWorkDecision.CANCEL
    finally:
        delete(parent)
