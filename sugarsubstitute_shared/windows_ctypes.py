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

"""Own Windows ctypes loading and errors without hiding portable consumer code."""

from __future__ import annotations

import ctypes
import sys


def load_windows_library(name: str, *, use_last_error: bool = False) -> ctypes.CDLL:
    """Load a stdcall library while exposing its portable ctypes base type.

    WinDLL must remain the runtime loader: CDLL's cdecl calling convention is
    not interchangeable with Windows APIs. Last-error swapping is opt-in so
    each native adapter retains the error contract of its library.
    """
    if sys.platform == "win32":
        return ctypes.WinDLL(name, use_last_error=use_last_error)
    raise OSError("Windows native libraries require Windows.")


def windows_last_error() -> int:
    """Read ctypes' thread-local error copy before native cleanup can replace it."""
    if sys.platform == "win32":
        return ctypes.get_last_error()
    raise OSError("Windows native errors require Windows.")


def windows_error(code: int) -> OSError:
    """Preserve Windows' error translation and metadata for an explicit native code."""
    if sys.platform == "win32":
        return ctypes.WinError(code)
    raise OSError("Windows native errors require Windows.")
