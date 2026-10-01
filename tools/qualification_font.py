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

"""Scope qualification-only fonts without changing native application typography."""

from __future__ import annotations

from contextlib import AbstractContextManager
import os
from pathlib import Path
import sys
from types import TracebackType
from typing import Self

from PySide6.QtGui import QFont, QFontInfo, QFontMetricsF, QRawFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel

_PROBE_TEXT = "Model 0123"


class QualificationFontSession(AbstractContextManager["QualificationFontSession"]):
    """Retain native font resolution or temporarily register Windows Segoe UI."""

    def __init__(
        self, application: QApplication, *, host_platform: str = sys.platform
    ) -> None:
        """Keep the actual host boundary injectable for Windows policy tests."""

        self._application = application
        self._platform = host_platform
        self._original_font: QFont | None = None
        self._font_id = -1

    def __enter__(self) -> Self:
        """Prepare font resources and roll back even a partially failed setup."""

        if self._original_font is not None:
            raise RuntimeError("A qualification font session is already active.")
        self._original_font = QFont(self._application.font())
        try:
            if self._platform == "win32":
                self._register_windows_font()
            resolved_font_evidence(self._application.font())
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release this session after its capture-owned widgets are disposed."""

        self.close()

    def close(self) -> None:
        """Restore selection before releasing only the registration we own."""

        original = self._original_font
        if original is None:
            return
        self._original_font = None
        try:
            if self._application.font() != original:
                self._application.setFont(original)
        finally:
            font_id, self._font_id = self._font_id, -1
            if font_id >= 0 and not QFontDatabase.removeApplicationFont(font_id):
                raise RuntimeError(
                    f"Qt could not release qualification font registration {font_id}."
                )

    def evidence(self, label: QLabel) -> dict[str, object]:
        """Record actual application and mounted production Fluent font resolution."""

        if self._original_font is None:
            raise RuntimeError(
                "Font evidence requires an active qualification session."
            )
        label.ensurePolished()
        return {
            "platform": self._platform,
            "qt_platform": self._application.platformName(),
            "source": "windows-segoe-ui" if self._font_id >= 0 else "native-qt",
            "application": resolved_font_evidence(self._application.font()),
            "fluent_label": {
                "class": f"{type(label).__module__}.{type(label).__name__}",
                "text": label.text(),
                **resolved_font_evidence(label.font()),
            },
        }

    def _register_windows_font(self) -> None:
        """Preserve the established Windows offscreen Segoe UI/10-point contract."""

        windows_root = os.environ.get("WINDIR")
        if not windows_root:
            raise RuntimeError(
                "WINDIR is required for Windows headless Fluent rendering."
            )
        font_path = Path(windows_root) / "Fonts" / "segoeui.ttf"
        if not font_path.is_file():
            raise RuntimeError(f"Headless Fluent render font is missing: {font_path}")
        self._font_id = QFontDatabase.addApplicationFont(str(font_path))
        if self._font_id < 0:
            raise RuntimeError(f"Qt could not register the render font: {font_path}")
        families = QFontDatabase.applicationFontFamilies(self._font_id)
        if not families:
            raise RuntimeError(f"Qt registered no font family for: {font_path}")
        self._application.setFont(QFont(families[0], 10))


def resolved_font_evidence(font: QFont) -> dict[str, object]:
    """Require a real font with usable qualification glyphs, not a requested name."""

    info = QFontInfo(font)
    raw = QRawFont.fromFont(font)
    metrics = QFontMetricsF(font)
    glyphs = raw.glyphIndexesForString(_PROBE_TEXT) if raw.isValid() else []
    if (
        not raw.isValid()
        or not info.family()
        or metrics.height() <= 0
        or metrics.horizontalAdvance(_PROBE_TEXT) <= 0
        or len(glyphs) != len(_PROBE_TEXT)
        or not all(glyphs)
    ):
        raise RuntimeError(
            "Qt could not resolve a readable qualification font: "
            f"requested={font.families()!r}, resolved={info.family()!r}."
        )
    return {
        "requested_families": font.families(),
        "resolved_family": info.family(),
        "raw_family": raw.familyName(),
        "point_size": info.pointSizeF(),
        "pixel_size": info.pixelSize(),
        "probe_text": _PROBE_TEXT,
        "probe_advance": metrics.horizontalAdvance(_PROBE_TEXT),
        "glyphs_available": True,
    }


__all__ = ["QualificationFontSession", "resolved_font_evidence"]
