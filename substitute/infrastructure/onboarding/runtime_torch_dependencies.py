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

"""Install and retain the app runtime's selected Torch distribution with pip."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from sugarsubstitute_shared.app_runtime_torch import AppRuntimeTorchPolicy
from sugarsubstitute_shared.windows_long_paths import subprocess_path


def install_runtime_torch(
    python_executable: Path, policy: AppRuntimeTorchPolicy
) -> tuple[str, ...]:
    """Install CPU support wheels and constrain the later app dependency resolver.

    A newer or mixed GPU installation must be replaced even when pip regards its
    version as satisfying an unpinned requirement. Read metadata without importing
    Torch so incomplete native installations remain repairable.
    """
    installed = _installed_versions(python_executable, policy.packages)
    command = [
        subprocess_path(python_executable),
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--index-url",
        policy.index_url,
    ]
    if any(version and not version.endswith("+cpu") for version in installed):
        command.append("--force-reinstall")
    command.extend(policy.packages)
    try:
        subprocess.run(command, check=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(
            "Failed to install CPU Torch for the Substitute runtime."
        ) from error
    resolved = _installed_versions(python_executable, policy.packages)
    if not all(
        re.fullmatch(r"\d+(?:\.\d+){1,3}\+cpu", version) for version in resolved
    ):
        raise RuntimeError(
            "Substitute runtime Torch packages did not resolve to stable CPU builds."
        )
    return tuple(
        f"{package}=={version}"
        for package, version in zip(policy.packages, resolved, strict=True)
    )


def _installed_versions(
    python_executable: Path, packages: tuple[str, ...]
) -> tuple[str, ...]:
    """Read only target-interpreter distribution metadata with a bounded probe."""
    script = (
        "import importlib.metadata as metadata, json, sys\n"
        "versions = []\n"
        "for package in sys.argv[1:]:\n"
        "    try:\n"
        "        versions.append(metadata.version(package))\n"
        "    except metadata.PackageNotFoundError:\n"
        "        versions.append('')\n"
        "print(json.dumps(versions))\n"
    )
    try:
        result = subprocess.run(
            [subprocess_path(python_executable), "-c", script, *packages],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        versions: object = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise RuntimeError(
            "Failed to inspect Substitute runtime Torch package metadata."
        ) from error
    if (
        not isinstance(versions, list)
        or len(versions) != len(packages)
        or not all(isinstance(version, str) for version in versions)
    ):
        raise RuntimeError(
            "Substitute runtime returned invalid Torch package metadata."
        )
    return tuple(str(version) for version in versions)
