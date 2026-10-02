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

"""Project completed GUI startup work without claiming replacement-surface readiness."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol
from substitute.app.bootstrap.gui_startup_queue import GuiStartupProgress
from substitute.app.bootstrap.startup_failure_controller import SplashCloseProtocol
from sugarsubstitute_shared.launch_splash.progress import SplashProgress
from substitute.app.bootstrap.startup_estimate_splash import report_startup_milestone
from sugarsubstitute_shared.localization import app_text
from sugarsubstitute_shared.presentation.localization.application_message import (
    render_application_text,
)


class StartupProgressSplash(SplashCloseProtocol, Protocol):
    """Expose startup completion and cancellation through the live splash client."""

    def set_progress(self, progress: SplashProgress, *, status: str) -> None:
        """Present producer-owned progress and localized status."""

    def record_activity(self) -> None:
        """Report one queue boundary as observed startup work."""


class StartupSplashProgress:
    """Forward named queue completions into the single startup estimate owner."""

    def __init__(self, splash: Callable[[], StartupProgressSplash | None]) -> None:
        """Resolve the current splash after any early startup handoff."""
        self._splash = splash

    def queue_progress(self, progress: GuiStartupProgress) -> None:
        """Report actual task completions independently of equal-count queue totals."""
        splash = self._splash()
        if splash is None:
            return
        splash.record_activity()
        if progress.finished:
            report_startup_milestone(
                splash,
                f"gui.{progress.task_name}",
                status=render_application_text(
                    app_text("Preparing the application interface.")
                ),
            )
