"""Bind one startup estimate to its existing replaceable splash transport."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import ContextManager, Protocol, runtime_checkable
from threading import RLock

from substitute.app.bootstrap.launch_splash_client import LaunchSplashClient
from substitute.app.bootstrap.startup_trace import trace_mark
from substitute.application.comfy_startup_status import observe_comfy_startup_output
from substitute.application.startup_progress_estimate import StartupProgressEstimate
from substitute.shared.logging.logger import get_logger, log_exception, log_info
from sugarsubstitute_shared.launch_splash.activity import SplashActivity
from sugarsubstitute_shared.launch_splash.progress import SplashProgress

_LOGGER = get_logger("app.bootstrap.startup_estimate_splash")


@runtime_checkable
class StartupEstimateReporter(Protocol):
    """Accept semantic startup evidence independently of the transport protocol."""

    def observe_startup(self, milestone: str, *, status: str | None = None) -> None:
        """Update the startup estimate from one real operation boundary."""


def report_startup_milestone(
    splash: object | None,
    milestone: str,
    *,
    status: str | None = None,
) -> None:
    """Isolate optional estimate presentation from authoritative startup work."""
    if not isinstance(splash, StartupEstimateReporter):
        return
    try:
        splash.observe_startup(milestone, status=status)
    except Exception:
        log_exception(_LOGGER, "Startup estimate reporting failed", milestone=milestone)


class StartupEstimateSplashClient:
    """Retain estimated-work state through early splash adoption and native closure."""

    def __init__(
        self,
        client: LaunchSplashClient,
        *,
        estimate: StartupProgressEstimate | None = None,
    ) -> None:
        """Wrap the existing transport without changing its lifecycle guarantees."""
        self._client = client
        self.estimate = estimate if estimate is not None else StartupProgressEstimate()
        self._status = ""
        self._closed = False
        self._lock = RLock()
        self._backend_generation = 0

    def observe_startup(self, milestone: str, *, status: str | None = None) -> None:
        """Serialize startup evidence with worker output and native splash closure."""
        with self._lock:
            if milestone == "backend.restart":
                # App-owned relaunch invalidates callbacks from the old pump.
                self._backend_generation += 1
            self._observe(milestone, status=status)

    def _observe(self, milestone: str, *, status: str | None = None) -> None:
        """Apply one observation while the caller holds the session lock."""
        if self._closed and milestone != "shell.painted":
            return
        if status is not None:
            self._status = status
        changed = self.estimate.observe(milestone)
        if changed:
            trace_mark(
                "startup.progress.estimated",
                milestone=milestone,
                completed=self.estimate.progress.completed,
                total=self.estimate.progress.total,
                estimated_remaining_ms=self.estimate.remaining_ms,
            )
            log_info(
                _LOGGER,
                "Startup estimated work advanced",
                milestone=milestone,
                completed=self.estimate.progress.completed,
                total=self.estimate.progress.total,
                estimated_remaining_ms=self.estimate.remaining_ms,
            )
        if changed and not self._closed:
            self._client.set_progress(self.estimate.progress, status=self._status)

    def bind_backend_output(self) -> Callable[[str], None]:
        """Bind one process-pump attempt so late prior logs cannot earn new work."""
        with self._lock:
            self._backend_generation += 1
            generation = self._backend_generation

        def observe_output(line: str) -> None:
            """Classify current-attempt console evidence without suppressing diagnostics."""
            try:
                with self._lock:
                    if self._closed or generation != self._backend_generation:
                        return
                    observation = observe_comfy_startup_output(line)
                    if observation is not None and observation.milestone is not None:
                        # Manager can restart inside the same stdout stream. Its
                        # marker resets work, but does not invalidate this pump.
                        self._observe(observation.milestone)
            except Exception:
                log_exception(_LOGGER, "Startup console estimate failed")

        return observe_output

    def append_log(self, line: str) -> None:
        """Keep diagnostics separate from generation-bound progress observations."""
        with self._lock:
            if not self._closed:
                self._client.append_log(line)

    def set_progress(self, progress: SplashProgress, *, status: str) -> None:
        """Forward explicit non-startup operation units without changing their meaning."""
        with self._lock:
            if not self._closed:
                self._status = status
                self._client.set_progress(progress, status=status)

    def start_activity(self, activity: SplashActivity) -> None:
        """Preserve captions and independent activity without earning completion."""
        with self._lock:
            if not self._closed:
                self._status = activity.initial_text
                self._client.start_activity(activity)

    def record_activity(self) -> None:
        """Forward real activity without changing duration-weighted completion."""
        with self._lock:
            if not self._closed:
                self._client.record_activity()

    def clear_activity(self) -> None:
        """Clear the current activity while retaining the estimated work state."""
        with self._lock:
            if not self._closed:
                self._client.clear_activity()

    def close(self) -> object:
        """Preserve failed native close acknowledgements and never claim readiness."""
        with self._lock:
            result = self._client.close()
            if result is not False:
                self._closed = True
            return result


def adopt_startup_estimate(client: LaunchSplashClient) -> StartupEstimateSplashClient:
    """Keep a single estimate when adopting the launcher-owned early splash."""
    if isinstance(client, StartupEstimateSplashClient):
        return client
    return StartupEstimateSplashClient(client)


@contextmanager
def observe_backend_ready_phase(
    splash: object | None,
    phase: ContextManager[None],
) -> Iterator[None]:
    """Report actual HTTP readiness without prematurely crediting workspace work."""
    with phase:
        report_startup_milestone(splash, "backend.ready")
        yield


@contextmanager
def observe_backend_restart_phase(
    splash: object | None,
    phase: ContextManager[None],
) -> Iterator[None]:
    """Rebase remaining estimated work when app-owned recovery relaunches Comfy."""
    with phase:
        report_startup_milestone(splash, "backend.restart")
        yield


def startup_backend_output_observer(splash: object | None) -> Callable[[str], None]:
    """Bind process evidence only when the startup session owns an estimate."""
    if isinstance(splash, StartupEstimateSplashClient):
        return splash.bind_backend_output()
    return lambda _line: None


def observe_hidden_restore_runtime_prepared(
    splash: object | None,
    set_prepared: Callable[[bool], None],
    prepared: bool,
) -> None:
    """Credit restored-runtime preparation only after its actual gate callback."""
    set_prepared(prepared)
    # False resolves an unavailable/not-applicable preparation path; it is not
    # evidence of successful restored content or of replacement-surface paint.
    report_startup_milestone(splash, "workspace.runtime_prepared")
