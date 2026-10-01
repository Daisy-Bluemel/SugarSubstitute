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

"""Inject native-module import failures without replacing the import machinery."""

from __future__ import annotations

from collections.abc import Sequence
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
import sys
from types import ModuleType

import pytest


class NativeImportFailure(MetaPathFinder):
    """Raise a configured exception only for one optional native module."""

    def __init__(self, name: str, error: Exception) -> None:
        """Retain the exact import boundary and failure to expose."""

        self.name = name
        self.error = error

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        """Let unrelated imports proceed through the normal finders."""

        if fullname == self.name:
            raise self.error
        return None


def fail_native_import(
    monkeypatch: pytest.MonkeyPatch, name: str, error: Exception
) -> None:
    """Restore the module cache and finder list automatically after each test."""

    monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(
        sys, "meta_path", [NativeImportFailure(name, error), *sys.meta_path]
    )
