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

"""Characterize system-locale selection at the platform spellcheck boundary."""

from __future__ import annotations

import ctypes
import locale
from dataclasses import dataclass

import pytest

from substitute.infrastructure.spellcheck import factory
from sugarsubstitute_shared import windows_ctypes


@dataclass(frozen=True)
class _Host:
    """Control one adapter's platform without changing the runner's platform."""

    platform: str


class _Kernel32(ctypes.CDLL):
    """Supply a controlled locale API without loading an operating-system DLL."""

    def __init__(self, locale_name: str, result: int | Exception) -> None:
        """Store the native response without constructing a real CDLL."""
        self.locale_name = locale_name
        self.result = result
        self.buffers: list[tuple[int, int, str]] = []

    def GetUserDefaultLocaleName(
        self, buffer: ctypes.Array[ctypes.c_wchar], capacity: int
    ) -> int:
        """Record the buffer contract and supply the configured native response."""
        self.buffers.append((len(buffer), capacity, buffer.value))
        if isinstance(self.result, Exception):
            raise self.result
        buffer.value = self.locale_name
        return self.result


@pytest.mark.parametrize("language", ["en_US", " fr-FR ", "zh_Hant_TW", "en_"])
def test_current_portable_locale_takes_precedence(
    monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    """Trim a portable current locale without consulting the deprecated fallback."""

    def current_locale() -> tuple[str, None]:
        """Return the controlled current locale."""
        return language, None

    def unexpected_fallback() -> tuple[None, None]:
        """Reject an unnecessary deprecated-locale lookup."""
        pytest.fail("A portable current locale must take precedence.")

    monkeypatch.setattr(factory, "sys", _Host("linux"))
    monkeypatch.setattr(locale, "getlocale", current_locale)
    monkeypatch.setattr(locale, "getdefaultlocale", unexpected_fallback)
    assert factory.default_spellcheck_language_tag() == language.strip()


@pytest.mark.parametrize("language", [None, "", "  ", "C", "en", "English_US", "12_US"])
@pytest.mark.parametrize("fallback", [" de_DE ", None, "", "C"])
def test_nonportable_current_locale_uses_fallback_or_english(
    monkeypatch: pytest.MonkeyPatch, language: str | None, fallback: str | None
) -> None:
    """Keep blank, missing, and nonportable locale values safe before stripping."""

    def current_locale() -> tuple[str | None, None]:
        """Supply a current locale that cannot be used as a portable tag."""
        return language, None

    def fallback_locale() -> tuple[str | None, None]:
        """Supply a portable fallback or another unusable locale."""
        return fallback, None

    monkeypatch.setattr(factory, "sys", _Host("linux"))
    monkeypatch.setattr(locale, "getlocale", current_locale)
    monkeypatch.setattr(locale, "getdefaultlocale", fallback_locale)
    assert factory.default_spellcheck_language_tag() == (
        "de_DE" if fallback == " de_DE " else "en_US"
    )


@pytest.mark.parametrize(
    ("locale_name", "result", "expected"),
    [
        (" fr-FR ", 8, "fr-FR"),
        ("ja-JP", 6, "ja-JP"),
        ("fr-FR", 0, "en-US"),
        ("fr-FR", -1, "en-US"),
        ("", 1, "en-US"),
        ("   ", 4, "en-US"),
        ("", OSError("native locale failure"), "en-US"),
    ],
)
def test_windows_locale_preserves_buffer_and_fallback_contract(
    monkeypatch: pytest.MonkeyPatch,
    locale_name: str,
    result: int | Exception,
    expected: str,
) -> None:
    """Use the fixed wide buffer and accept only nonempty successful native output."""
    kernel = _Kernel32(locale_name, result)
    monkeypatch.setattr(factory, "sys", _Host("win32"))
    loads: list[tuple[str, bool]] = []

    def load(name: str, *, use_last_error: bool = False) -> ctypes.CDLL:
        """Capture the stdcall loader contract without changing native signatures."""
        loads.append((name, use_last_error))
        return kernel

    monkeypatch.setattr(windows_ctypes, "sys", _Host("win32"))
    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    assert factory.default_spellcheck_language_tag() == expected
    assert kernel.buffers == [(85, 85, "")]
    assert loads == [("kernel32", False)]


def test_windows_locale_library_failure_uses_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep native-library loading failure inside the locale fallback boundary."""
    monkeypatch.setattr(factory, "sys", _Host("win32"))

    def fail_load(name: str, *, use_last_error: bool = False) -> ctypes.CDLL:
        """Reject loading with the original adapter's default last-error mode."""
        assert name == "kernel32"
        assert use_last_error is False
        raise OSError("missing kernel32")

    monkeypatch.setattr(windows_ctypes, "sys", _Host("win32"))
    monkeypatch.setattr(ctypes, "WinDLL", fail_load, raising=False)
    assert factory.default_spellcheck_language_tag() == "en-US"
