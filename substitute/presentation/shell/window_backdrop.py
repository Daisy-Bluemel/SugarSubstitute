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

"""Select native or portable window material with one opaque fallback owner."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Protocol, cast

from PySide6.QtCore import QObject, Slot
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget

from substitute.presentation.shell.window_effects import (
    ShellBackdropMode,
    apply_acrylic_effect,
    remove_native_background,
)
from substitute.shared.logging.logger import get_logger, log_warning

if TYPE_CHECKING:
    from substitute.presentation.shell.portable_mica_surface import PortableMicaSurface

_LOGGER = get_logger("presentation.shell.window_backdrop")


class _NativeEffects(Protocol):
    """Describe the qframeless material operation used at the native boundary."""

    def setMicaEffect(self, handle: object, *, isDarkMode: bool, isAlt: bool) -> None:
        """Apply the existing Windows material implementation."""


class WindowBackdrop(QObject):
    """Own effective material, fallback color and portable renderer lifetime.

    Imports remain lightweight until portable material is explicitly enabled, so
    the startup splash can paint a correct base before loading image processors.
    Platform identity is captured per owner, including during native test probes.
    """

    def __init__(self, window: QWidget, *, platform_name: str | None = None) -> None:
        """Retain one window and its initial toolkit style."""

        super().__init__(window)
        self._window = window
        self._platform = platform_name or sys.platform
        self._base_style = window.styleSheet()
        self._dark = False
        self._portable: PortableMicaSurface | None = None
        self._native_identity: tuple[str | None, bool, int] | None = None
        self._provider_name = "plain"

    @property
    def provider_name(self) -> str:
        """Report actual portable publication or successfully applied native mode."""

        return self._provider_name

    def apply(
        self,
        mode: ShellBackdropMode | str | None,
        *,
        dark: bool,
        portable: bool = True,
    ) -> None:
        """Apply one requested material while preserving truthful fallback state."""

        value = mode.value if isinstance(mode, ShellBackdropMode) else mode
        self._dark = dark
        if self._platform == "win32":
            self._apply_native(value, dark)
            return
        self._apply_plain()
        if value not in {"mica", "mica_alt"} or self._platform != "linux":
            self._release_portable()
            return
        if not portable:
            return
        if self._portable is not None:
            self._portable.set_dark(dark)
            self._portable_state_changed(self._portable.ready)
            return
        try:
            from substitute.presentation.shell.portable_mica_surface import (
                PortableMicaSurface,
            )

            self._portable = PortableMicaSurface(self._window, dark=dark)
            self._portable.state_changed.connect(self._portable_state_changed)
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            log_warning(
                _LOGGER,
                "Portable Mica initialization failed; using Plain",
                error=repr(error),
            )
            self._release_portable()

    def _apply_native(self, value: str | None, dark: bool) -> None:
        """Retain the existing Windows provider and clear effects for Plain."""

        identity = (value, dark, int(self._window.winId()))
        if identity == self._native_identity:
            return
        self._apply_plain()
        try:
            if value == "acrylic":
                apply_acrylic_effect(self._window)
            elif value in {"mica", "mica_alt"}:
                effect = cast(_NativeEffects, getattr(self._window, "windowEffect"))
                effect.setMicaEffect(
                    self._window.winId(), isDarkMode=dark, isAlt=value == "mica_alt"
                )
            else:
                remove_native_background(self._window)
                self._native_identity = identity
                return
            self._window.setStyleSheet(self._base_style)
            self._window.setAutoFillBackground(False)
            self._provider_name = "windows-" + value
            self._native_identity = identity
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as error:
            log_warning(
                _LOGGER,
                "Native material unavailable; using Plain",
                material=value,
                error=repr(error),
            )

    def _apply_plain(self) -> None:
        """Override inherited transparent styles with an opaque root-only surface."""

        color = QColor("#202020" if self._dark else "#F8F8F8")
        palette = self._window.palette()
        palette.setColor(QPalette.ColorRole.Window, color)
        self._window.setPalette(palette)
        self._window.setProperty("substitutePlainBackdrop", True)
        self._window.setStyleSheet(
            self._base_style
            + '\nQWidget[substitutePlainBackdrop="true"] {'
            + f"background-color: {color.name()};"
            + "}"
        )
        self._window.setAutoFillBackground(True)
        self._provider_name = "plain"

    @Slot(bool)
    def _portable_state_changed(self, ready: bool) -> None:
        """Claim portable Mica only after actual texture publication."""

        self._provider_name = "cutemica" if ready else "plain"

    def _release_portable(self) -> None:
        """Dispose portable observation when Plain or another material is selected."""

        if self._portable is not None:
            self._portable.state_changed.disconnect(self._portable_state_changed)
            self._portable.dispose()
            self._portable.deleteLater()
            self._portable = None
        self._provider_name = "plain"
