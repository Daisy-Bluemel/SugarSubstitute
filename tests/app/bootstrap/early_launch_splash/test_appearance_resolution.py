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

"""Verify read-only early appearance resolution and its lightweight imports."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from substitute.app.bootstrap import early_splash_appearance
from substitute.application.appearance import WindowMaterialCapabilities
from substitute.domain.appearance import (
    AppearanceAccentSource,
    AppearanceBackdropMode,
    AppearanceThemeMode,
    RgbColor,
    SystemAppearanceSnapshot,
    SystemColorScheme,
    default_appearance_preferences,
)
from substitute.infrastructure.persistence.file_appearance_preference_repository import (
    FileAppearancePreferenceRepository,
)


@pytest.mark.parametrize("theme", [AppearanceThemeMode.DARK, AppearanceThemeMode.LIGHT])
@pytest.mark.parametrize(
    "backdrop", [AppearanceBackdropMode.PLAIN, AppearanceBackdropMode.MICA_ALT]
)
def test_saved_explicit_appearance_survives_early_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    theme: AppearanceThemeMode,
    backdrop: AppearanceBackdropMode,
) -> None:
    """Read the authoritative preference file without rewriting user choices."""

    monkeypatch.setattr(
        early_splash_appearance,
        "probe_window_material_capabilities",
        lambda: WindowMaterialCapabilities(mica_alt_available=True),
    )
    preferences = (
        default_appearance_preferences()
        .with_theme_mode(theme)
        .with_backdrop_mode(backdrop)
        .with_accent_source(AppearanceAccentSource.CUSTOM)
        .with_custom_accent_color("#123456")
    )
    settings = tmp_path / "user" / "settings"
    FileAppearancePreferenceRepository(settings).save(preferences)
    preference_file = settings / "appearance.json"
    original_bytes = preference_file.read_bytes()

    resolved = early_splash_appearance.resolve_early_splash_appearance(
        tmp_path, system_appearance=SystemAppearanceSnapshot()
    )

    assert resolved.effective_theme_mode is theme
    assert resolved.effective_accent_color == "#123456"
    assert resolved.effective_backdrop_mode is (
        None if backdrop is AppearanceBackdropMode.PLAIN else backdrop
    )
    assert preference_file.read_bytes() == original_bytes


@pytest.mark.parametrize("content", [b"{broken", b"\xff\xfeinvalid-utf8"])
def test_malformed_appearance_uses_existing_fallback_without_rewriting(
    tmp_path: Path,
    content: bytes,
) -> None:
    """Retain malformed preference bytes while delegating recovery to the repository."""

    preference_file = tmp_path / "user" / "settings" / "appearance.json"
    preference_file.parent.mkdir(parents=True)
    preference_file.write_bytes(content)

    resolved = early_splash_appearance.resolve_early_splash_appearance(
        tmp_path, system_appearance=SystemAppearanceSnapshot()
    )

    assert resolved.effective_theme_mode is AppearanceThemeMode.DARK
    assert preference_file.read_bytes() == content


@pytest.mark.parametrize(
    ("system_snapshot", "expected_theme", "expected_accent"),
    [
        (
            SystemAppearanceSnapshot(SystemColorScheme.LIGHT, RgbColor(17, 34, 51)),
            AppearanceThemeMode.LIGHT,
            "#112233",
        ),
        (
            SystemAppearanceSnapshot(SystemColorScheme.DARK, RgbColor(68, 85, 102)),
            AppearanceThemeMode.DARK,
            "#445566",
        ),
        (SystemAppearanceSnapshot(), AppearanceThemeMode.DARK, "#E91E63"),
    ],
)
@pytest.mark.parametrize("custom_accent", [False, True])
def test_auto_uses_supplied_qt_hints_without_native_polling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    system_snapshot: SystemAppearanceSnapshot,
    expected_theme: AppearanceThemeMode,
    expected_accent: str,
    custom_accent: bool,
) -> None:
    """Use local first-frame hints, retain explicit accent, and defer full native probing."""

    from substitute.infrastructure.appearance import system_appearance_factory

    def reject_native_probe(*_args: object, **_kwargs: object) -> None:
        """Fail if first-frame resolution attempts to construct native/portal polling."""

        raise AssertionError("Native appearance probing must wait until main startup.")

    monkeypatch.setattr(
        system_appearance_factory,
        "build_system_appearance_provider",
        reject_native_probe,
    )
    preferences = default_appearance_preferences()
    if custom_accent:
        preferences = preferences.with_accent_source(
            AppearanceAccentSource.CUSTOM
        ).with_custom_accent_color("#ABCDEF")
    FileAppearancePreferenceRepository(tmp_path / "user" / "settings").save(preferences)

    resolved = early_splash_appearance.resolve_early_splash_appearance(
        tmp_path, system_appearance=system_snapshot
    )

    assert resolved.effective_theme_mode is expected_theme
    assert resolved.effective_accent_color == (
        "#ABCDEF" if custom_accent else expected_accent
    )


def test_appearance_resolution_does_not_import_deferred_renderers(
    tmp_path: Path,
) -> None:
    """Exercise capability probing and preference loading in a fresh process."""

    code = textwrap.dedent(
        """
        import json
        from pathlib import Path
        import sys
        from substitute.app.bootstrap.early_splash_appearance import (
            resolve_early_splash_appearance,
        )
        from substitute.domain.appearance import SystemAppearanceSnapshot
        resolve_early_splash_appearance(
            Path(sys.argv[1]), system_appearance=SystemAppearanceSnapshot()
        )
        prefixes = ('qfluentwidgets', 'cutemica', 'numpy', 'PIL', 'cutecanvas')
        print(json.dumps(sorted(
            name for name in sys.modules
            if any(name == prefix or name.startswith(prefix + '.') for prefix in prefixes)
        )))
        """
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[4],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == []
