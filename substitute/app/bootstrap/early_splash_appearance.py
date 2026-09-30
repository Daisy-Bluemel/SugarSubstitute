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

"""Resolve persisted splash appearance without importing the rendering runtime."""

from __future__ import annotations

from pathlib import Path

from sugarsubstitute_shared.windows_long_paths import operational_path

from substitute.application.appearance.appearance_preference_service import (
    AppearancePreferenceService,
)
from substitute.application.appearance.appearance_resolver import (
    AppearanceResolver,
    ResolvedAppearance,
)
from substitute.domain.appearance import SystemAppearanceSnapshot
from substitute.infrastructure.appearance.window_material_probe import (
    probe_window_material_capabilities,
)
from substitute.infrastructure.persistence.file_appearance_preference_repository import (
    FileAppearancePreferenceRepository,
)


def resolve_early_splash_appearance(
    install_root: Path,
    *,
    system_appearance: SystemAppearanceSnapshot,
) -> ResolvedAppearance:
    """Reuse durable preference and capability policy before expensive UI enrichment.

    The host supplies already-available Qt hints rather than starting native
    desktop polling on the first-frame critical path. Explicit user choices
    retain the same domain precedence as the main application.
    """

    normalized_root = operational_path(install_root).resolve()
    preferences = AppearancePreferenceService(
        FileAppearancePreferenceRepository(normalized_root / "user" / "settings")
    ).load_preferences()
    return AppearanceResolver(probe_window_material_capabilities()).resolve(
        preferences, system_appearance=system_appearance
    )
