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

"""Characterize native Windows accent precedence, validation, and fallback."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest
from PySide6.QtGui import QColor

from substitute.domain.appearance import RgbColor
from substitute.infrastructure.appearance.windows_system_appearance import (
    read_windows_accent_color,
)
from tests.infrastructure.appearance.windows_import_support import fail_native_import

_HELPER_MODULE = "qframelesswindow.utils.win32_utils"


class AccentHelperModule(ModuleType):
    """Expose a controllable native QColor boundary without loading Windows APIs."""

    def __init__(self, color: object, error: Exception | None = None) -> None:
        """Retain the returned value and optional native failure."""

        super().__init__(_HELPER_MODULE)
        self.color = color
        self.error = error
        self.calls = 0

    def getSystemAccentColor(self) -> object:
        """Observe native fallback use independently of the adapter's validation."""

        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.color


@pytest.fixture
def native_helper(monkeypatch: pytest.MonkeyPatch) -> AccentHelperModule:
    """Install a complete fake package boundary for both native import forms."""

    package = ModuleType("qframelesswindow")
    package.__path__ = []
    utils = ModuleType("qframelesswindow.utils")
    utils.__path__ = []
    helper = AccentHelperModule(QColor(11, 22, 33, 44))
    setattr(package, "utils", utils)
    setattr(utils, "win32_utils", helper)
    monkeypatch.setitem(sys.modules, "qframelesswindow", package)
    monkeypatch.setitem(sys.modules, "qframelesswindow.utils", utils)
    monkeypatch.setitem(sys.modules, _HELPER_MODULE, helper)
    monkeypatch.setitem(sys.modules, "winaccent", ModuleType("winaccent"))
    return helper


@pytest.mark.parametrize("value", ["#12aB34", "  #12AB34 \n"])
def test_valid_winaccent_color_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
    native_helper: AccentHelperModule,
    value: str,
) -> None:
    """Preserve hex parsing and avoid consulting a lower-priority native helper."""

    monkeypatch.setattr(sys.modules["winaccent"], "accent", value, raising=False)

    assert read_windows_accent_color() == RgbColor(18, 171, 52)
    assert native_helper.calls == 0


@pytest.mark.parametrize(
    "value", [None, 12, QColor(1, 2, 3), "", "red", "#123", "#12345678"]
)
def test_unusable_winaccent_values_fall_back_to_native_qcolor(
    monkeypatch: pytest.MonkeyPatch,
    native_helper: AccentHelperModule,
    value: object,
) -> None:
    """Validate optional accent strings before using valid native RGB channels."""

    monkeypatch.setattr(sys.modules["winaccent"], "accent", value, raising=False)

    assert read_windows_accent_color() == RgbColor(11, 22, 33)
    assert native_helper.calls == 1


def test_absent_winaccent_attribute_falls_back_to_native_qcolor(
    native_helper: AccentHelperModule,
) -> None:
    """Accept a native helper QColor while discarding its alpha channel."""

    assert read_windows_accent_color() == RgbColor(11, 22, 33)
    assert native_helper.calls == 1


@pytest.mark.parametrize("error_type", [ModuleNotFoundError, ValueError])
def test_expected_winaccent_import_failure_uses_native_helper(
    monkeypatch: pytest.MonkeyPatch,
    native_helper: AccentHelperModule,
    error_type: type[Exception],
) -> None:
    """Preserve the narrow first-helper fallback exception boundary."""

    fail_native_import(monkeypatch, "winaccent", error_type("winaccent unavailable"))

    assert read_windows_accent_color() == RgbColor(11, 22, 33)
    assert native_helper.calls == 1


@pytest.mark.parametrize("error_type", [ImportError, RuntimeError, TypeError])
def test_unexpected_winaccent_import_failure_propagates(
    monkeypatch: pytest.MonkeyPatch,
    native_helper: AccentHelperModule,
    error_type: type[Exception],
) -> None:
    """Do not hide unexpected first-helper failures by consulting the fallback."""

    error = error_type("unexpected winaccent failure")
    fail_native_import(monkeypatch, "winaccent", error)

    with pytest.raises(error_type) as raised:
        read_windows_accent_color()

    assert raised.value is error
    assert native_helper.calls == 0


@pytest.mark.parametrize("color", [None, "#123456", 123, QColor()])
def test_invalid_native_helper_color_is_unavailable(
    native_helper: AccentHelperModule, color: object
) -> None:
    """Require the fallback result to be an actual valid QColor."""

    native_helper.color = color

    assert read_windows_accent_color() is None
    assert native_helper.calls == 1


@pytest.mark.parametrize("error_type", [AttributeError, ImportError, RuntimeError])
def test_native_helper_failures_are_logged_and_unavailable(
    native_helper: AccentHelperModule,
    caplog: pytest.LogCaptureFixture,
    error_type: type[Exception],
) -> None:
    """Keep expected native failures visible while allowing Qt fallback."""

    error = error_type("accent helper unavailable")
    native_helper.error = error

    assert read_windows_accent_color() is None
    assert "Failed to read Windows accent color" in caplog.text
    assert repr(error) in caplog.text


@pytest.mark.parametrize("error_type", [AttributeError, ImportError, RuntimeError])
def test_native_helper_import_failures_are_logged_and_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    native_helper: AccentHelperModule,
    caplog: pytest.LogCaptureFixture,
    error_type: type[Exception],
) -> None:
    """Catch the same expected failures when they arise during native import."""

    monkeypatch.delattr(sys.modules["qframelesswindow.utils"], "win32_utils")
    error = error_type("accent helper import unavailable")
    fail_native_import(monkeypatch, _HELPER_MODULE, error)

    assert read_windows_accent_color() is None
    assert native_helper.calls == 0
    assert "Failed to read Windows accent color" in caplog.text
    assert repr(error) in caplog.text


@pytest.mark.parametrize("error_type", [OSError, TypeError, ValueError])
def test_unexpected_native_helper_failures_propagate(
    native_helper: AccentHelperModule, error_type: type[Exception]
) -> None:
    """Do not broaden fallback to unrelated native helper failures."""

    error = error_type("unexpected accent helper failure")
    native_helper.error = error

    with pytest.raises(error_type) as raised:
        read_windows_accent_color()

    assert raised.value is error
