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

"""Strictly audit installed registry packages and verify one unpublished source pin."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from importlib import metadata
import json
import logging
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

from packaging.utils import canonicalize_name
from packaging.version import Version

_LOGGER = logging.getLogger(__name__)
_CUTEMICA_ARCHIVE = (
    "https://github.com/Artificial-Sweetener/CuteMica/archive/"
    "5cbf43d201526e004f28f86785714c56f37067bc.tar.gz"
)
_CUTEMICA_SHA256 = "46f6e27b8dd9df7969d279778ab66e4595432b4394c42e097e9ae58d9e21d617"


class InstalledDependencyAudit:
    """Own the sole reviewed source exception when preparing registry audit input."""

    def __init__(
        self,
        distribution: Callable[[str], metadata.Distribution] = metadata.distribution,
    ) -> None:
        """Read installed metadata independently of the pip inventory boundary."""

        self._distribution = distribution

    def requirements(self, inventory: object) -> str:
        """Retain every installed package except the verified CuteMica source pin."""

        if not isinstance(inventory, list) or not inventory:
            raise ValueError("Installed dependency inventory must be a nonempty list.")
        requirements: list[str] = []
        seen: set[str] = set()
        for record in inventory:
            if not isinstance(record, dict):
                raise ValueError(
                    "Installed dependency inventory contains an invalid record."
                )
            name = record.get("name")
            version = record.get("version")
            if (
                not isinstance(name, str)
                or re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", name)
                is None
                or not isinstance(version, str)
            ):
                raise ValueError(
                    "Installed dependency name or version is missing or invalid."
                )
            Version(version)
            canonical_name = canonicalize_name(name)
            if canonical_name in seen:
                raise ValueError(f"Installed dependency inventory repeats {name}.")
            seen.add(canonical_name)
            if canonical_name == "cutemica":
                self._verify_cutemica(version)
            else:
                requirements.append(f"{name}=={version}")
        if not requirements:
            raise ValueError(
                "Installed dependency inventory contains no registry packages."
            )
        return "\n".join(requirements) + "\n"

    def _verify_cutemica(self, version: str) -> None:
        """Fail closed unless both inventory and provenance identify the reviewed archive."""

        distribution = self._distribution("CuteMica")
        if (
            version != "0.1.0"
            or distribution.metadata["Name"] != "CuteMica"
            or distribution.version != "0.1.0"
        ):
            raise ValueError(
                "CuteMica installed name or version differs from the reviewed pin."
            )
        direct_url = distribution.read_text("direct_url.json")
        if direct_url is None:
            raise ValueError("CuteMica installed source provenance is missing.")
        try:
            source: object = json.loads(direct_url)
        except json.JSONDecodeError as error:
            raise ValueError(
                "CuteMica installed source provenance is invalid JSON."
            ) from error
        if (
            not isinstance(source, dict)
            or source.get("url") != _CUTEMICA_ARCHIVE
            or "dir_info" in source
            or "vcs_info" in source
        ):
            raise ValueError("CuteMica installed source is not the reviewed archive.")
        archive = source.get("archive_info")
        if not isinstance(archive, dict):
            raise ValueError("CuteMica installed archive identity is missing.")
        hashes = archive.get("hashes")
        if (
            not isinstance(hashes, dict)
            or hashes.get("sha256") != _CUTEMICA_SHA256
            or archive.get("hash", f"sha256={_CUTEMICA_SHA256}")
            != f"sha256={_CUTEMICA_SHA256}"
        ):
            raise ValueError(
                "CuteMica installed archive digest differs from the reviewed pin."
            )
        _LOGGER.warning(
            "CuteMica 0.1.0 source identity verified at commit %s; no PyPI "
            "vulnerability-database coverage is available for this distribution.",
            "5cbf43d201526e004f28f86785714c56f37067bc",
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Audit the complete local environment while preserving upstream strict failures."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ignore-vuln", action="append", default=[])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    try:
        inventory = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--local", "--format=json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if inventory.returncode:
            _LOGGER.error(
                "Installed dependency enumeration failed: %s", inventory.stderr
            )
            return inventory.returncode
        requirements = InstalledDependencyAudit().requirements(
            json.loads(inventory.stdout)
        )
        with TemporaryDirectory(
            prefix="sugarsubstitute-dependency-audit-"
        ) as directory:
            path = Path(directory) / "installed-requirements.txt"
            path.write_text(requirements, encoding="utf-8")
            command = [
                sys.executable,
                "-m",
                "pip_audit",
                "-r",
                str(path),
                "--no-deps",
                "--disable-pip",
                "--strict",
                "--progress-spinner",
                "off",
                "--timeout",
                "15",
            ]
            for vulnerability in args.ignore_vuln:
                command.extend(("--ignore-vuln", vulnerability))
            result = subprocess.run(command, text=True, check=False, timeout=600)
            return result.returncode
    except (
        OSError,
        ValueError,
        metadata.PackageNotFoundError,
        subprocess.TimeoutExpired,
    ):
        _LOGGER.exception("Installed dependency audit failed before completion.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
