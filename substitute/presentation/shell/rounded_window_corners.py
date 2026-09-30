"""Own restored Linux window clipping while preserving native corner policies."""

from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject, QRectF
from PySide6.QtGui import QPainterPath, QPlatformSurfaceEvent, QRegion
from PySide6.QtWidgets import QWidget


_PLATFORM = sys.platform
_CORNER_RADIUS_DIP = 8.0


class RoundedWindowCorners(QObject):
    """Keep a Linux top-level window's native mask aligned with its window state."""

    def __init__(self, window: QWidget) -> None:
        """Attach one lightweight corner owner without replacing native macOS/Windows chrome."""

        super().__init__(window)
        self._window = window
        if _PLATFORM.startswith("linux"):
            window.installEventFilter(self)
            self._apply_mask()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Refresh the shape when geometry, restoration, or a native surface changes."""

        if watched is self._window:
            if event.type() in {
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.WindowStateChange,
                QEvent.Type.WinIdChange,
                QEvent.Type.ParentChange,
            }:
                self._apply_mask()
            elif (
                isinstance(event, QPlatformSurfaceEvent)
                and event.surfaceEventType()
                == QPlatformSurfaceEvent.SurfaceEventType.SurfaceCreated
            ):
                self._apply_mask()
        return super().eventFilter(watched, event)

    def _apply_mask(self) -> None:
        """Use logical-pixel geometry so Qt scales the same 8-DIP outline on every display."""

        window = self._window
        if not window.isWindow() or window.isMaximized() or window.isFullScreen():
            window.clearMask()
            return
        outline = QPainterPath()
        outline.addRoundedRect(
            QRectF(window.rect()), _CORNER_RADIUS_DIP, _CORNER_RADIUS_DIP
        )
        window.setMask(QRegion(outline.toFillPolygon().toPolygon()))
