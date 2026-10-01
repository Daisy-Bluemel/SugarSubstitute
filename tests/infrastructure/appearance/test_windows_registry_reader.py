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

"""Characterize Windows theme registry access, cleanup, and failure boundaries."""

from __future__ import annotations

from contextlib import AbstractContextManager
import sys
from types import ModuleType, TracebackType
from typing import Literal

import pytest

from substitute.domain.appearance import SystemColorScheme
from substitute.infrastructure.appearance.windows_system_appearance import (
    read_windows_color_scheme,
)
from tests.infrastructure.appearance.windows_import_support import fail_native_import

RegistryStage = Literal["open", "enter", "query", "exit"]


class RegistryKey(AbstractContextManager[object]):
    """Track handle lifetime while exposing failures at native lifecycle boundaries."""

    def __init__(self, stage: RegistryStage | None, error: Exception | None) -> None:
        """Store the selected failure and an initially unopened handle."""

        self.stage = stage
        self.error = error
        self.entered = False
        self.closed = False

    def __enter__(self) -> object:
        """Expose a handle only after entry succeeds."""

        self.fail_at("enter")
        self.entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the handle even when querying raises an exception."""

        self.closed = True
        self.fail_at("exit")

    def fail_at(self, stage: RegistryStage) -> None:
        """Raise only at the native boundary selected by the test."""

        if self.stage == stage and self.error is not None:
            raise self.error


class RegistryModule(ModuleType):
    """Supply only the registry operations used to read the application theme."""

    HKEY_CURRENT_USER = 0x80000001

    def __init__(
        self,
        value: object = 0,
        stage: RegistryStage | None = None,
        error: Exception | None = None,
    ) -> None:
        """Keep native calls and the key lifecycle inspectable."""

        super().__init__("winreg")
        self.value = value
        self.key = RegistryKey(stage, error)
        self.opened: tuple[int, str] | None = None
        self.queried: tuple[object, str] | None = None

    def OpenKey(self, hive: int, path: str) -> AbstractContextManager[object]:
        """Record the two-argument default-read registry request."""

        self.opened = (hive, path)
        self.key.fail_at("open")
        return self.key

    def QueryValueEx(self, key: object, name: str) -> tuple[object, int]:
        """Reject reads outside the acquired handle's lifetime."""

        assert key is self.key and self.key.entered and not self.key.closed
        self.queried = (key, name)
        self.key.fail_at("query")
        return self.value, 4


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, SystemColorScheme.DARK),
        (1, SystemColorScheme.LIGHT),
        (False, SystemColorScheme.DARK),
        (True, SystemColorScheme.LIGHT),
        (0.0, SystemColorScheme.DARK),
        (1.0, SystemColorScheme.LIGHT),
        (2, None),
        ("0", None),
        (None, None),
    ],
)
def test_registry_reads_app_theme_and_closes_key(
    monkeypatch: pytest.MonkeyPatch,
    value: object,
    expected: SystemColorScheme | None,
) -> None:
    """Preserve equality-based theme values and the precise Windows read contract."""

    registry = RegistryModule(value)
    monkeypatch.setitem(sys.modules, "winreg", registry)

    assert read_windows_color_scheme() is expected

    assert registry.opened == (
        RegistryModule.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
    )
    assert registry.queried == (registry.key, "AppsUseLightTheme")
    assert registry.key.closed


@pytest.mark.parametrize("stage", ["open", "enter", "query", "exit"])
@pytest.mark.parametrize("error_type", [OSError, ImportError])
def test_registry_native_failures_are_logged_and_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage: RegistryStage,
    error_type: type[Exception],
) -> None:
    """Preserve fallback and handle cleanup across expected native failures."""

    error = error_type("registry unavailable")
    registry = RegistryModule(stage=stage, error=error)
    monkeypatch.setitem(sys.modules, "winreg", registry)

    assert read_windows_color_scheme() is None

    assert registry.key.closed is (stage in {"query", "exit"})
    assert "Failed to read Windows application color scheme" in caplog.text
    assert repr(error) in caplog.text


@pytest.mark.parametrize("error_type", [OSError, ImportError, ModuleNotFoundError])
def test_registry_import_failures_are_logged_and_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error_type: type[Exception],
) -> None:
    """Keep missing or unavailable native imports inside the registry fallback."""

    error = error_type("registry import unavailable")
    fail_native_import(monkeypatch, "winreg", error)

    assert read_windows_color_scheme() is None
    assert "Failed to read Windows application color scheme" in caplog.text
    assert repr(error) in caplog.text


@pytest.mark.parametrize(
    "error_type", [AttributeError, RuntimeError, TypeError, ValueError]
)
def test_unexpected_registry_errors_propagate_after_cleanup(
    monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    """Avoid converting unexpected native failures into a missing theme value."""

    error = error_type("unexpected registry failure")
    registry = RegistryModule(stage="query", error=error)
    monkeypatch.setitem(sys.modules, "winreg", registry)

    with pytest.raises(error_type) as raised:
        read_windows_color_scheme()

    assert raised.value is error
    assert registry.key.closed
