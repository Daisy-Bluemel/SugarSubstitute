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

"""Own per-test restoration of the simulated Windows process-creation boundary."""

from __future__ import annotations

import ctypes
import sys

import pytest

from sugarsubstitute_shared import windows_ctypes, windows_process_creation
from tests.shared.windows_native.process_creation_boundary import (
    ProcessCreationBoundary,
    WindowsHost,
)


@pytest.fixture
def creation_boundary(monkeypatch: pytest.MonkeyPatch) -> ProcessCreationBoundary:
    """Replace external CRT and kernel symbols while retaining the real adapter."""
    boundary = ProcessCreationBoundary()
    monkeypatch.setitem(sys.modules, "msvcrt", boundary.crt)
    monkeypatch.setattr(windows_ctypes, "sys", WindowsHost())
    monkeypatch.setattr(ctypes, "WinDLL", boundary.load, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", boundary.read_error, raising=False)
    monkeypatch.setattr(ctypes, "WinError", boundary.translate, raising=False)
    monkeypatch.setattr(ctypes, "create_unicode_buffer", boundary.create_unicode_buffer)
    monkeypatch.setattr(
        windows_process_creation, "open", boundary.open_null, raising=False
    )
    return boundary
