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

"""Observe wallpaper snapshots asynchronously with explicit recovery publication."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from cutemica.geometry import ScreenBinding  # type: ignore[import-untyped]
from cutemica.providers.wallpaper_monitor import WallpaperPollJob  # type: ignore[import-untyped]
from cutemica.providers.wallpaper_provider import WallpaperProvider  # type: ignore[import-untyped]
from cutemica.wallpaper import WallpaperSnapshot  # type: ignore[import-untyped]

from substitute.presentation.qt.execution.thread_pool_dispatcher import (
    start_qt_runnable,
)


class MicaWallpaperObserver(QObject):
    """Publish every successful observation so unchanged sources recover from errors."""

    snapshot_ready = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        provider: WallpaperProvider,
        bindings: tuple[ScreenBinding, ...],
        *,
        parent: QObject,
    ) -> None:
        """Store provider affinity and prevent overlapping discovery requests."""

        super().__init__(parent)
        self._provider = provider
        self._bindings = bindings
        self._active_job: WallpaperPollJob | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.poll)

    def start(self) -> None:
        """Discover immediately and monitor providers that support source changes."""

        self.poll()
        if self._provider.capabilities.wallpaper_changes:
            self._timer.start()

    def stop(self) -> None:
        """Stop future polling while allowing a submitted request to settle safely."""

        self._timer.stop()

    @Slot()
    def poll(self) -> None:
        """Run slow platform queries through the registered Qt execution boundary."""

        if self._active_job is not None:
            return
        if self._provider.requires_main_thread:
            try:
                self._completed(self._provider.discover(self._bindings))
            except (OSError, RuntimeError, ValueError) as error:
                self.failed.emit(str(error))
            return
        job = WallpaperPollJob(self._provider, self._bindings)
        job.signals.completed.connect(self._completed)
        job.signals.failed.connect(self._failed)
        self._active_job = job
        start_qt_runnable(job)

    @Slot(object)
    def _completed(self, value: object) -> None:
        """Publish valid snapshots even if the previous successful one was equal."""

        self._active_job = None
        if isinstance(value, WallpaperSnapshot):
            self.snapshot_ready.emit(value)

    @Slot(str)
    def _failed(self, reason: str) -> None:
        """Release the request so a later observation can recover."""

        self._active_job = None
        self.failed.emit(reason)
