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

"""Tests for the shutdown progress dialog contract."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTranslator
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import Dialog, Theme  # type: ignore[import-untyped]

from substitute.presentation.shell.shutdown_progress_dialog import (
    ShutdownProgressDialog,
)
from tests.support.qt.lifecycle import destroy_qt_object, ensure_qt_application
from tests.support.qt.semantic_wait import wait_for_qt_condition
from tests.presentation.theme.support import fluent_theme, is_qfluent_managed


@pytest.fixture(params=[False, True], ids=["parentless", "parented"])
def shutdown_progress_dialog(
    request: pytest.FixtureRequest,
) -> Iterator[ShutdownProgressDialog]:
    """Create one dialog with explicit application and teardown ownership."""

    application = ensure_qt_application()
    parent = QWidget() if request.param else None
    if parent is not None:
        parent.resize(640, 480)
        parent.show()
    dialog = ShutdownProgressDialog(parent)
    try:
        yield dialog
    finally:
        destroy_qt_object(dialog)
        if parent is not None:
            destroy_qt_object(parent)
        del application


def test_shutdown_progress_dialog_matches_required_copy(
    shutdown_progress_dialog: ShutdownProgressDialog,
) -> None:
    """The dialog should expose only the fixed in-progress shutdown copy."""

    dialog = shutdown_progress_dialog

    assert dialog.windowTitle() == "Closing Substitute"
    assert dialog.headline_label.text() == "Closing Substitute..."
    assert dialog.body_label.text() == "Please wait a moment."
    assert dialog.windowFlags() & Qt.WindowType.WindowCloseButtonHint == 0
    assert dialog.isModal() is True


def test_shutdown_progress_dialog_has_no_failure_state_api(
    shutdown_progress_dialog: ShutdownProgressDialog,
) -> None:
    """The dialog should not expose any failure or detail mutation surface."""

    dialog = shutdown_progress_dialog

    assert hasattr(dialog, "show_failure_state") is False
    assert hasattr(dialog, "set_detail_text") is False


def test_shutdown_progress_dialog_blocks_close_until_allowed(
    shutdown_progress_dialog: ShutdownProgressDialog,
) -> None:
    """The dialog should stay open until the coordinator explicitly allows close."""

    dialog = shutdown_progress_dialog
    dialog.show()
    assert dialog.isVisible() is True

    dialog.close()
    assert dialog.isVisible() is True

    dialog.allow_close()
    dialog.close()
    assert dialog.isVisible() is False


def test_shutdown_progress_dialog_blocks_escape_until_allowed(
    shutdown_progress_dialog: ShutdownProgressDialog,
) -> None:
    """Ignore Escape while shutdown is active and honor it after completion."""

    dialog = shutdown_progress_dialog
    dialog.show()

    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.isVisible() is True

    dialog.allow_close()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.isVisible() is False


def test_shutdown_progress_uses_the_shared_fluent_dialog(
    shutdown_progress_dialog: ShutdownProgressDialog,
) -> None:
    """Cleanup progress should use Fluent chrome without adding cancellation."""

    assert isinstance(shutdown_progress_dialog, Dialog)


@pytest.mark.parametrize("action", ["accept", "reject", "done", "yes", "cancel"])
def test_fluent_actions_cannot_release_cleanup_ownership(
    shutdown_progress_dialog: ShutdownProgressDialog, action: str
) -> None:
    """Inherited dialog actions must not bypass the coordinator's close permission."""

    dialog = shutdown_progress_dialog
    finished = QSignalSpy(dialog.finished)
    dialog.show()
    assert dialog.isWindow()
    assert dialog.windowModality() is Qt.WindowModality.ApplicationModal
    assert not dialog.buttonGroup.isVisible()
    assert not dialog.yesButton.isVisible()
    assert not dialog.cancelButton.isVisible()
    if action == "done":
        dialog.done(1)
    elif action == "accept":
        dialog.accept()
    elif action == "reject":
        dialog.reject()
    elif action == "yes":
        dialog.yesButton.click()
    else:
        dialog.cancelButton.click()
    assert dialog.isVisible()
    assert finished.count() == 0
    dialog.allow_close()
    assert dialog.close()
    assert not dialog.isVisible()
    assert finished.count() == 1


@pytest.mark.parametrize("theme", [Theme.DARK, Theme.LIGHT])
def test_progress_uses_shared_theme_and_readable_copy(
    qt_application_owner: QApplication, theme: Theme
) -> None:
    """Both Fluent palettes render the noninteractive progress content."""

    with fluent_theme(theme):
        dialog = ShutdownProgressDialog()
        try:
            dialog.show()
            assert is_qfluent_managed(dialog)
            assert not dialog.grab().isNull()
            for label in (dialog.headline_label, dialog.body_label):
                assert dialog.rect().contains(label.geometry())
                assert label.height() >= label.heightForWidth(label.width())
            assert not dialog.buttonGroup.isVisible()
        finally:
            destroy_qt_object(dialog)


class _ExpandedShutdownTranslator(QTranslator):
    """Provide deliberately long application copy through the Qt translation API."""

    def isEmpty(self) -> bool:
        """Expose the fixture catalog as populated to Qt."""

        return False

    def translate(
        self,
        context: str,
        source_text: str,
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str:
        """Expand only the two progress labels, retaining exact source identity."""

        del disambiguation, n
        if context == "AppText" and source_text in {
            "Closing Substitute...",
            "Please wait a moment.",
        }:
            return source_text + " " + "A longer translated phrase. " * 6
        return ""


@pytest.mark.parametrize("expanded", [False, True], ids=["spanish", "expanded-copy"])
def test_live_localization_keeps_all_progress_text_visible(
    shutdown_progress_dialog: ShutdownProgressDialog,
    qt_application_owner: QApplication,
    expanded: bool,
) -> None:
    """Changing the catalog must reflow fixed progress copy without clipping it."""

    dialog = shutdown_progress_dialog
    dialog.show()
    translator = _ExpandedShutdownTranslator() if expanded else QTranslator()
    if not expanded:
        root = Path(__file__).resolve().parents[4]
        assert translator.load(
            str(
                root / "substitute/presentation/resources/i18n/sugarsubstitute_es_ES.qm"
            )
        )
    before = dialog.headline_label.text()
    qt_application_owner.installTranslator(translator)
    try:
        wait_for_qt_condition(lambda: dialog.headline_label.text() != before)
        wait_for_qt_condition(
            lambda: all(
                label.height() >= label.heightForWidth(label.width())
                for label in (dialog.headline_label, dialog.body_label)
            ),
            description="translated progress layout",
        )
        for label in (dialog.headline_label, dialog.body_label):
            assert dialog.rect().contains(label.geometry())
            assert label.height() >= label.heightForWidth(label.width())
        assert dialog.width() <= 640
        assert dialog.height() <= 480
        assert not dialog.buttonGroup.isVisible()
    finally:
        qt_application_owner.removeTranslator(translator)
