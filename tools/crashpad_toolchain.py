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

"""Validate the Linux compiler contract consumed by pinned mini_chromium GN."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys


def resolve_clang_toolchain(requested_root: Path | None) -> Path | None:
    """Reject unusable Linux compilers before downloading native dependencies.

    mini_chromium appends ``bin`` to an explicit ``clang_path``. Without an
    override it resolves clang, clang++, and ar from PATH, ignoring CC/CXX.
    The syntax probe proves the required C++23 spelling, not a complete native
    build or compatibility with the host C++ standard library.
    """

    if not sys.platform.startswith("linux"):
        if requested_root is not None:
            raise RuntimeError("--clang-path is supported only for Linux builds.")
        return None
    root = requested_root.expanduser().resolve() if requested_root is not None else None
    if root is not None and any(
        character.isspace() or character in "\"'\\`$;&|<>()[]{}*?!~#"
        for character in root.as_posix()
    ):
        raise RuntimeError(
            "The Clang toolchain root must not contain whitespace or shell "
            "metacharacters: pinned mini_chromium invokes its tools without quoting."
        )
    names = ("clang", "clang++", "llvm-ar" if root is not None else "ar")
    tools: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        executable = shutil.which(
            str(root / "bin" / name) if root is not None else name
        )
        if executable is None:
            missing.append(name)
        else:
            tools[name] = executable
    if missing:
        raise RuntimeError(
            f"The Linux Clang toolchain is missing executable tools: {', '.join(missing)}. "
            "Install Clang on PATH or pass --clang-path with the toolchain root "
            "containing bin/clang, bin/clang++, and bin/llvm-ar."
        )
    _require_cpp23(tools["clang++"])
    return root


def _require_cpp23(compiler: str) -> None:
    """Check the exact language flag without linking or writing build outputs."""

    try:
        result = subprocess.run(  # noqa: S603
            [compiler, "-std=c++23", "-x", "c++", "-fsyntax-only", "-"],
            input="int main() { return 0; }\n",
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(
            "The Linux Clang C++23 prerequisite probe failed."
        ) from error
    if result.returncode != 0:
        raise RuntimeError(
            "The Linux Clang toolchain must accept -std=c++23. "
            f"Compiler diagnostic: {result.stderr.strip()}"
        )
