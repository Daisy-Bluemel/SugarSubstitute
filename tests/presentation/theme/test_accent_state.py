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

"""Verify exact restoration of test-owned Fluent accent state."""

from __future__ import annotations

from contextlib import nullcontext

import pytest
from PySide6.QtGui import QColor
from qfluentwidgets import Theme, qconfig  # type: ignore[import-untyped]
from qfluentwidgets.common.style_sheet import themeColor  # type: ignore[import-untyped]

from tests.presentation.theme.support import ThemeWidgetOwner, fluent_accent


@pytest.mark.parametrize(
    "finish_with_error", [False, True], ids=["normal", "exception"]
)
def test_fluent_accent_restores_exact_configured_color_in_dark_mode(
    theme_owner: ThemeWidgetOwner,
    finish_with_error: bool,
) -> None:
    """Restore the configured color rather than its transformed dark-mode value."""

    original_accent = QColor(qconfig.get(qconfig.themeColor))
    configured_accent = QColor("#e91e63")
    temporary_accent = QColor("#009faa")
    with fluent_accent(configured_accent), theme_owner.using_theme(Theme.DARK):
        assert QColor(themeColor()) != configured_accent
        expectation = (
            pytest.raises(RuntimeError, match="accent scope failure")
            if finish_with_error
            else nullcontext()
        )
        with expectation:
            with fluent_accent(temporary_accent):
                assert qconfig.get(qconfig.themeColor) == temporary_accent
                assert qconfig.get(qconfig.themeMode) is Theme.DARK
                assert qconfig.theme is Theme.DARK
                if finish_with_error:
                    raise RuntimeError("accent scope failure")
        assert qconfig.get(qconfig.themeColor) == configured_accent
        assert qconfig.get(qconfig.themeMode) is Theme.DARK
        assert qconfig.theme is Theme.DARK
    assert qconfig.get(qconfig.themeColor) == original_accent
