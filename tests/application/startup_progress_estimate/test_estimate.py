"""Verify estimated wait uses durations and signals, with no running clock."""

from dataclasses import replace

import pytest

from substitute.application.startup_estimate_policy import StartupEstimatePolicy
from substitute.application.startup_progress_estimate import StartupProgressEstimate


def test_parallel_wait_is_maximum_not_sum_and_tiny_steps_do_not_dominate() -> None:
    """Account for prefix work then concurrent shell/backend, without double counting."""
    policy = StartupEstimatePolicy()
    model = StartupProgressEstimate(policy)
    assert model.remaining_ms == (
        sum(policy.bootstrap_ms)
        + policy.prepare_shell_ms
        + max(sum(policy.gui_ms), sum(policy.backend_ms))
        + sum(policy.restore_ms)
        + policy.paint_ms
    )
    model.observe("gui.prepare_main_window")
    after_prepare = model.progress.completed
    model.observe("gui.start_readiness_timer")
    assert model.progress.completed == after_prepare
    for name in (
        "build_main_window",
        "wire_metadata_bridge",
        "warm_prompt_editor_gui",
        "prehydrate_initial_workspace",
        "mark_minimum_shell_ready",
    ):
        model.observe("gui." + name)
    # GUI work is hidden behind the longer backend critical path.
    assert model.progress.completed == after_prepare
    assert model.progress.completed < 4000
    model.observe("backend.runtime")
    assert model.progress.completed > after_prepare


def test_slow_gui_remains_outstanding_after_backend_is_ready() -> None:
    """Handle fast/reused backend without pretending the shell is also built."""
    model = StartupProgressEstimate(
        replace(StartupEstimatePolicy(), gui_ms=(20000, 0, 0, 0, 0))
    )
    model.observe("gui.prepare_main_window")
    before = model.progress
    model.observe("backend.ready")
    assert model.progress == before
    model.observe("gui.build_main_window")
    assert model.progress.completed > before.completed
    assert model.progress.completed < 10000


def test_repeated_early_markers_and_unknown_work_do_not_count_twice() -> None:
    """Keep idempotent semantic milestones separate from task-count denominators."""
    model = StartupProgressEstimate()
    for marker in (
        "bootstrap.installation",
        "bootstrap.components",
        "bootstrap.services",
    ):
        model.observe(marker)
    before = model.progress
    for marker in (
        "bootstrap.components",
        "bootstrap.entrypoint",
        "gui.unrelated_added_task",
    ):
        model.observe(marker)
    assert model.progress == before
    model.observe("backend.connecting")
    connected = model.progress
    for marker in ("backend.runtime", "backend.device", "backend.connecting"):
        model.observe(marker)
    assert model.progress == connected


def test_restart_reallocates_remaining_bar_without_falsely_finishing() -> None:
    """Require new attempt evidence after a backend restart without a backwards jump."""
    model = StartupProgressEstimate()
    model.observe("gui.prepare_main_window")
    model.observe("backend.connecting")
    before = model.progress
    remaining = model.remaining_ms
    model.observe("backend.restart")
    assert model.remaining_ms > remaining
    assert model.progress == before
    model.observe("backend.runtime")
    assert before.completed < model.progress.completed < 10000


def test_reveal_fallback_is_not_painted_readiness() -> None:
    """Allow a recovery reveal to proceed, but only an actual paint can reach100%."""
    model = StartupProgressEstimate()
    model.observe("shell.reveal")
    assert 0 < model.progress.completed < 10000
    before = model.progress
    assert model.progress == before  # Reading repeatedly cannot advance anything.
    model.observe("shell.painted")
    assert model.progress.completed == 10000
    model.observe("backend.restart")
    assert model.progress.completed == 10000
    assert StartupProgressEstimate().progress.completed == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"paint_ms": 0},
        {"prepare_shell_ms": -1},
        {"paint_ms": float("nan")},
        {"backend_ms": (1, 2)},
        {"prepare_shell_ms": float("inf")},
    ],
)
def test_invalid_duration_controls_fail_validation(changes: dict[str, object]) -> None:
    """Reject malformed estimates rather than presenting meaningless completion."""
    with pytest.raises((ValueError, TypeError)):
        StartupEstimatePolicy(**changes)  # type: ignore[arg-type]
