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

"""Keep prepared wallpaper material visible during native window movement."""

from __future__ import annotations

from PySide6.QtGui import QPainter, QPaintEvent
from cutemica.viewport import plan_material_slices  # type: ignore[import-untyped]
from cutemica.widgets.backdrop import PortableMicaBackdrop  # type: ignore[import-untyped]
from cutemica.widgets.material_painter import paint_material_slices  # type: ignore[import-untyped]


class MicaBackdropPresenter(PortableMicaBackdrop):  # type: ignore[misc]
    """Retain the material across activation changes, including X11 WM drags.

    CuteMica 0.1.0 paints its fallback whenever the top-level window becomes
    inactive. X11 can deactivate a window while the pointer is still dragging
    it. Reuse the pinned presenter's stored textures, geometry, slicing and
    metrics while deliberately keeping Substitute's material visible. These
    protected fields are an adapter contract covered by the immutable source pin
    and inactive-paint regression; no texture is regenerated during movement.
    """

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the cached geometry slice even when the WM deactivates its window."""

        started = self._clock()
        slices = ()
        if self._materials and self._window_geometry is not None:
            slices = plan_material_slices(
                self._window_geometry,
                self._controller.bindings,
                self._material_sizes,
            )
        painter = QPainter(self)
        paint_material_slices(
            painter,
            event.rect(),
            self._controller.fallback_color,
            slices,
            self._materials,
            paint_bounds=self.rect(),
        )
        painter.end()
        self._metrics.record((self._clock() - started) * 1000)
