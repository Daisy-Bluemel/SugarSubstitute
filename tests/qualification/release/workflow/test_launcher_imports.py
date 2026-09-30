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

"""Protect native launcher imports needed by IPC and portable material rendering."""

from __future__ import annotations

import ast

import pytest

from tests.qualification.release.workflow.support import PROJECT_ROOT

_LINUX_SPECS = (
    "SugarSubstitute-Linux-x64.spec",
    "SugarSubstitute-Setup-Linux-x64.spec",
)
_MACOS_SPECS = (
    "SugarSubstitute-macOS-arm64.spec",
    "SugarSubstitute-Setup-macOS-arm64.spec",
)
_WINDOWS_SPECS = (
    "SugarSubstitute-Windows-x64.spec",
    "SugarSubstitute-Setup-Windows-x64.spec",
    "SugarSubstitute-Local-Test-Installer-Windows-x64.spec",
)


@pytest.mark.parametrize("name", _LINUX_SPECS)
def test_linux_launcher_specs_bundle_native_singleton_dependencies(name: str) -> None:
    """Retain dynamically selected Linux IPC adapters regardless of import order."""

    imports = _analysis_literals(name, "hiddenimports")

    assert {"jeepney", "jeepney.io.blocking"} <= imports


@pytest.mark.parametrize("name", _MACOS_SPECS)
def test_macos_launcher_specs_bundle_native_adapters(name: str) -> None:
    """Retain the existing macOS native IPC adapter in both launchers."""

    imports = _analysis_literals(name, "hiddenimports")

    assert "AppKit" in imports


@pytest.mark.parametrize("name", _LINUX_SPECS)
def test_linux_launcher_specs_bundle_portable_material_dependencies(name: str) -> None:
    """Keep the optional renderer and its image-processing dependencies available."""

    imports = _analysis_literals(name, "hiddenimports")
    excluded = _analysis_literals(name, "excludes")

    assert "cutemica.widgets" in imports
    assert not {"cutemica", "numpy", "PIL"} & excluded


@pytest.mark.parametrize("name", (*_WINDOWS_SPECS, *_MACOS_SPECS))
def test_native_launcher_specs_exclude_development_only_renderer(name: str) -> None:
    """Preserve native materials without bundling the unvalidated typing dependency."""

    assert {"cutemica", "numpy", "PIL"} <= _analysis_literals(name, "excludes")
    assert not any(
        module == "cutemica" or module.startswith("cutemica.")
        for module in _analysis_literals(name, "hiddenimports")
    )


def _analysis_literals(name: str, keyword: str) -> set[str]:
    """Read explicitly configured module names without executing packaging code."""

    source = (PROJECT_ROOT / "launcher" / name).read_text(encoding="utf-8")
    module = ast.parse(source, filename=name)
    analyses = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Analysis"
    ]
    assert analyses
    configured = [
        argument.value
        for analysis in analyses
        for argument in analysis.keywords
        if argument.arg == keyword and isinstance(argument.value, ast.List)
    ]
    assert configured
    return {
        element.value
        for value in configured
        for element in value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }
