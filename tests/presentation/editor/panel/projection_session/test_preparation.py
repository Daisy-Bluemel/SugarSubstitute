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

"""Verify hidden preparation observers never claim visible session completion."""

import pytest

from substitute.presentation.editor.panel.projection_session_models import (
    ActiveProjectionSession,
)
from substitute.presentation.editor.panel.projection_session_registry import (
    ActiveProjectionSessionRegistry,
)


def _start(registry: ActiveProjectionSessionRegistry) -> ActiveProjectionSession:
    """Start a real session with inert external completion collaborators."""

    return registry.start(
        workflow_id="workflow",
        cube_entries=[("cube", object())],
        supersede_existing=lambda _old, _new, _reason: None,
        session_cleared=lambda _session, _reason: None,
        discard_pending_visible_commit=lambda _reason: None,
    )


def test_preparation_replays_once_per_observer_without_resolving() -> None:
    """Preparation remains distinct from visible projection publication."""

    registry = ActiveProjectionSessionRegistry()
    calls: list[str] = []
    assert not registry.when_prepared(lambda: calls.append("absent"))
    session = _start(registry)
    assert registry.when_prepared(lambda: calls.append("first"))
    assert calls == []
    registry.mark_prepared(session)
    registry.mark_prepared(session)
    assert registry.when_prepared(lambda: calls.append("replayed"))
    assert calls == ["first", "replayed"]
    assert registry.is_current(session)
    assert not session.resolved


@pytest.mark.parametrize("terminate", ["cancel", "replace", "clear"])
def test_interrupted_preparation_ignores_late_build_signal(terminate: str) -> None:
    """An abandoned build cannot notify or transfer preparation observers."""

    registry = ActiveProjectionSessionRegistry()
    calls: list[str] = []
    session = _start(registry)
    assert registry.when_prepared(lambda: calls.append("old"))
    if terminate == "cancel":
        registry.cancel(session, reason="cancel", cancel_session=lambda _s, _r: None)
    elif terminate == "clear":
        registry.clear(session, reason="clear")
    else:
        replacement = _start(registry)
        assert registry.when_prepared(lambda: calls.append("new"))
        registry.mark_prepared(replacement)
    registry.mark_prepared(session)
    assert calls == (["new"] if terminate == "replace" else [])
    assert not any(
        completion.completion_phase == "prepared"
        for completion in session.projection_completions
    )


def test_preparation_notification_stops_after_reentrant_replacement() -> None:
    """An observer replacing its session invalidates later old observers."""

    registry = ActiveProjectionSessionRegistry()
    calls: list[str] = []
    session = _start(registry)

    def callback() -> None:
        """Replace the session during observer dispatch."""

        _start(registry)

    assert registry.when_prepared(callback)
    assert registry.when_prepared(lambda: calls.append("stale"))
    registry.mark_prepared(session)
    assert calls == []


@pytest.mark.parametrize(
    ("replacement_workflow", "replacement_aliases", "compatible"),
    [
        ("workflow", ("cube",), True),
        ("workflow", ("cube", "extra"), True),
        ("other-workflow", ("cube",), False),
        ("workflow", ("other-cube",), False),
    ],
)
def test_replacement_transfers_only_owned_preparation_waiter(
    replacement_workflow: str,
    replacement_aliases: tuple[str, ...],
    compatible: bool,
) -> None:
    """Late definitions adopt waiters only when replacing the same requested work."""

    from substitute.presentation.editor.panel.projection_completion_registry import (
        ProjectionCompletionRegistry,
        ProjectionSessionCompletionController,
    )

    registry = ActiveProjectionSessionRegistry()
    pending = ProjectionCompletionRegistry()
    completions = ProjectionSessionCompletionController(pending)
    calls: list[str] = []
    original = _start(registry)
    pending.register_projection_completion(
        original,
        workflow_id="workflow",
        aliases={"cube"},
        on_complete=lambda: calls.append("visible"),
        reason="test_visible_completion",
    )
    assert registry.when_prepared(lambda: calls.append("prepared"))

    def transfer(
        old: ActiveProjectionSession, new: ActiveProjectionSession, reason: str
    ) -> None:
        """Delegate ownership to the production compatible-completion transfer."""

        completions.transfer(old, replacement_session=new, reason=reason)

    replacement = registry.start(
        workflow_id=replacement_workflow,
        cube_entries=[(alias, object()) for alias in replacement_aliases],
        supersede_existing=transfer,
        session_cleared=lambda _session, _reason: None,
        discard_pending_visible_commit=lambda _reason: None,
    )
    registry.mark_prepared(original)
    assert calls == []
    registry.mark_prepared(replacement)
    assert calls == (["prepared"] if compatible else [])
    assert registry.is_current(replacement)
    registry.mark_prepared(original)
    registry.mark_prepared(replacement)
    assert calls == (["prepared"] if compatible else [])
    registry.resolve(
        replacement,
        reason="visible_complete",
        resolve_session=lambda session, reason: completions.resolve(
            session, reason=reason
        ),
    )
    assert calls == (["prepared", "visible"] if compatible else [])
