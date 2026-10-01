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

"""Capture immutable caret geometry for incremental layout comparisons."""

from __future__ import annotations

from substitute.presentation.editor.prompt_editor.layout.models import (
    PromptProjectionLineSnapshot,
)


def line_caret_signature(
    line: PromptProjectionLineSnapshot,
) -> tuple[tuple[int, tuple[float, float, float, float]], ...]:
    """Copy exact caret values without retaining mutable Qt rectangles."""

    return tuple(
        (
            stop.projection_position,
            (stop.rect.x(), stop.rect.y(), stop.rect.width(), stop.rect.height()),
        )
        for stop in line.caret_stops
    )
