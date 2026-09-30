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

"""Contain source-file races before CuteMica's protected rendering jobs."""

from __future__ import annotations

from PySide6.QtCore import Slot
from cutemica.controller import MaterialController  # type: ignore[import-untyped]
from cutemica.wallpaper import WallpaperSnapshot  # type: ignore[import-untyped]


class MicaMaterialController(MaterialController):  # type: ignore[misc]
    """Report metadata races through the material error signal, never Qt callbacks.

    The pinned CuteMica controller protects asynchronous rendering but queries
    file metadata before scheduling it. Its generation counter also guards late
    results; invalidate that generation if a metadata query fails partway through.
    """

    @Slot()
    def refresh(self) -> None:
        """Regenerate material while containing disappearing source files."""

        try:
            super().refresh()
        except (OSError, ValueError) as error:
            failed_generation = self._generation
            self._generation += 1
            self._pending = 0
            self.error.emit(str(error))
            self.generation_finished.emit(failed_generation)

    def set_wallpaper(self, wallpaper: WallpaperSnapshot) -> None:
        """Preserve CuteMica's publication API while containing metadata races."""

        self.update_wallpaper(wallpaper)

    def update_wallpaper(self, wallpaper: WallpaperSnapshot) -> bool:
        """Confirm snapshot acceptance before allowing unchanged-source recovery."""

        try:
            super().set_wallpaper(wallpaper)
        except (OSError, ValueError) as error:
            self.error.emit(str(error))
            return False
        return True
