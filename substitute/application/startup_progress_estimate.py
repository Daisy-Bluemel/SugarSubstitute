"""Estimate remaining startup work from semantic evidence and calibrated durations."""

from __future__ import annotations

from substitute.application.startup_estimate_policy import (
    DEFAULT_STARTUP_ESTIMATE_POLICY,
    StartupEstimatePolicy,
)
from sugarsubstitute_shared.launch_splash.progress import SplashProgress

_BOOTSTRAP_BOUNDARIES = {
    "bootstrap.installation": 1,
    "bootstrap.components": 2,
    "bootstrap.services": 3,
    "bootstrap.workspace": 4,
    "bootstrap.interface": 5,
}
_GUI_TASKS = (
    "build_main_window",
    "wire_metadata_bridge",
    "warm_prompt_editor_gui",
    "prehydrate_initial_workspace",
    "mark_minimum_shell_ready",
)
_BACKEND_BOUNDARIES = {
    "backend.runtime": 1,
    "backend.device": 2,
    "backend.custom_nodes": 3,
    "backend.imports_complete": 4,
    "backend.server": 5,
    "backend.connecting": 6,
    "backend.ready": 7,
}


class StartupProgressEstimate:
    """Own one monotonic signal-driven estimate with an explicit parallel branch.

    A backend restart rebases only the remaining fraction, retaining earned
    completion while reserving enough of the bar for the new attempt. Repeated
    and late earlier milestones never earn work twice. Background catalog work
    is deliberately outside the startup critical path.
    """

    def __init__(
        self,
        policy: StartupEstimatePolicy = DEFAULT_STARTUP_ESTIMATE_POLICY,
    ) -> None:
        """Start a fresh estimate without consulting elapsed wall time."""
        self._policy = policy
        self._bootstrap = 0
        self._prepared = False
        self._gui: set[str] = set()
        self._backend = 0
        self._restore = 0
        self._painted = False
        self._base = 0
        self._units = 0
        self._remaining_at_base = self.remaining_ms

    @property
    def remaining_ms(self) -> int:
        """Return estimated outstanding critical-path work, not an elapsed ETA."""
        policy = self._policy
        gui = sum(
            duration
            for name, duration in zip(_GUI_TASKS, policy.gui_ms, strict=True)
            if name not in self._gui
        )
        backend = sum(policy.backend_ms[self._backend :])
        return (
            sum(policy.bootstrap_ms[self._bootstrap :])
            + (0 if self._prepared else policy.prepare_shell_ms)
            + max(gui, backend)
            + sum(policy.restore_ms[self._restore :])
            + (0 if self._painted else policy.paint_ms)
        )

    @property
    def progress(self) -> SplashProgress:
        """Expose fixed integer units compatible with the existing splash wire format."""
        return SplashProgress(self._units, 10_000)

    def observe(self, milestone: str) -> bool:
        """Apply one semantic event and report whether estimated completion changed."""
        if self._painted:
            return False
        previous = self._units
        if milestone == "backend.restart":
            self._backend = 0
            self._restore = 0
            self._base = self._units
            self._remaining_at_base = self.remaining_ms
            return False
        if milestone in _BOOTSTRAP_BOUNDARIES:
            self._bootstrap = max(self._bootstrap, _BOOTSTRAP_BOUNDARIES[milestone])
        elif milestone == "gui.prepare_main_window":
            self._bootstrap = len(self._policy.bootstrap_ms)
            self._prepared = True
        elif milestone.removeprefix("gui.") in _GUI_TASKS:
            self._gui.add(milestone.removeprefix("gui."))
        elif milestone in _BACKEND_BOUNDARIES:
            self._backend = max(self._backend, _BACKEND_BOUNDARIES[milestone])
        elif milestone == "workspace.runtime_prepared":
            self._restore = max(self._restore, 1)
        elif milestone == "shell.reveal":
            # Reveal may be a recovery fallback, so this records reaching the
            # reveal boundary, not successful restoration or backend readiness.
            self._bootstrap = len(self._policy.bootstrap_ms)
            self._prepared = True
            self._gui.update(_GUI_TASKS)
            self._backend = len(self._policy.backend_ms)
            self._restore = len(self._policy.restore_ms)
        elif milestone == "shell.painted":
            self._painted = True
            self._units = 10_000
            return True
        else:
            return False
        earned = self._remaining_at_base - self.remaining_ms
        estimate = (
            self._base + (10_000 - self._base) * earned // self._remaining_at_base
        )
        self._units = max(self._units, min(9999, estimate))
        return self._units != previous
