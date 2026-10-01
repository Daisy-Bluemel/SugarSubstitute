"""Require fixed-window shell persistence to preserve editor intent without drift."""

from __future__ import annotations

from dataclasses import replace

import pytest

from substitute.presentation.cubes.cube_stack_metrics import (
    CUBE_STACK_COMPACT_WIDTH,
    CUBE_STACK_EXPANDED_WIDTH,
)
import substitute.presentation.shell.generation_queue_panel_transition as queue_transition
from substitute.presentation.shell.cube_stack_presentation_transition import (
    CubeStackPresentationTransition,
)
from tests.support.qt.lifecycle import widget_root_scope

from .support import LayoutHarness


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("direct", [False, True])
def test_repeated_cold_roundtrip_preserves_user_divider(
    compact: bool, direct: bool
) -> None:
    """Fresh geometry owners must restore the same exact divider after every save."""

    with widget_root_scope() as roots:
        first = roots.own(LayoutHarness(compact=compact, direct=direct))
        first.move_divider()
        editor_width = first.editor.width()
        divider = first.splitter.sizes()[0]
        snapshot = first.capture()
        for _restart in range(3):
            restored = roots.own(LayoutHarness(compact=compact, direct=direct))
            restored.restore(snapshot)
            assert restored.editor.width() == editor_width
            assert restored.splitter.sizes()[0] == divider
            next_snapshot = restored.capture()
            assert next_snapshot.editor_panel_width == editor_width
            assert next_snapshot.main_splitter_sizes == snapshot.main_splitter_sizes
            assert next_snapshot == snapshot
            snapshot = next_snapshot


def test_unavailable_capture_uses_durable_coordinates_when_live_geometry_disagrees() -> (
    None
):
    """The reported native recurrence must not add compact chrome at each capture."""

    with widget_root_scope() as roots:
        shell = roots.own(LayoutHarness(compact=True, direct=True))
        shell.workspace_layout_controller.remember_workflow_splitter_sizes(
            (633, 526, 0)
        )
        shell.splitter.setSizes([633, 522, 0])
        shell.settle_layout()

        snapshot = shell.capture()

        assert snapshot.main_splitter_sizes == (633, 526, 0)
        assert snapshot.editor_panel_width == 633 - CUBE_STACK_COMPACT_WIDTH


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("compact", [False, True])
def test_preference_change_rebases_durable_geometry_before_autosave(
    direct: bool, compact: bool
) -> None:
    """Density changes preserve editor intent in both visible and unavailable modes."""

    with widget_root_scope() as roots:
        shell = roots.own(LayoutHarness(compact=not compact, direct=direct))
        shell.move_divider()
        editor_width = shell.editor.width()
        shell.cube_stack_presentation_controller.request_preference(
            compact, animated=False
        )
        shell.settle_layout()

        snapshot = shell.capture()
        preferred_width = (
            CUBE_STACK_COMPACT_WIDTH if compact else CUBE_STACK_EXPANDED_WIDTH
        )
        assert snapshot.main_splitter_sizes[0] == editor_width + preferred_width
        assert snapshot.editor_panel_width == editor_width
        restored = roots.own(LayoutHarness(compact=compact, direct=direct))
        restored.restore(snapshot)
        assert restored.editor.width() == editor_width


def test_inactive_route_capture_keeps_remembered_intent() -> None:
    """Hidden or constrained editor widgets cannot replace authoritative user sizes."""

    with widget_root_scope() as roots:
        shell = roots.own(LayoutHarness(compact=True, direct=False))
        shell.move_divider()
        before = shell.capture()
        shell._active_workspace_route = "settings"
        shell.cube_stack_presentation_controller.set_workflow_route_active(False)
        shell.editor.resize(900, shell.editor.height())

        assert shell.capture() == before


def test_compact_snapshot_remains_stable_after_restore_clamps_editor() -> None:
    """An existing narrow-window clamp may lose width once but cannot accumulate drift."""

    with widget_root_scope() as roots:
        shell = roots.own(LayoutHarness(compact=True, direct=False))
        shell.move_divider()
        oversized = replace(shell.capture(), editor_panel_width=2000)
        shell.restore(oversized)
        clamped = shell.capture()
        divider = shell.splitter.sizes()[0]
        for _restart in range(3):
            restored = roots.own(LayoutHarness(compact=True, direct=False))
            restored.restore(clamped)
            assert restored.splitter.sizes()[0] == divider
            assert restored.capture() == clamped


def test_temporary_expansion_keeps_compact_snapshot_intent() -> None:
    """A lease may enlarge the visible stack but must not rewrite durable preference."""

    with widget_root_scope() as roots:
        shell = roots.own(LayoutHarness(compact=True, direct=False))
        shell.move_divider()
        before = shell.capture()
        with shell.cube_stack_presentation_controller.acquire_expansion():
            shell.settle_layout()
            assert shell.cube_stack_container.width() == CUBE_STACK_EXPANDED_WIDTH
            assert shell.capture() == before
        shell.settle_layout()
        assert shell.capture() == before


def test_temporary_expansion_midpoint_cannot_replace_durable_geometry() -> None:
    """A deterministic animation frame must not become the next saved editor width."""

    with widget_root_scope() as roots:
        shell = roots.own(
            LayoutHarness(compact=True, direct=False, presentation_duration=60_000)
        )
        shell.move_divider()
        before = shell.capture()
        controller = shell.cube_stack_presentation_controller
        with controller.acquire_expansion():
            transition = controller.findChild(CubeStackPresentationTransition)
            assert transition is not None
            transition.setProgress(0.5)
            shell.settle_layout()
            assert (
                CUBE_STACK_COMPACT_WIDTH
                < shell.cube_stack_container.width()
                < CUBE_STACK_EXPANDED_WIDTH
            )
            assert controller.is_animating
            assert shell.capture() == before
        controller.stop()


@pytest.mark.parametrize("compact", [False, True])
def test_queue_transition_remembers_preferred_coordinates_for_direct_workflow(
    compact: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real queue owner must not persist hidden-stack geometry as canonical sizes."""

    monkeypatch.setattr(
        queue_transition, "resolve_motion_duration", lambda _duration: 0
    )
    with widget_root_scope() as roots:
        shell = roots.own(LayoutHarness(compact=compact, direct=True))
        shell.move_divider()
        editor_width = shell.editor.width()
        shell.generation_queue_controller.apply_panel_visibility(
            True, request_autosave=True, animated=True
        )
        shell.settle_layout()
        assert shell.editor.width() == editor_width
        snapshot = shell.capture()
        preferred_width = (
            CUBE_STACK_COMPACT_WIDTH if compact else CUBE_STACK_EXPANDED_WIDTH
        )
        assert snapshot.editor_panel_width == editor_width
        assert snapshot.main_splitter_sizes[0] == editor_width + preferred_width
        assert snapshot.main_splitter_sizes[2] == 240
        assert snapshot.side_panel_visible
        restored = roots.own(LayoutHarness(compact=compact, direct=True))
        restored.restore(snapshot)
        assert restored.editor.width() == editor_width
        assert restored.capture().editor_panel_width == editor_width
        assert restored.capture() == snapshot
        for _restart in range(2):
            repeated = roots.own(LayoutHarness(compact=compact, direct=True))
            repeated.restore(restored.capture())
            assert repeated.editor.width() == editor_width
            assert repeated.capture() == snapshot
        shell.generation_queue_controller.apply_panel_visibility(
            False, request_autosave=True, animated=True
        )
        shell.settle_layout()
        assert shell.editor.width() == editor_width
        closed = shell.capture()
        restored.restore(closed)
        assert restored.editor.width() == editor_width
        assert restored.capture() == closed


def test_direct_canvas_clamp_converges_without_changing_minimum_policy() -> None:
    """Insufficient canvas donation may clamp once, then persisted geometry is stable."""

    with widget_root_scope() as roots:
        shell = roots.own(LayoutHarness(compact=False, direct=True))
        shell.move_divider(1005)
        canonical = shell.capture()
        assert canonical.main_splitter_sizes == (1055, 100, 0)
        assert canonical.editor_panel_width == 1055 - CUBE_STACK_EXPANDED_WIDTH
        shell.restore(canonical)
        stable = shell.capture()
        divider = shell.splitter.sizes()[0]
        assert stable.main_splitter_sizes[1] == 120
        for _restart in range(3):
            restored = roots.own(LayoutHarness(compact=False, direct=True))
            restored.restore(stable)
            assert restored.splitter.sizes()[0] == divider
            assert restored.capture() == stable


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("direct", [False, True])
def test_constrained_preference_cycles_converge_after_canvas_clamp(
    compact: bool, direct: bool
) -> None:
    """The declared lossy donation clamp must not ratchet on repeated density cycles."""

    with widget_root_scope() as roots:
        shell = roots.own(LayoutHarness(compact=compact, direct=direct))
        shell.move_divider(1005)
        stable = None
        stable_editor_width = None
        for _cycle in range(3):
            controller = shell.cube_stack_presentation_controller
            controller.request_preference(not compact, animated=False)
            controller.request_preference(compact, animated=False)
            shell.settle_layout()
            if direct:
                assert shell.editor.width() == 1005
            elif stable_editor_width is not None:
                assert shell.editor.width() == stable_editor_width
            current = shell.capture()
            assert current.main_splitter_sizes[1] >= 100
            if stable is not None:
                assert current == stable
            stable = current
            stable_editor_width = shell.editor.width()


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("compact", [False, True])
def test_startup_defaults_use_preferred_geometry_and_restore_same_editor(
    direct: bool, compact: bool
) -> None:
    """The default-layout caller must supply canonical sizes to the presentation owner."""

    with widget_root_scope() as roots:
        shell = roots.own(LayoutHarness(compact=compact, direct=direct))
        shell.resize(1600, 651)
        shell.settle_layout()
        shell.workspace_layout_controller.apply_startup_default_splitter_layout()
        shell.settle_layout()
        assert shell.editor.width() == 832
        snapshot = shell.capture()
        assert snapshot.editor_panel_width == 832
        restored = roots.own(LayoutHarness(compact=compact, direct=direct))
        restored.resize(1600, 651)
        restored.settle_layout()
        restored.restore(snapshot)
        assert restored.editor.width() == 832
