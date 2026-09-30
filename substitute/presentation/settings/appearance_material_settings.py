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

"""Own window-material settings, capability projection, and restart-required saves."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon  # type: ignore[import-untyped]

from sugarsubstitute_shared.localization import app_text
from substitute.application.appearance import AppearanceRestartCoordinator
from substitute.domain.appearance import AppearanceBackdropMode
from substitute.presentation.settings.appearance_runtime_protocol import (
    AppearanceRuntimeProtocol,
)
from substitute.presentation.settings.settings_card import SettingsCard
from substitute.presentation.settings.settings_catalog import (
    SettingsControlEntry,
    SettingsSectionEntry,
)
from substitute.presentation.settings.settings_row_factories import (
    build_combo_settings_row,
)


class AppearanceMaterialSettings:
    """Present supported materials and delegate persistence to the restart owner."""

    def __init__(
        self,
        *,
        appearance_runtime: AppearanceRuntimeProtocol,
        restart_coordinator: AppearanceRestartCoordinator,
        show_restart_requirements: Callable[[], None] | None,
    ) -> None:
        """Store the appearance owners used by the material control."""

        self._runtime = appearance_runtime
        self._restart_coordinator = restart_coordinator
        self._show_restart_requirements = show_restart_requirements

    def section(self) -> SettingsSectionEntry:
        """Build searchable metadata for the window-material control."""

        return SettingsSectionEntry(
            "appearance.window",
            app_text("Window"),
            "",
            20,
            (
                SettingsControlEntry(
                    "appearance.window.material",
                    app_text("Window material"),
                    app_text("Plain is used when window effects are unavailable."),
                    (
                        "theme",
                        "dark",
                        "light",
                        "color",
                        "accent",
                        "window",
                        "material",
                        "plain",
                        "mica",
                        "acrylic",
                    ),
                    10,
                    self.material_row,
                ),
            ),
        )

    def material_row(self, parent: QWidget) -> SettingsCard:
        """Offer Plain and supported effects without changing saved preferences."""

        resolved = self._runtime.resolve_preferences()
        options: list[tuple[str, object]] = [
            (app_text("Plain"), AppearanceBackdropMode.PLAIN)
        ]
        if resolved.capabilities.mica_alt_available:
            options.append((app_text("Mica"), AppearanceBackdropMode.MICA_ALT))
        if resolved.capabilities.acrylic_available:
            options.append((app_text("Acrylic"), AppearanceBackdropMode.ACRYLIC))
        selected = resolved.requested.backdrop_mode
        if selected not in {value for _label, value in options}:
            selected = resolved.effective_backdrop_mode or AppearanceBackdropMode.PLAIN
        return build_combo_settings_row(
            parent=parent,
            icon=FluentIcon.BACKGROUND_FILL,
            title=app_text("Window material"),
            description=app_text("Plain is used when window effects are unavailable."),
            options=tuple(options),
            selected=selected,
            on_changed=self._save_material,
        )

    def _save_material(self, value: object) -> None:
        """Save a valid selection and show existing pending restart requirements."""

        if not isinstance(value, AppearanceBackdropMode):
            return
        snapshot = self._restart_coordinator.set_backdrop_mode(value)
        if snapshot.count > 0 and self._show_restart_requirements is not None:
            self._show_restart_requirements()


__all__ = ["AppearanceMaterialSettings"]
