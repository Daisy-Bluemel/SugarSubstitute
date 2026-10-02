"""Declare developer-calibrated startup durations, never execution timeouts.

Defaults approximate installed Linux process-cold traces with a 17-tab restore.
Adjust these expected
milliseconds from phase diagnostics when hardware/workloads change. They only
weight observed milestones: no clock advances completion. The parallel shell
and Comfy branches intentionally contribute their maximum, not their sum.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StartupEstimatePolicy:
    """Keep tunable duration estimates separate from optional-work budgets."""

    # Entrypoint imports, installation check, runtime imports, services, restore plan.
    bootstrap_ms: tuple[int, ...] = (1800, 20, 300, 300, 150)
    prepare_shell_ms: int = 4500
    # Shell build, metadata bridge, editor warmup, prehydration, minimum-ready.
    gui_ms: tuple[int, ...] = (5000, 10, 100, 150, 10)
    # Extension/security setup, runtime imports, device setup, custom nodes,
    # database, server binding, authoritative HTTP/compatibility probe.
    backend_ms: tuple[int, ...] = (1500, 2500, 2500, 5000, 100, 100, 1000)
    # Restored node definitions/runtime, hidden restored-editor preparation.
    restore_ms: tuple[int, ...] = (5000, 500)
    paint_ms: int = 200

    def __post_init__(self) -> None:
        """Reject invalid developer controls before computing normalized units."""
        for values, length in (
            (self.bootstrap_ms, 5),
            (self.gui_ms, 5),
            (self.backend_ms, 7),
            (self.restore_ms, 2),
        ):
            if len(values) != length:
                raise ValueError("Startup estimate segment count is invalid.")
        values = (
            *self.bootstrap_ms,
            self.prepare_shell_ms,
            *self.gui_ms,
            *self.backend_ms,
            *self.restore_ms,
            self.paint_ms,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("Startup duration estimates must be nonnegative integers.")
        if self.paint_ms <= 0:
            raise ValueError("Startup estimates must reserve painted readiness.")


DEFAULT_STARTUP_ESTIMATE_POLICY = StartupEstimatePolicy()
