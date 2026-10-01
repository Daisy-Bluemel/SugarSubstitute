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

"""Provide a typed Windows registration boundary without distributing OS fonts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tools import qualification_font


class WindowsFontBoundary:
    """Record only the native font-file registration and release operations."""

    def __init__(self, root: Path) -> None:
        """Keep registrations local to one explicitly simulated Windows test."""

        self.path = root / "Fonts" / "segoeui.ttf"
        self.path.parent.mkdir()
        self.path.touch()
        self.paths: list[str] = []
        self.active: set[int] = set()
        self.removed: list[int] = []
        self.families = ["Segoe UI"]
        self.registration_fails = False
        self.release_fails = False
        self.before_release: Callable[[], None] | None = None
        self._next_id = 29

    def addApplicationFont(self, path: str) -> int:  # noqa: N802
        """Accept an owned registration or reproduce Qt's failure result."""

        self.paths.append(path)
        if self.registration_fails:
            return -1
        identifier = self._next_id
        self._next_id += 1
        self.active.add(identifier)
        return identifier

    def applicationFontFamilies(self, identifier: int) -> list[str]:  # noqa: N802
        """Expose the family that a successful Windows registration published."""

        assert identifier in self.active
        return self.families

    def removeApplicationFont(self, identifier: int) -> bool:  # noqa: N802
        """Observe cleanup ordering before releasing the exact owned ID."""

        if self.before_release is not None:
            self.before_release()
        self.active.remove(identifier)
        self.removed.append(identifier)
        return not self.release_fails


@pytest.fixture
def windows_font_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    offscreen_rendering_font: None,
) -> WindowsFontBoundary:
    """Replace OS registration only for tests explicitly selecting Windows policy."""

    _ = offscreen_rendering_font
    boundary = WindowsFontBoundary(tmp_path)
    monkeypatch.setenv("WINDIR", str(tmp_path))
    monkeypatch.setattr(qualification_font, "QFontDatabase", boundary)
    return boundary
