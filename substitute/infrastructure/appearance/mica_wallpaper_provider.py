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

"""Select desktop wallpaper discovery or an explicitly watched material source."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from cutemica.providers.capabilities import (  # type: ignore[import-untyped]
    ProviderCapabilities,
    WindowRegistration,
)
from cutemica.providers.explicit_wallpaper import ExplicitWallpaperProvider  # type: ignore[import-untyped]
from cutemica.providers.system_wallpaper import create_system_wallpaper_provider  # type: ignore[import-untyped]
from cutemica.providers.wallpaper_provider import WallpaperProvider  # type: ignore[import-untyped]


class WatchedWallpaperProvider(ExplicitWallpaperProvider):  # type: ignore[misc]
    """Track revisions of an explicit image using CuteMica's metadata monitor."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Enable changes for a stable application-supplied wallpaper path."""

        return ProviderCapabilities(
            automatic_wallpaper=False,
            wallpaper_changes=True,
            per_screen_wallpaper=False,
            window_registration=WindowRegistration.GLOBAL,
        )


def create_mica_wallpaper_provider() -> WallpaperProvider:
    """Prefer an explicit source only when the environment selects one.

    Custom desktops without published wallpaper metadata can provide the same
    image they display. Linux desktop discovery remains the default. The macOS
    provider stays disabled until its native still-image cache is governed.
    """

    explicit = os.environ.get("SUGARSUBSTITUTE_MICA_WALLPAPER")
    if explicit:
        return WatchedWallpaperProvider(Path(explicit).expanduser())
    if sys.platform != "linux":
        raise RuntimeError(
            "Portable Mica wallpaper discovery is currently supported on Linux"
        )
    return create_system_wallpaper_provider()
