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

"""Protect exact verified runtime and toolchain dependencies."""

from __future__ import annotations

from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_EXPECTED_RUNTIME_DEPENDENCIES = frozenset(
    {
        "comtypes",
        "cryptography",
        "cutecanvas",
        "cutemica",
        "ferrastra",
        "ijson",
        "jeepney",
        "keyring",
        "pillow",
        "photoshop",
        "py7zr",
        "pyenchant",
        "pygit2",
        "pyobjc-core",
        "pyobjc-framework-cocoa",
        "psutil",
        "python-mpv",
        "pyside6",
        "pyside6-fluent-widgets",
        "pysidesix-frameless-window",
        "qpane",
        "requests",
        "truststore",
        "websocket-client",
        "winaccent",
    }
)
_EXPECTED_TOOLCHAIN_DEPENDENCIES = frozenset(
    {
        "certifi",
        "cutemica",
        "mypy",
        "pip",
        "pip-audit",
        "pre-commit",
        "pyinstaller",
        "pywinauto",
        "pytest",
        "pytest-xdist",
        "ruff",
        "uv",
    }
)


def test_runtime_requirements_match_verified_versions() -> None:
    """Keep every direct runtime dependency at its verified version."""

    requirements = _read_runtime_requirements()

    assert requirements.keys() == _EXPECTED_RUNTIME_DEPENDENCIES
    for requirement in requirements.values():
        _assert_verified_pin(requirement)


def test_toolchain_requirements_match_verified_versions() -> None:
    """Keep every development and CI tool at its verified version."""

    requirements = _read_requirements("requirements-toolchain.txt")

    assert requirements.keys() == _EXPECTED_TOOLCHAIN_DEPENDENCIES
    for requirement in requirements.values():
        _assert_verified_pin(requirement)


@pytest.mark.parametrize(
    ("platform", "runtime", "toolchain"),
    (("linux", True, False), ("darwin", False, True), ("win32", False, True)),
)
def test_cutemica_platform_dependencies(
    platform: str, runtime: bool, toolchain: bool
) -> None:
    """Install the portable renderer at runtime only on validated Linux targets."""

    runtime_requirement = _read_runtime_requirements()["cutemica"]
    toolchain_requirement = _read_requirements("requirements-toolchain.txt")["cutemica"]

    assert runtime_requirement.marker is not None
    assert toolchain_requirement.marker is not None
    assert runtime_requirement.marker.evaluate({"sys_platform": platform}) is runtime
    assert (
        toolchain_requirement.marker.evaluate({"sys_platform": platform}) is toolchain
    )
    assert runtime_requirement.url == toolchain_requirement.url


def test_cutemica_toolchain_lock_preserves_reviewed_archive_digest() -> None:
    """Require hash-locked CI installs to use the same portable source revision."""

    lines = (
        (_REPOSITORY_ROOT / "requirements-toolchain.lock")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    entries = [
        (index, Requirement(line.rstrip("\\").strip()))
        for index, line in enumerate(lines)
        if line.lower().startswith("cutemica ")
    ]

    assert len(entries) == 1
    index, locked = entries[0]
    runtime = _read_runtime_requirements()["cutemica"]
    assert runtime.url is not None
    _, fragment = runtime.url.split("#", maxsplit=1)
    assert locked.url == runtime.url
    assert lines[index + 1].strip() == f"--hash={fragment.replace('=', ':', 1)}"
    for platform in ("linux", "darwin", "win32"):
        assert locked.marker is None or locked.marker.evaluate(
            {"sys_platform": platform}
        )


def _assert_verified_pin(requirement: Requirement) -> None:
    """Allow only the reviewed immutable CuteMica archive outside the registry."""

    if canonicalize_name(requirement.name) == "cutemica":
        assert requirement.url == (
            "https://github.com/Daisy-Bluemel/CuteMica/archive/"
            "831ec759d867ddd566bf2ec44154d4577ea8b8ee.tar.gz"
            "#sha256=d11cbb7a4c42d0a1078daf7ce374c4a242986603dbd8cce4d74b516aeb0e1d2b"
        )
        assert not requirement.specifier
        assert not requirement.extras
        return
    _assert_exact_registry_pin(requirement)


def _assert_exact_registry_pin(requirement: Requirement) -> None:
    """Require one immutable registry version without duplicating its value."""

    specifiers = tuple(requirement.specifier)
    assert requirement.url is None
    assert len(specifiers) == 1
    assert specifiers[0].operator == "=="
    assert specifiers[0].version


def _read_runtime_requirements() -> dict[str, Requirement]:
    """Parse declared requirements while preserving environment-marker entries."""

    return _read_requirements("requirements.txt")


def _read_requirements(filename: str) -> dict[str, Requirement]:
    """Parse direct requirement entries from one repository requirement file."""

    requirements: dict[str, Requirement] = {}
    for raw_line in (
        (_REPOSITORY_ROOT / filename).read_text(encoding="utf-8").splitlines()
    ):
        line = raw_line.split(" #", maxsplit=1)[0].strip()
        if not line or line.startswith(("#", "-r ")):
            continue
        requirement = Requirement(line)
        requirements[canonicalize_name(requirement.name)] = requirement
    return requirements
