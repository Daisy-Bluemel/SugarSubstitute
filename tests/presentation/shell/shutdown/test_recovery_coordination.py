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

"""Prove real recovery actions retain coordinator ownership during timed-out work."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QWidget

from substitute.app.bootstrap.lifecycle import ManagedComfyCleanupResult
from substitute.app.bootstrap.shutdown_coordinator import ShutdownCoordinator
from substitute.presentation.shell.shutdown_progress_dialog import (
    ShutdownProgressDialog,
)
from substitute.presentation.shell.shutdown_recovery_dialog import (
    ShutdownRecoveryDialog,
)
from tests.support.execution.testing import QueuedTaskSubmitter
from tests.support.qt.lifecycle import destroy_qt_object, widget_root_scope


@dataclass
class _ExitRequests:
    """Record application-exit effects without quitting the test QApplication."""

    effects: list[str] = field(default_factory=list)

    def quit(self) -> None:
        """Record final exit after the coordinator has closed recovery."""

        self.effects.append("quit")

    def bypass_cleanup(self) -> None:
        """Record explicit approval to leave the outstanding cleanup behind."""

        self.effects.append("bypass")


@dataclass(frozen=True)
class _RecoveryComposition:
    """Retain the real dialog composition and its controlled execution boundary."""

    coordinator: ShutdownCoordinator
    submitter: QueuedTaskSubmitter
    exit_requests: _ExitRequests
    progress_dialogs: list[ShutdownProgressDialog]
    recovery_dialogs: list[ShutdownRecoveryDialog]
    parent: QWidget | None


@pytest.fixture(params=(False, True), ids=("parentless", "parented"))
def recovery_composition(
    request: pytest.FixtureRequest,
) -> Iterator[_RecoveryComposition]:
    """Own widgets, coordinator timers and pending work without real worker timing."""

    with widget_root_scope() as widgets:
        parent = widgets.own(QWidget()) if request.param else None
        if parent is not None:
            parent.show()
        submitter = QueuedTaskSubmitter()
        exit_requests = _ExitRequests()
        progress_dialogs: list[ShutdownProgressDialog] = []
        recovery_dialogs: list[ShutdownRecoveryDialog] = []

        def progress_factory(parent: QWidget | None) -> ShutdownProgressDialog:
            """Capture each production progress surface for lifecycle assertions."""

            dialog = widgets.own(ShutdownProgressDialog(parent))
            progress_dialogs.append(dialog)
            return dialog

        def recovery_factory(parent: QWidget | None) -> ShutdownRecoveryDialog:
            """Capture each production recovery surface without replacing its wiring."""

            dialog = widgets.own(ShutdownRecoveryDialog(parent))
            recovery_dialogs.append(dialog)
            return dialog

        def cleanup() -> ManagedComfyCleanupResult:
            """Require the external execution boundary to remain manually controlled."""

            pytest.fail("The queued cleanup must not execute during this UI contract.")

        coordinator = ShutdownCoordinator(
            app=exit_requests,
            cleanup=cleanup,
            cleanup_submitter=submitter,
            skip_cleanup_on_force_close=exit_requests.bypass_cleanup,
            progress_dialog_factory=progress_factory,
            recovery_dialog_factory=recovery_factory,
        )
        try:
            yield _RecoveryComposition(
                coordinator,
                submitter,
                exit_requests,
                progress_dialogs,
                recovery_dialogs,
                parent,
            )
        finally:
            for handle in submitter.handles:
                if not handle.is_finished:
                    handle.cancel(reason="recovery_composition_teardown")
            destroy_qt_object(coordinator)


def test_recovery_retry_retains_active_task_until_explicit_force_close(
    recovery_composition: _RecoveryComposition,
) -> None:
    """Ignored retries must leave recovery visible; force-close exits exactly once."""

    composition = recovery_composition
    coordinator = composition.coordinator
    coordinator.request_shutdown(composition.parent)
    assert len(composition.progress_dialogs) == 1
    progress = composition.progress_dialogs[0]
    assert progress.isVisible() is True
    assert len(composition.submitter.handles) == 1
    pending = composition.submitter.handles[0]
    assert pending.is_finished is False

    timeout = coordinator.findChild(QTimer)
    assert timeout is not None
    assert timeout.isActive() is True
    timeout.stop()
    timeout.timeout.emit()

    assert progress.isVisible() is False
    assert len(composition.recovery_dialogs) == 1
    recovery = composition.recovery_dialogs[0]
    finished = QSignalSpy(recovery.finished)
    assert recovery.isVisible() is True
    for _ in range(3):
        recovery.retry_button.click()
        QTest.keyClick(recovery, Qt.Key.Key_Return)
        assert recovery.isVisible() is True
        assert coordinator.shutdown_in_progress is True
        assert composition.submitter.handles == (pending,)
        assert pending.is_finished is False
        assert composition.exit_requests.effects == []
        assert finished.count() == 0

    for _ in range(3):
        recovery.force_close_button.click()

    assert recovery.isVisible() is False
    assert progress.isVisible() is False
    assert finished.count() == 1
    assert coordinator.shutdown_in_progress is False
    assert composition.exit_requests.effects == ["bypass", "quit"]
    assert composition.submitter.handles == (pending,)
    assert pending.is_finished is True
    assert len(composition.progress_dialogs) == 1
    assert len(composition.recovery_dialogs) == 1
