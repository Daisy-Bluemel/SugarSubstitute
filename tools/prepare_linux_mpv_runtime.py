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

"""Build pinned Linux x64 libmpv using caller-prepared, offline native inputs.

This tool installs only into a fresh workspace DESTDIR. It neither acquires
packages nor qualifies portable redistribution or native GPU playback. Keep the
public dependency/license inventory in third_party; --build-inputs identifies
that reviewed inventory by digest without copying environment values into it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.linux_mpv_artifact import LinuxMpvArtifact, sha256

MPV_COMMIT = "41f6a645068483470267271e1d09966ca3b9f413"
MPV_TREE = "d0cc1c088a9c72f52d6c232438215c50ceeb11a3"
MPV_VERSION = "0.41.0"
BUILD_OPTIONS = (
    "--buildtype=release",
    "--wrap-mode=nofallback",
    "--prefix=/usr",
    "--libdir=lib",
    "-Dauto_features=disabled",
    "-Ddefault_library=shared",
    "-Dlibmpv=true",
    "-Dcplayer=false",
    "-Dgpl=true",
    "-Dgl=enabled",
    "-Dplain-gl=enabled",
    "-Dcplugins=enabled",
    "-Dlua=disabled",
    "-Djavascript=disabled",
    "-Dpulse=enabled",
    "-Dbuild-date=false",
    "-Dmanpage-build=disabled",
)
_ENVIRONMENT_KEYS = frozenset(
    {
        "PKG_CONFIG_LIBDIR",
        "PKG_CONFIG_PATH",
        "PKG_CONFIG_SYSROOT_DIR",
        "CPPFLAGS",
        "CFLAGS",
        "LDFLAGS",
        "LD_LIBRARY_PATH",
    }
)
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuildConfiguration:
    """Name the already prepared native tools and their bounded execution scope."""

    source: Path
    workspace: Path
    output_root: Path
    meson_python_path: Path
    ninja: Path
    pkg_config: Path
    cc: Path
    readelf: Path
    ldd: Path
    build_inputs: Path
    environment: dict[str, str]
    pkg_config_arguments: tuple[str, ...] = ()
    jobs: int = 2


class LinuxMpvBuild:
    """Own verification, offline compilation, and failure-safe runtime promotion."""

    def __init__(self, configuration: BuildConfiguration) -> None:
        """Keep caller inputs separate from the minimal subprocess environment."""
        self.config = configuration
        self.base_environment = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"}
        self.environment = {
            **self.base_environment,
            **configuration.environment,
            "PYTHONPATH": str(configuration.meson_python_path.resolve()),
            "NINJA": str(configuration.ninja.resolve()),
        }

    def prepare(self) -> Path:
        """Publish only a completely built, installed, and machine-checked runtime."""
        self._validate_inputs()
        artifact_owner = LinuxMpvArtifact(
            self.config.readelf, self.config.ldd, self._run, self.base_environment
        )
        self._verify_source()
        versions = self._tool_versions()
        inputs_hash = sha256(self.config.build_inputs)
        workspace = self.config.workspace.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix="mpv-linux-", dir=workspace))
        build, installed = run / "build", run / "install"
        native = run / "native.ini"
        native.write_text(self._native_file(), encoding="utf-8")
        self._meson(
            [
                "setup",
                str(build),
                str(self.config.source.resolve()),
                "--native-file",
                str(native),
                *BUILD_OPTIONS,
            ],
            cwd=run,
            timeout=180,
        )
        self._verify_build_features(build)
        self._run(
            [
                str(self.config.ninja.resolve()),
                "-C",
                str(build),
                "-j",
                str(self.config.jobs),
                "libmpv.so.2.5.0",
            ],
            cwd=run,
            timeout=1800,
        )
        self._meson(
            [
                "install",
                "-C",
                str(build),
                "--no-rebuild",
                "--destdir",
                str(installed),
                "--tags",
                "runtime",
            ],
            cwd=run,
            timeout=120,
        )
        artifact = installed / "usr" / "lib" / "libmpv.so.2.5.0"
        artifact_evidence = artifact_owner.qualify(artifact, root=run)
        self._verify_source()
        if sha256(self.config.build_inputs) != inputs_hash:
            raise RuntimeError(
                "Reviewed build-input metadata changed during compilation."
            )
        provenance = {
            "schema_version": 1,
            "source": {
                "url": "https://github.com/mpv-player/mpv.git",
                "commit": MPV_COMMIT,
                "tree": MPV_TREE,
                "version": MPV_VERSION,
            },
            "build_options": list(BUILD_OPTIONS),
            "tools": versions,
            "build_inputs_sha256": inputs_hash,
            "native_configuration_sha256": sha256(native),
            "build_environment_sha256": hashlib.sha256(
                json.dumps(self.config.environment, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "sha256": sha256(artifact),
            **artifact_evidence,
        }
        return artifact_owner.publish(artifact, self.config.output_root, provenance)

    def _validate_inputs(self) -> None:
        """Reject unsupported hosts or ambiguous inputs before executing any tool."""
        if sys.platform != "linux" or platform.machine().lower() not in {
            "x86_64",
            "amd64",
        }:
            raise RuntimeError("This source recipe supports Linux x64 only.")
        if not 1 <= self.config.jobs <= 8:
            raise ValueError("Build jobs must be between 1 and 8.")
        if set(self.config.environment) - _ENVIRONMENT_KEYS:
            raise ValueError("Build environment contains an unsupported variable.")
        for path in (self.config.source, self.config.meson_python_path):
            if not path.is_dir():
                raise ValueError(f"Required input directory is missing: {path}")
        for path in (
            self.config.ninja,
            self.config.pkg_config,
            self.config.cc,
            self.config.readelf,
            self.config.ldd,
        ):
            if not path.is_file() or not os.access(path, os.X_OK):
                raise ValueError(f"Required executable is missing: {path}")
        if not (self.config.meson_python_path / "mesonbuild" / "__init__.py").is_file():
            raise ValueError("Meson module directory is incomplete.")
        if self.config.build_inputs.stat().st_size > 1024 * 1024:
            raise ValueError("Build-input metadata exceeds 1 MiB.")
        if not isinstance(json.loads(self.config.build_inputs.read_text()), dict):
            raise ValueError("Build-input metadata must be a JSON object.")
        source = self.config.source.resolve()
        for path in (self.config.workspace, self.config.output_root):
            if path.resolve().is_relative_to(source):
                raise ValueError(
                    "Build and staging roots must be outside the source checkout."
                )

    def _verify_source(self) -> None:
        """Require the exact clean checkout, including untracked and ignored files."""
        source = self.config.source.resolve()
        git = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]
        identity = self._run(
            [*git, "rev-parse", "--show-toplevel", "HEAD", "HEAD^{tree}"],
            cwd=source,
            timeout=30,
            environment=self.base_environment,
        )
        if identity.splitlines() != [str(source), MPV_COMMIT, MPV_TREE]:
            raise RuntimeError(
                "Source checkout does not match the pinned mpv commit/tree."
            )
        dirty = self._run(
            [*git, "status", "--porcelain", "--untracked-files=all", "--ignored"],
            cwd=source,
            timeout=30,
            environment=self.base_environment,
        )
        if dirty.strip() or (source / "MPV_VERSION").read_text().strip() != MPV_VERSION:
            raise RuntimeError(
                "Pinned mpv source checkout is dirty or has a different version."
            )
        index = self._run(
            [*git, "ls-files", "-v"],
            cwd=source,
            timeout=30,
            environment=self.base_environment,
        )
        if any(
            line[0].islower() or line.startswith("S ")
            for line in index.splitlines()
            if line
        ):
            raise RuntimeError(
                "Pinned source has hidden assume-unchanged or sparse index entries."
            )

    def _native_file(self) -> str:
        """Pass pkgconf flags as Meson argv rather than an executable shell string."""
        binaries = {
            "c": [str(self.config.cc.resolve())],
            "pkg-config": [
                str(self.config.pkg_config.resolve()),
                *self.config.pkg_config_arguments,
            ],
            "python3": [sys.executable],
        }
        lines = ["[binaries]"]
        for name, arguments in binaries.items():
            quoted = []
            for argument in arguments:
                if any(character in argument for character in "\r\n\0"):
                    raise ValueError(
                        "Native tool arguments must not contain control characters."
                    )
                quoted.append(
                    "'" + argument.replace("\\", "\\\\").replace("'", "\\'") + "'"
                )
            lines.append(f"{name} = [{', '.join(quoted)}]")
        return "\n".join(lines) + "\n"

    def _verify_build_features(self, build: Path) -> None:
        """Check Meson's generated production options before invoking the compiler."""
        header = build / "config.h"
        if (
            not header.resolve().is_relative_to(build.resolve())
            or header.stat().st_size > 65536
        ):
            raise RuntimeError("Generated mpv configuration is unsafe or oversized.")
        lines = set(header.read_text(encoding="utf-8").splitlines())
        features = {
            "FFMPEG": 1,
            "GL": 1,
            "PULSE": 1,
            "CPLUGINS": 1,
            "LUA": 0,
            "JAVASCRIPT": 0,
        }
        if any(
            f"#define HAVE_{name} {value}" not in lines
            for name, value in features.items()
        ):
            raise RuntimeError(
                "Generated mpv configuration lacks the required production features."
            )

    def _tool_versions(self) -> dict[str, str]:
        """Record version banners without storing absolute paths or environment values."""
        commands = {
            "meson": [sys.executable, "-m", "mesonbuild.mesonmain"],
            "ninja": [str(self.config.ninja.resolve())],
            "pkg_config": [
                str(self.config.pkg_config.resolve()),
                *self.config.pkg_config_arguments,
            ],
            "cc": [str(self.config.cc.resolve())],
            "readelf": [str(self.config.readelf.resolve())],
        }
        return {
            name: self._run(
                [*command, "--version"], cwd=self.config.source.resolve(), timeout=30
            ).splitlines()[0][:200]
            for name, command in commands.items()
        }

    def _meson(self, arguments: list[str], *, cwd: Path, timeout: int) -> str:
        """Use the selected Python module without requiring a global Meson install."""
        return self._run(
            [sys.executable, "-m", "mesonbuild.mesonmain", *arguments],
            cwd=cwd,
            timeout=timeout,
        )

    def _run(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        timeout: int,
        environment: dict[str, str] | None = None,
    ) -> str:
        """Execute bounded argv commands, retaining diagnostic output on failure."""
        _LOG.info("Running %s (timeout=%ss)", Path(arguments[0]).name, timeout)
        try:
            result = subprocess.run(
                arguments,
                cwd=cwd,
                env=environment or self.environment,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as error:
            details = str(error.stderr or error.stdout or "No tool diagnostic")[-4000:]
            raise RuntimeError(
                f"Native command failed: {Path(arguments[0]).name}: {details}"
            ) from error
        return "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )


def main(argv: list[str] | None = None) -> int:
    """Build from explicit local inputs; no downloads or system installation occur."""
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in (
        "source",
        "workspace",
        "meson-python-path",
        "ninja",
        "pkg-config",
        "cc",
        "readelf",
        "ldd",
        "build-inputs",
        "build-environment",
    ):
        parser.add_argument(f"--{argument}", type=Path, required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "third_party/bin/mpv",
    )
    parser.add_argument(
        "--pkg-config-argument",
        action="append",
        default=[],
        help="Repeat for pkgconf argv, e.g. --pkg-config-argument=--dont-define-prefix",
    )
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args(argv)
    if args.build_environment.stat().st_size > 65536:
        raise ValueError("Build environment exceeds 64 KiB.")
    environment: object = json.loads(args.build_environment.read_text(encoding="utf-8"))
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in environment.items()
    ):
        raise ValueError("Build environment must be a JSON object of string values.")
    configuration = BuildConfiguration(
        source=args.source,
        workspace=args.workspace,
        output_root=args.output_root,
        meson_python_path=args.meson_python_path,
        ninja=args.ninja,
        pkg_config=args.pkg_config,
        cc=args.cc,
        readelf=args.readelf,
        ldd=args.ldd,
        build_inputs=args.build_inputs,
        environment=environment,
        pkg_config_arguments=tuple(args.pkg_config_argument),
        jobs=args.jobs,
    )
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    LinuxMpvBuild(configuration).prepare()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
