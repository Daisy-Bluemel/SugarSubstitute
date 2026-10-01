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

"""Prove source identity, offline build features, and atomic runtime publication."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import platform
import sys

import pytest

from tools import prepare_linux_mpv_runtime as recipe
from tests.tools.linux_mpv_runtime.build_boundary import (
    NativeBuildBoundary,
    configuration,
    elf_bytes,
)


@pytest.fixture
def boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> NativeBuildBoundary:
    """Keep the build boundary portable without actually configuring native code."""
    fake = NativeBuildBoundary(configuration(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


@pytest.mark.parametrize(
    ("platform_name", "machine"),
    (("win32", "AMD64"), ("darwin", "arm64"), ("linux", "aarch64")),
)
def test_rejects_unsupported_host_before_tools(
    boundary: NativeBuildBoundary,
    monkeypatch: pytest.MonkeyPatch,
    platform_name: str,
    machine: str,
) -> None:
    """Reject unsupported targets before executing even a source inspection tool."""
    monkeypatch.setattr(sys, "platform", platform_name)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    with pytest.raises(RuntimeError, match="Linux x64 only"):
        recipe.LinuxMpvBuild(boundary.config).prepare()
    assert boundary.calls == []


@pytest.mark.parametrize(
    "source_error", ("identity", "dirty", "ignored", "version", "hidden")
)
def test_rejects_unverified_source_before_build(
    boundary: NativeBuildBoundary, source_error: str
) -> None:
    """Keep altered commits, tracked/untracked files, and ignored overlays out of builds."""
    if source_error == "identity":
        boundary.commit = "0" * 40
    elif source_error == "dirty":
        boundary.dirty = " M meson.build\n?? overlay.c\n"
    elif source_error == "ignored":
        boundary.dirty = "!! local-overlay\n"
    elif source_error == "hidden":
        boundary.index = "h meson.build"
    else:
        (boundary.config.source / "MPV_VERSION").write_text("0.42.0")
    with pytest.raises(RuntimeError, match="pinned|Pinned|dirty"):
        recipe.LinuxMpvBuild(boundary.config).prepare()
    assert all(arguments[0] == "git" for arguments, _, _ in boundary.calls)
    assert not boundary.config.workspace.exists()
    assert not boundary.config.output_root.exists()


@pytest.mark.parametrize(
    "failure",
    (
        "configure",
        "compile",
        "install",
        "missing",
        "arm64",
        "not-elf",
        "oversized",
        "rpath",
        "runpath",
        "linkage",
        "exports",
        "features",
        "soname",
        "needed",
        "loader-stderr",
        "path-dependency",
    ),
)
def test_failures_preserve_existing_runtime(
    boundary: NativeBuildBoundary, failure: str
) -> None:
    """Never replace an existing runtime when a build or qualification step fails."""
    destination = boundary.config.output_root / "linux-x64/libmpv.so.2"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"prior qualified runtime")
    if failure in {"configure", "compile", "install"}:
        boundary.failure = failure
    elif failure in {"missing", "arm64", "not-elf", "oversized"}:
        boundary.artifact_mode = failure
    elif failure in {"rpath", "runpath"}:
        boundary.dynamic_extra = (
            f"\n0x ({failure.upper()}) Library rpath: [/private/build]"
        )
    elif failure == "linkage":
        boundary.unresolved = True
    elif failure == "features":
        boundary.missing_feature = True
    elif failure == "soname":
        boundary.soname = "libmpv.so.3"
    elif failure == "needed":
        boundary.missing_dependency = True
    elif failure == "loader-stderr":
        boundary.loader_stderr = True
    elif failure == "path-dependency":
        boundary.dynamic_extra = "\n0x (NEEDED) Shared library: [/build/libprivate.so]"
    else:
        boundary.missing_symbol = True
    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        recipe.LinuxMpvBuild(boundary.config).prepare()
    assert destination.read_bytes() == b"prior qualified runtime"
    assert list(destination.parent.iterdir()) == [destination]


def test_cli_consumes_explicit_offline_inputs(boundary: NativeBuildBoundary) -> None:
    """Exercise the public entrypoint with the same native-tool argv used by operators."""
    config = boundary.config
    environment = config.source.parent / "environment.json"
    environment.write_text(json.dumps(config.environment), encoding="utf-8")
    values = {
        "source": config.source,
        "workspace": config.workspace,
        "output-root": config.output_root,
        "meson-python-path": config.meson_python_path,
        "ninja": config.ninja,
        "pkg-config": config.pkg_config,
        "cc": config.cc,
        "readelf": config.readelf,
        "ldd": config.ldd,
        "build-inputs": config.build_inputs,
        "build-environment": environment,
    }
    arguments = [
        part for name, value in values.items() for part in (f"--{name}", str(value))
    ]
    arguments.append("--pkg-config-argument=--dont-define-prefix")
    assert recipe.main(arguments) == 0
    assert (config.output_root / "linux-x64/libmpv.so.2").read_bytes() == elf_bytes()


def test_success_builds_required_features_and_reproducible_provenance(
    boundary: NativeBuildBoundary,
) -> None:
    """Publish the installed ELF with offline inputs and honest repeatable provenance."""
    config = boundary.config
    existing = config.workspace / "unrelated-build.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("keep")
    builder = recipe.LinuxMpvBuild(config)
    result = builder.prepare()
    digest = hashlib.sha256(elf_bytes()).hexdigest()
    metadata = result.parent / f"libmpv.so.2.{digest}.json"
    first_provenance = metadata.read_bytes()
    document = json.loads(first_provenance)
    assert result.read_bytes() == elf_bytes()
    assert document["sha256"] == digest
    assert document["source"]["commit"] == recipe.MPV_COMMIT
    assert document["source"]["tree"] == recipe.MPV_TREE
    assert document["qualification"]["host_dependencies_resolved"] is True
    assert document["qualification"]["native_gpu_playback_tested"] is False
    assert document["qualification"]["portable_redistribution"] is False
    assert str(config.workspace).encode() not in first_provenance
    assert "LD_LIBRARY_PATH" not in document
    setup = next(
        arguments for arguments, _, _ in boundary.calls if "setup" in arguments
    )
    assert {
        "--wrap-mode=nofallback",
        "-Dauto_features=disabled",
        "-Dlibmpv=true",
        "-Ddefault_library=shared",
        "-Dgl=enabled",
        "-Dplain-gl=enabled",
        "-Dcplugins=enabled",
        "-Dlua=disabled",
        "-Djavascript=disabled",
        "-Dpulse=enabled",
        "-Dbuild-date=false",
        "-Dcplayer=false",
    } <= set(setup)
    native = Path(setup[setup.index("--native-file") + 1]).read_text()
    assert "pkg-config = [" in native
    assert config.pkg_config.name in native
    assert ", '--dont-define-prefix']" in native
    compile_call = next(
        arguments
        for arguments, _, _ in boundary.calls
        if arguments[0] == str(config.ninja) and "-C" in arguments
    )
    assert compile_call[-3:] == ["-j", "2", "libmpv.so.2.5.0"]
    builder.prepare()
    assert metadata.read_bytes() == first_provenance
    assert existing.read_text() == "keep"
    assert len(list(config.workspace.glob("mpv-linux-*"))) == 2
    assert not list(result.parent.glob(".mpv-stage-*"))


@pytest.mark.parametrize(
    "invalid", ("jobs", "environment", "nested-workspace", "meson")
)
def test_invalid_configuration_never_starts_tools(
    boundary: NativeBuildBoundary, invalid: str
) -> None:
    """Fail closed on uncontrolled tool environment and source-owned build roots."""
    config = boundary.config
    if invalid == "jobs":
        config = replace(config, jobs=0)
    elif invalid == "environment":
        config = replace(config, environment={"LD_PRELOAD": "/unexpected.so"})
    elif invalid == "nested-workspace":
        config = replace(config, workspace=config.source / "build")
    else:
        (config.meson_python_path / "mesonbuild/__init__.py").unlink()
    with pytest.raises(ValueError):
        recipe.LinuxMpvBuild(config).prepare()
    assert boundary.calls == []


@pytest.mark.parametrize("changed", ("source", "inputs"))
def test_input_changes_during_build_prevent_publication(
    boundary: NativeBuildBoundary, changed: str
) -> None:
    """Recheck source and reviewed metadata after compilation before publishing."""
    boundary.changed_source = changed == "source"
    boundary.changed_inputs = changed == "inputs"
    with pytest.raises(RuntimeError, match="dirty|metadata changed"):
        recipe.LinuxMpvBuild(boundary.config).prepare()
    assert not boundary.config.output_root.exists()


def test_escaped_output_is_rejected_before_native_inspection(
    boundary: NativeBuildBoundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent an installed artifact resolving outside the owned run from staging."""
    original_resolve = Path.resolve

    def escaped_resolve(path: Path, strict: bool = False) -> Path:
        """Simulate an external filesystem resolving the artifact through a link."""
        if path.name == "libmpv.so.2.5.0":
            return boundary.config.source / "external.so"
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", escaped_resolve)
    with pytest.raises(RuntimeError, match="unsafe"):
        recipe.LinuxMpvBuild(boundary.config).prepare()
    assert not any("--dynamic" in arguments for arguments, _, _ in boundary.calls)
    assert not boundary.config.output_root.exists()


def test_corruption_while_copying_preserves_previous_runtime(
    boundary: NativeBuildBoundary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify staged bytes before atomically replacing the prior qualified artifact."""
    import shutil

    destination = boundary.config.output_root / "linux-x64/libmpv.so.2"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"prior runtime")

    def corrupt_copy(source: Path, target: Path) -> Path:
        """Inject a filesystem copy failure without changing qualification behavior."""
        target.write_bytes(b"corrupted in transit")
        return target

    monkeypatch.setattr(shutil, "copyfile", corrupt_copy)
    with pytest.raises(RuntimeError, match="changed while staging"):
        recipe.LinuxMpvBuild(boundary.config).prepare()
    assert destination.read_bytes() == b"prior runtime"
    assert list(destination.parent.iterdir()) == [destination]
