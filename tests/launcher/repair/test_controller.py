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

"""Exercise queued repair work and user actions through the production controller."""

from __future__ import annotations

from pathlib import Path
import sys
from threading import Event

import pytest
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QThread
from PySide6.QtWidgets import QApplication, QPushButton

from launcher.sugarsubstitute_launcher.application.repair.models import RepairScope
from launcher.sugarsubstitute_launcher.application.repair.request import (
    PreparedRepairRequest,
)
from launcher.sugarsubstitute_launcher.ui.repair_controller import RepairController
from launcher.sugarsubstitute_launcher.ui.repair_window import RepairWindow
from launcher.sugarsubstitute_launcher.ui.repair_worker import RepairWorker
from tests.support.qt.semantic_wait import (
    wait_for_qt_condition,
    wait_for_queued_qt_turn,
)
from tests.support.qt.lifecycle import destroy_qt_object
from launcher.sugarsubstitute_launcher.repair_process_supervisor import (
    RepairProcessCancelled,
    RepairProcessSupervisor,
)
from sugarsubstitute_shared.session_recovery import (
    SessionRecoveryResult,
    SessionRecoveryState,
)
from sugarsubstitute_shared.installation_mutation import installation_mutation

_WORKER_COMPLETION_TIMEOUT_MS = 10_000


def _request(root: Path) -> PreparedRepairRequest:
    """Provide inert request metadata for the controlled worker boundary."""
    staging = root / ".repair/staging/1.2.3"
    return PreparedRepairRequest(
        root,
        RepairScope.APPLICATION,
        "1.2.3",
        "stable",
        "windows_x64",
        staging / "app",
        staging / "launcher",
        "a" * 64,
        "b" * 64,
    )


def _dispose(window: RepairWindow) -> None:
    """Wait for worker cleanup before disposing the native window and its children."""
    wait_for_qt_condition(
        lambda: not any(thread.isRunning() for thread in window.findChildren(QThread)),
        timeout_ms=_WORKER_COMPLETION_TIMEOUT_MS,
        description="repair worker cleanup",
        state=lambda: [thread.isRunning() for thread in window.findChildren(QThread)],
    )
    window.close()
    destroy_qt_object(window)


@pytest.mark.platforms("windows")
def test_close_cancels_frozen_native_repair_before_window_retires(
    tmp_path: Path, qt_application_owner: QApplication
) -> None:
    """Close through the production controller and reclaim a frozen fixture's lock."""
    supervisor = RepairProcessSupervisor(
        command_builder=lambda: (
            sys.executable,
            "-m",
            "tests.launcher.repair.execution_process_fixture",
            str(tmp_path),
        ),
        startup_log_path=tmp_path / "repair.log",
    )
    started = Event()

    def create(request: PreparedRepairRequest) -> RepairWorker:
        """Replace only the executable boundary, retaining the production worker."""
        worker = RepairWorker(request, supervisor=supervisor)
        worker.progress.connect(lambda _value: started.set())
        return worker

    window = RepairWindow()
    controller = RepairController(window, _request(tmp_path), worker_factory=create)
    window.show()
    try:
        controller.start()
        wait_for_qt_condition(started.is_set)
        assert not supervisor.safe_to_close
        assert not window.close()
        wait_for_qt_condition(lambda: not window.isVisible())
        assert supervisor.safe_to_close
        with installation_mutation(tmp_path) as ownership:
            ownership.validate(tmp_path)
    finally:
        supervisor.request_cancel()
        _dispose(window)


def test_unconfirmed_cleanup_retires_host_without_user_retry(
    tmp_path: Path,
    qt_application_owner: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retire the disposable UI host so its outer native owner reclaims the family."""
    started, cancelled = Event(), Event()
    attempts: list[RepairWorker] = []
    exits: list[int] = []
    monkeypatch.setattr(QCoreApplication, "exit", exits.append)

    class UnconfirmedExecution(RepairProcessSupervisor):
        """Control only the external execution capability observed by the Qt adapter."""

        @property
        def safe_to_close(self) -> bool:
            """Expose confirmation independently of a worker function returning."""
            return False

        def request_cancel(self) -> None:
            """Record UI intent without confirming native termination."""
            cancelled.set()

        def run(
            self,
            *,
            progress_observer: Callable[[dict[str, object]], None],
            output_callback: Callable[[str], None],
        ) -> dict[str, object]:
            """Return a cleanup error while the process boundary remains unconfirmed."""
            started.set()
            assert cancelled.wait(10)
            raise OSError("Fixture native exit could not be confirmed")

    def create(request: PreparedRepairRequest) -> RepairWorker:
        """Retain attempts so another repair cannot silently replace blocked cleanup."""
        worker = RepairWorker(
            request,
            supervisor=UnconfirmedExecution(
                command_builder=lambda: (), startup_log_path=tmp_path / "repair.log"
            ),
        )
        attempts.append(worker)
        return worker

    window = RepairWindow()
    controller = RepairController(window, _request(tmp_path), worker_factory=create)
    window.show()
    try:
        controller.start()
        wait_for_qt_condition(started.is_set)
        assert not window.close()
        wait_for_qt_condition(lambda: not window.isVisible())
        assert exits == [1]
        controller.start()
        assert len(attempts) == 1
    finally:
        for worker in attempts:
            worker.request_cancel()
        _dispose(window)


def test_close_waits_for_active_worker_completion(
    tmp_path: Path,
    qt_application_owner: QApplication,
) -> None:
    """A close request keeps the window and worker alive until mutation returns."""
    started, cancelled, release, returned = Event(), Event(), Event(), Event()
    affinities: list[tuple[bool, bool]] = []
    workers: list[RepairWorker] = []

    class HeldExecution(RepairProcessSupervisor):
        """Control the external boundary while retaining the production Qt slot."""

        def request_cancel(self) -> None:
            """Record intent without pretending that execution has completed."""
            cancelled.set()

        def run(
            self,
            *,
            progress_observer: Callable[[dict[str, object]], None],
            output_callback: Callable[[str], None],
        ) -> dict[str, object]:
            """Hold execution only on the real worker's owner thread."""
            affinities.append(
                (
                    QThread.currentThread() == workers[0].thread(),
                    QThread.currentThread() != qt_application_owner.thread(),
                )
            )
            started.set()
            try:
                if affinities[-1] != (True, True):
                    raise RuntimeError("Controlled execution ran on the wrong thread")
                if not release.wait(10):
                    raise TimeoutError("Controlled execution was not released")
                raise RepairProcessCancelled("Controlled native cleanup completed")
            finally:
                returned.set()

    def create(request: PreparedRepairRequest) -> RepairWorker:
        """Replace external execution while keeping the production worker unchanged."""
        worker = RepairWorker(
            request,
            supervisor=HeldExecution(
                command_builder=lambda: (),
                startup_log_path=tmp_path / "repair.log",
            ),
        )
        workers.append(worker)
        return worker

    window = RepairWindow()
    controller = RepairController(window, _request(tmp_path), worker_factory=create)
    window.show()
    try:
        controller.start()
        wait_for_qt_condition(started.is_set)
        assert affinities == [(True, True)]
        assert not returned.is_set()
        assert workers[0].thread().isRunning()
        assert not window.close()
        assert cancelled.is_set()
        wait_for_queued_qt_turn()
        assert window.isVisible()
        assert not returned.is_set()
        release.set()
        wait_for_qt_condition(lambda: not window.isVisible())
        assert returned.is_set()
    finally:
        release.set()
        _dispose(window)


def test_retry_and_open_wait_for_worker_cleanup(
    tmp_path: Path,
    qt_application_owner: QApplication,
) -> None:
    """Retry starts a new worker and successful Open delegates to the supervisor."""
    attempts: list[RepairWorker] = []
    affinities: list[tuple[bool, bool]] = []
    opened: list[bool] = []

    class CompletedExecution(RepairProcessSupervisor):
        """Choose each attempt's external result before the real worker begins."""

        def __init__(self) -> None:
            """Bind a stable outcome to this attempt rather than later list state."""
            self._attempt_index = len(attempts)
            super().__init__(
                command_builder=lambda: (),
                startup_log_path=tmp_path / f"repair-{self._attempt_index}.log",
            )

        def run(
            self,
            *,
            progress_observer: Callable[[dict[str, object]], None],
            output_callback: Callable[[str], None],
        ) -> dict[str, object]:
            """Fail once, then return the production terminal-result contract."""
            affinities.append(
                (
                    QThread.currentThread() == attempts[self._attempt_index].thread(),
                    QThread.currentThread() != qt_application_owner.thread(),
                )
            )
            if affinities[-1] != (True, True):
                raise RuntimeError("Controlled execution ran on the wrong thread")
            if self._attempt_index == 0:
                raise OSError("Synthetic recoverable failure")
            return {
                "session_recovery": SessionRecoveryResult(
                    SessionRecoveryState.NO_SESSION,
                ).to_json(),
            }

    def create(request: PreparedRepairRequest) -> RepairWorker:
        """Retain each distinct real worker and its controlled external attempt."""
        worker = RepairWorker(request, supervisor=CompletedExecution())
        attempts.append(worker)
        return worker

    def open_application() -> bool:
        """Record the successful supervisor action without launching an application."""
        opened.append(True)
        return True

    window = RepairWindow()
    controller = RepairController(
        window,
        _request(tmp_path),
        worker_factory=create,
        open_application=open_application,
    )
    window.show()
    primary = window.findChild(QPushButton, "RepairPrimaryAction")
    assert primary is not None
    try:
        controller.start()
        wait_for_qt_condition(
            lambda: primary.isVisible() and primary.text() == "Try again",
            timeout_ms=_WORKER_COMPLETION_TIMEOUT_MS,
            description="recoverable repair result",
            state=lambda: (primary.isVisible(), primary.text(), len(attempts)),
        )
        assert affinities == [(True, True)]
        assert primary.text() == "Try again"
        primary.click()
        wait_for_qt_condition(
            lambda: primary.isVisible() and primary.text() == "Open SugarSubstitute",
            timeout_ms=_WORKER_COMPLETION_TIMEOUT_MS,
            description="successful retry result",
            state=lambda: (primary.isVisible(), primary.text(), len(attempts)),
        )
        assert len(attempts) == 2
        assert attempts[0] is not attempts[1]
        assert affinities == [(True, True), (True, True)]
        assert primary.text() == "Open SugarSubstitute"
        primary.click()
        assert opened == [True]
        assert not window.isVisible()
    finally:
        _dispose(window)
