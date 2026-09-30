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

"""Verify portable material capability without enabling native Acrylic."""

from __future__ import annotations

import pytest
import substitute.infrastructure.appearance.window_material_probe as probe


from substitute.infrastructure.appearance.window_material_probe import (
    probe_window_material_capabilities,
)


def test_installed_cutemica_enables_portable_mica() -> None:
    """Expose wallpaper Mica while retaining native Acrylic as Windows-only."""

    capabilities = probe_window_material_capabilities(platform_name="linux")
    assert capabilities.mica_alt_available is True
    assert capabilities.acrylic_available is False


def test_macos_material_waits_for_governed_native_wallpaper_cache() -> None:
    """Keep the future macOS provider disabled until its persistent still cache is owned."""

    capabilities = probe_window_material_capabilities(platform_name="darwin")
    assert capabilities.mica_alt_available is False
    assert capabilities.acrylic_available is False


def test_missing_optional_renderer_keeps_plain_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fall back without importing an absent optional material package."""

    monkeypatch.setattr(probe, "find_spec", lambda _name: None)
    assert probe_window_material_capabilities("linux").backdrop_available is False
    assert (
        probe_window_material_capabilities("win32", "10.0.26100").mica_alt_available
        is True
    )
