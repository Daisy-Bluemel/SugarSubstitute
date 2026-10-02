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

"""Separate hidden restored-editor preparation from visible publication."""

from __future__ import annotations

from collections.abc import Callable

from substitute.shared.startup_trace import trace_mark


class RestoredProjectionPreparationCompletion:
    """Release hidden startup once while retaining visible-only finalizers."""

    def __init__(
        self,
        *,
        on_prepared: Callable[[], None],
        on_visible_complete: Callable[[], None],
    ) -> None:
        """Keep construction readiness separate from visible widget binding."""

        self._on_prepared = on_prepared
        self._on_visible_complete = on_visible_complete
        self._prepared = False

    def observe(self, panel: object) -> None:
        """Subscribe after starting projection, replaying already prepared builds."""

        when_prepared = getattr(panel, "when_projection_prepared", None)
        trace_mark(
            "restore_projection.preparation.observe",
            panel_present=panel is not None,
            observer_present=callable(when_prepared),
            already_prepared=self._prepared,
        )
        if callable(when_prepared):
            when_prepared(self.prepared)

    def prepared(self) -> None:
        """Report real construction completion at most once for this request."""

        if self._prepared:
            return
        self._prepared = True
        self._on_prepared()

    def visible_complete(self) -> None:
        """Bind published widgets and cover synchronous unstaged preparation."""

        self._on_visible_complete()
        self.prepared()
