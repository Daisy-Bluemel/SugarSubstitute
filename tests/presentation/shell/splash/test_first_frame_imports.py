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

"""Protect first-paint startup from the deferred portable-rendering import graph."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_first_visible_splash_frame_excludes_deferred_rendering_dependencies() -> None:
    """Use a fresh process because other widget tests intentionally import Fluent/NumPy."""

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "tests.presentation.shell.splash.first_frame_probe",
        ],
        cwd=Path(__file__).resolve().parents[4],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": "1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == []
