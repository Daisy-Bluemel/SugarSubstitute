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
