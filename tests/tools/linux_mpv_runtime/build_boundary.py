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

"""Provide a deterministic native subprocess boundary for real recipe execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import struct
import subprocess

from tools.prepare_linux_mpv_runtime import BuildConfiguration, MPV_COMMIT, MPV_TREE


@dataclass
class NativeBuildBoundary:
    """Simulate external native tools while preserving real files and orchestration."""

    config: BuildConfiguration
    failure: str = ""
    dirty: str = ""
    index: str = "H meson.build"
    commit: str = MPV_COMMIT
    artifact_mode: str = "valid"
    dynamic_extra: str = ""
    unresolved: bool = False
    missing_symbol: bool = False
    missing_feature: bool = False
    soname: str = "libmpv.so.2"
    missing_dependency: bool = False
    loader_stderr: bool = False
    changed_source: bool = False
    changed_inputs: bool = False
    calls: list[tuple[list[str], int, dict[str, str]]] = field(default_factory=list)

    def __call__(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        """Return controlled native output and install into the requested DESTDIR."""
        assert capture_output and text and check
        assert 0 < timeout <= 1800
        self.calls.append((arguments, timeout, env.copy()))
        output = ""
        error = ""
        if "rev-parse" in arguments:
            output = f"{self.config.source.resolve()}\n{self.commit}\n{MPV_TREE}\n"
        elif "status" in arguments:
            output = self.dirty
        elif "ls-files" in arguments:
            output = self.index
        elif "--version" in arguments:
            output = "test-tool 1.0\n"
        elif "setup" in arguments:
            self._fail("configure", arguments)
            build = Path(arguments[arguments.index("setup") + 1])
            build.mkdir()
            header = [
                f"#define HAVE_{name} 1"
                for name in ("FFMPEG", "GL", "PULSE", "CPLUGINS")
            ]
            header += ["#define HAVE_LUA 0", "#define HAVE_JAVASCRIPT 0"]
            if self.missing_feature:
                header.remove("#define HAVE_CPLUGINS 1")
            (build / "config.h").write_text("\n".join(header))
        elif arguments[0] == str(self.config.ninja.resolve()):
            self._fail("compile", arguments)
        elif "install" in arguments:
            self._fail("install", arguments)
            destination = Path(arguments[arguments.index("--destdir") + 1])
            artifact = destination / "usr/lib/libmpv.so.2.5.0"
            artifact.parent.mkdir(parents=True)
            if self.artifact_mode != "missing":
                artifact.write_bytes(elf_bytes(self.artifact_mode))
            if self.artifact_mode == "oversized":
                with artifact.open("r+b") as stream:
                    stream.truncate(256 * 1024 * 1024 + 1)
            if self.changed_source:
                self.dirty = " M meson.build\n"
            if self.changed_inputs:
                self.config.build_inputs.write_text('{"changed": true}')
        elif "--dynamic" in arguments:
            output = f" 0x SONAME (SONAME) Library soname: [{self.soname}]\n"
            output += "\n".join(
                f" 0x (NEEDED) Shared library: [lib{name}.so.1]"
                for name in (
                    "avcodec",
                    "avfilter",
                    "avformat",
                    "avutil",
                    "swresample",
                    "swscale",
                    "ass",
                    "placebo",
                    "pulse",
                )
            )
            output += self.dynamic_extra
            if self.missing_dependency:
                output = output.replace("libpulse.so.1", "libunrelated.so.1")
        elif "--dyn-syms" in arguments:
            names = ["mpv_create", "mpv_initialize", "mpv_render_context_create"]
            if self.missing_symbol:
                names.pop()
            output = "\n".join(
                f"1: 0 12 FUNC GLOBAL DEFAULT 1 {name}" for name in names
            )
        elif arguments[0] == str(self.config.ldd.resolve()):
            assert "LD_LIBRARY_PATH" not in env
            output = (
                "libmissing.so => not found"
                if self.unresolved
                else "libc.so.6 => /lib/libc.so.6 (0x0)"
            )
            if self.loader_stderr:
                error = "libavcodec.so.61: version 'REQUIRED' not found"
        else:
            raise AssertionError(f"Unexpected native command: {arguments}")
        return subprocess.CompletedProcess(arguments, 0, output, error)

    def _fail(self, stage: str, arguments: list[str]) -> None:
        """Inject a terminal tool failure at the selected real orchestration boundary."""
        if self.failure == stage:
            raise subprocess.CalledProcessError(1, arguments, output=f"{stage} failed")


def elf_bytes(mode: str = "valid") -> bytes:
    """Create a controlled ELF header rather than invoking a compiler in tests."""
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HH", header, 16, 3, 183 if mode == "arm64" else 62)
    if mode == "not-elf":
        header[:4] = b"nope"
    return bytes(header) + b"controlled native artifact"


def configuration(root: Path) -> BuildConfiguration:
    """Prepare explicit local inputs without any system installations or downloads."""
    source = root / "source"
    source.mkdir(parents=True)
    (source / "MPV_VERSION").write_text("0.41.0\n", encoding="utf-8")
    meson = root / "meson"
    (meson / "mesonbuild").mkdir(parents=True)
    (meson / "mesonbuild/__init__.py").touch()
    binaries = {}
    for name in ("ninja", "pkgconf", "cc", "readelf", "ldd"):
        binary = root / name
        binary.touch()
        binary.chmod(0o755)
        binaries[name] = binary
    inputs = root / "inputs.json"
    inputs.write_text('{"reviewed_packages": []}\n', encoding="utf-8")
    return BuildConfiguration(
        source=source,
        workspace=root / "work",
        output_root=root / "output",
        meson_python_path=meson,
        ninja=binaries["ninja"],
        pkg_config=binaries["pkgconf"],
        cc=binaries["cc"],
        readelf=binaries["readelf"],
        ldd=binaries["ldd"],
        build_inputs=inputs,
        environment={
            "PKG_CONFIG_LIBDIR": str(root / "pkgconfig"),
            "LD_LIBRARY_PATH": str(root / "build-libraries"),
        },
        pkg_config_arguments=("--dont-define-prefix",),
    )
