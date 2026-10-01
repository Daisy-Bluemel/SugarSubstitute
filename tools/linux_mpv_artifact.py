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

"""Qualify and atomically publish Linux libmpv ELF artifacts within owned roots."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
from typing import Protocol

_LOG = logging.getLogger(__name__)


class NativeCommand(Protocol):
    """Execute the caller's bounded native inspection tools."""

    def __call__(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        timeout: int,
        environment: dict[str, str] | None = None,
    ) -> str:
        """Return stdout or fail with the original subprocess diagnostic."""
        ...


class LinuxMpvArtifact:
    """Own installed ELF qualification and atomic artifact publication."""

    def __init__(
        self,
        readelf: Path,
        ldd: Path,
        run: NativeCommand,
        base_environment: dict[str, str],
    ) -> None:
        """Use explicit inspection tools with a clean runtime loader environment."""
        self.readelf = readelf
        self.ldd = ldd
        self._run = run
        self.base_environment = base_environment

    def qualify(self, artifact: Path, *, root: Path) -> dict[str, object]:
        """Check the exact installed ELF and standard host loader resolution."""
        if (
            not artifact.resolve().is_relative_to(root.resolve())
            or artifact.is_symlink()
            or not artifact.is_file()
            or not 64 <= artifact.stat().st_size <= 256 * 1024 * 1024
        ):
            raise RuntimeError(
                "Installed libmpv output is missing, unsafe, or oversized."
            )
        with artifact.open("rb") as binary:
            header = binary.read(64)
        if header[:7] != b"\x7fELF\x02\x01\x01" or struct.unpack_from(
            "<HH", header, 16
        ) != (3, 62):
            raise RuntimeError("Installed libmpv must be an x64 ELF shared library.")
        dynamic = self._run(
            [str(self.readelf.resolve()), "--dynamic", "--wide", str(artifact)],
            cwd=root,
            timeout=30,
        )
        if re.search(r"\((?:RPATH|RUNPATH)\)", dynamic):
            raise RuntimeError("Installed libmpv contains an RPATH/RUNPATH.")
        if re.findall(r"\(SONAME\).*?\[([^]]+)\]", dynamic) != ["libmpv.so.2"]:
            raise RuntimeError("Installed libmpv has the wrong ELF SONAME.")
        needed = sorted(re.findall(r"\(NEEDED\).*?\[([^]]+)\]", dynamic))
        if any("/" in name for name in needed):
            raise RuntimeError("Installed libmpv contains path-bound ELF dependencies.")
        for dependency in (
            "avcodec",
            "avfilter",
            "avformat",
            "avutil",
            "swresample",
            "swscale",
            "ass",
            "placebo",
            "pulse",
        ):
            if not any(name.startswith(f"lib{dependency}.so.") for name in needed):
                raise RuntimeError(
                    f"Installed libmpv is missing required {dependency} linkage."
                )
        symbols = self._run(
            [str(self.readelf.resolve()), "--dyn-syms", "--wide", str(artifact)],
            cwd=root,
            timeout=30,
        )
        exported = {
            parts[7]
            for line in symbols.splitlines()
            if len(parts := line.split()) >= 8
            and parts[6] != "UND"
            and parts[3] == "FUNC"
            and parts[4] in {"GLOBAL", "WEAK"}
            and parts[5] == "DEFAULT"
        }
        if (
            not {"mpv_create", "mpv_initialize", "mpv_render_context_create"}
            <= exported
        ):
            raise RuntimeError("Installed libmpv is missing its client/render API.")
        resolved = self._run(
            [str(self.ldd.resolve()), str(artifact)],
            cwd=root,
            timeout=30,
            environment=self.base_environment,
        )
        if (
            "not found" in resolved
            or "undefined symbol" in resolved
            or not resolved.strip()
        ):
            raise RuntimeError(
                "Installed libmpv dependencies do not resolve on this host."
            )
        return {
            "elf": {
                "class": 64,
                "machine": "x86_64",
                "soname": "libmpv.so.2",
                "needed": needed,
                "rpath": [],
                "runpath": [],
            },
            "qualification": {
                "host_dependencies_resolved": True,
                "portable_redistribution": False,
                "native_gpu_playback_tested": False,
                "playback_tested": False,
                "compiled_features": [
                    "ffmpeg",
                    "software-renderer",
                    "plain-gl",
                    "pulse",
                    "cplugins (production requires load-scripts=no)",
                ],
            },
        }

    def publish(
        self, artifact: Path, output_root: Path, provenance: dict[str, object]
    ) -> Path:
        """Publish digest-named provenance before atomically replacing the library."""
        output = output_root.resolve()
        destination = output / "linux-x64"
        if not destination.resolve().is_relative_to(output):
            raise RuntimeError("Runtime directory escapes the selected staging root.")
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".mpv-stage-", dir=destination) as name:
            temporary = Path(name)
            library = temporary / "libmpv.so.2"
            shutil.copyfile(artifact, library)
            if sha256(library) != provenance["sha256"]:
                raise RuntimeError(
                    "Runtime changed while staging; prior runtime was retained."
                )
            metadata = temporary / "provenance.json"
            metadata.write_text(
                json.dumps(provenance, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            for path in (library, metadata):
                path.chmod(0o644)
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
            metadata.replace(destination / f"libmpv.so.2.{provenance['sha256']}.json")
            library.replace(destination / "libmpv.so.2")
        _LOG.info("Staged Linux libmpv sha256=%s", provenance["sha256"])
        return destination / "libmpv.so.2"


def sha256(path: Path) -> str:
    """Hash a file without retaining its contents in memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
