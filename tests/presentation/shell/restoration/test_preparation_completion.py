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

"""Test separate restored-editor construction and publication completion."""

from collections.abc import Callable
from types import SimpleNamespace

from substitute.presentation.shell.restored_projection_preparation_completion import (
    RestoredProjectionPreparationCompletion,
)


def test_hidden_preparation_releases_startup_without_visible_binding() -> None:
    """A prepared hidden build can unblock startup but cannot bind previews."""

    calls: list[str] = []
    observers: list[Callable[[], None]] = []
    completion = RestoredProjectionPreparationCompletion(
        on_prepared=lambda: calls.append("prepared"),
        on_visible_complete=lambda: calls.append("visible"),
    )
    completion.observe(SimpleNamespace(when_projection_prepared=observers.append))
    assert calls == []
    observers[0]()
    observers[0]()
    assert calls == ["prepared"]
    completion.visible_complete()
    assert calls == ["prepared", "visible"]


def test_synchronous_visible_completion_is_preparation_evidence() -> None:
    """Unstaged synchronous projection reports preparation without an observer."""

    calls: list[str] = []
    completion = RestoredProjectionPreparationCompletion(
        on_prepared=lambda: calls.append("prepared"),
        on_visible_complete=lambda: calls.append("visible"),
    )
    completion.visible_complete()
    completion.observe(object())
    completion.prepared()
    assert calls == ["visible", "prepared"]


def test_restore_controller_subscribes_to_hidden_preparation_before_publication() -> (
    None
):
    """Startup completion observes prepared builds while preview binding waits."""

    from substitute.presentation.shell.restore_projection_controller import (
        RestoreProjectionController,
    )

    calls: list[str] = []
    prepared: list[Callable[[], None]] = []
    published: list[Callable[[], None]] = []
    panel = SimpleNamespace(when_projection_prepared=prepared.append)

    def refresh(*, force_refresh: bool, on_complete: Callable[[], None]) -> None:
        """Queue a deferred production editor publication boundary."""

        assert force_refresh
        published.append(on_complete)

    shell = SimpleNamespace(
        active_editor_panel=panel,
        input_node_preview_coordinator=SimpleNamespace(
            bind_panel=lambda _panel: calls.append("bind")
        ),
        active_workflow_surface_refresher=SimpleNamespace(
            refresh_active_workflow_surface=refresh
        ),
    )
    RestoreProjectionController(shell).reconcile_active_workflow_for_restore_projection(
        force_refresh=True,
        on_complete=lambda: calls.append("prepared"),
    )
    assert calls == []
    prepared[0]()
    assert calls == ["prepared"]
    published[0]()
    assert calls == ["prepared", "bind"]
