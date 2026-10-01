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

"""Test Windows system appearance field ownership and fallback."""

from __future__ import annotations

import pytest

from substitute.application.ports.system_appearance_provider import (
    SystemAppearanceProbe,
)
from substitute.domain.appearance import RgbColor, SystemColorScheme
from substitute.infrastructure.appearance.qt_system_appearance import (
    QtSystemAppearanceProvider,
)
from substitute.infrastructure.appearance.windows_system_appearance import (
    WindowsSystemAppearanceProvider,
)
from tests.infrastructure.appearance.support import StubQtAppearanceReader


class ObservedQtProvider(QtSystemAppearanceProvider):
    """Observe fallback probes while retaining the real Qt provider behavior."""

    def __init__(self) -> None:
        """Supply deterministic Qt fields and an initially unused probe."""

        super().__init__(
            reader=StubQtAppearanceReader(SystemColorScheme.LIGHT, RgbColor(1, 2, 3))
        )
        self.calls = 0

    def probe(self) -> SystemAppearanceProbe:
        """Count every fresh fallback observation."""

        self.calls += 1
        return super().probe()


@pytest.mark.parametrize("native_scheme", [None, SystemColorScheme.DARK])
@pytest.mark.parametrize("native_accent", [None, RgbColor(4, 5, 6)])
def test_provider_prefers_native_fields_and_fills_missing_values(
    native_scheme: SystemColorScheme | None, native_accent: RgbColor | None
) -> None:
    """Keep Windows native and Qt fallback responsibilities field-specific."""

    qt_provider = ObservedQtProvider()
    provider = WindowsSystemAppearanceProvider(
        scheme_reader=lambda: native_scheme,
        accent_reader=lambda: native_accent,
        qt_provider=qt_provider,
    )

    probe = provider.probe()

    assert probe.snapshot.color_scheme is (native_scheme or SystemColorScheme.LIGHT)
    assert probe.snapshot.accent_color == (native_accent or RgbColor(1, 2, 3))
    assert probe.adapter_name == "windows"
    assert probe.color_scheme_source == (
        "windows_registry" if native_scheme is not None else "qt_style_hints"
    )
    assert probe.accent_color_source == (
        "windows_accent" if native_accent is not None else "qt_palette"
    )
    assert qt_provider.calls == 1
