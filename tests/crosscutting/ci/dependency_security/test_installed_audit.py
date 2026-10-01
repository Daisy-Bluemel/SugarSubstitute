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

"""Keep unpublished-source identity checks separate from strict registry auditing."""

from __future__ import annotations

from collections.abc import Sequence
from importlib.metadata import Distribution, PathDistribution
import json
from pathlib import Path
import subprocess

import pytest

from tools.ci.audit_installed_dependencies import InstalledDependencyAudit, main

_ARCHIVE = (
    "https://github.com/Daisy-Bluemel/CuteMica/archive/"
    "831ec759d867ddd566bf2ec44154d4577ea8b8ee.tar.gz"
)
_DIGEST = "d11cbb7a4c42d0a1078daf7ce374c4a242986603dbd8cce4d74b516aeb0e1d2b"


def _source_json(
    *,
    url: str = _ARCHIVE,
    digest: str = _DIGEST,
    legacy_hash: str = "sha256=" + _DIGEST,
    extra: dict[str, object] | None = None,
) -> str:
    """Represent the installed archive identity without importing vendor code."""

    return json.dumps(
        {
            "url": url,
            "archive_info": {"hash": legacy_hash, "hashes": {"sha256": digest}},
            **(extra or {}),
        }
    )


def test_verified_cutemica_only_is_omitted_from_registry_inventory(
    tmp_path: Path,
) -> None:
    """Retain every other installed dependency, including unknown source packages."""

    distribution = _distribution(tmp_path, direct_url=_source_json())
    owner = InstalledDependencyAudit(lambda name: distribution)

    requirements = owner.requirements(
        [
            {"name": "CuteMica", "version": "0.1.0"},
            {"name": "Pillow", "version": "12.3.0"},
            {"name": "unpublished-other", "version": "1.0"},
        ]
    )

    assert set(requirements.splitlines()) == {
        "Pillow==12.3.0",
        "unpublished-other==1.0",
    }


@pytest.mark.parametrize(
    "direct_url",
    (
        None,
        "not json",
        "[]",
        "{}",
        _source_json(url="https://example.com/CuteMica.tar.gz"),
        _source_json(digest="0" * 64),
        _source_json(legacy_hash="sha256=" + "0" * 64),
        _source_json(extra={"dir_info": {"editable": True}}),
        _source_json(extra={"vcs_info": {"commit_id": "unknown"}}),
    ),
)
def test_unverified_cutemica_source_fails_closed(
    tmp_path: Path, direct_url: str | None
) -> None:
    """Reject missing, malformed, changed, editable, and VCS provenance."""

    distribution = _distribution(tmp_path, direct_url=direct_url)
    owner = InstalledDependencyAudit(lambda name: distribution)

    with pytest.raises(ValueError, match="CuteMica"):
        owner.requirements([{"name": "CuteMica", "version": "0.1.0"}])


@pytest.mark.parametrize(
    ("inventory_version", "metadata_name", "metadata_version"),
    (
        ("0.2.0", "CuteMica", "0.2.0"),
        ("0.1.0", "Other", "0.1.0"),
        ("0.1.0", "CuteMica", "0.2.0"),
    ),
)
def test_cutemica_identity_mismatch_fails_closed(
    tmp_path: Path,
    inventory_version: str,
    metadata_name: str,
    metadata_version: str,
) -> None:
    """Do not extend the single reviewed name and version exemption."""

    distribution = _distribution(
        tmp_path,
        direct_url=_source_json(),
        name=metadata_name,
        version=metadata_version,
    )
    owner = InstalledDependencyAudit(lambda name: distribution)

    with pytest.raises(ValueError, match="CuteMica"):
        owner.requirements([{"name": "CuteMica", "version": inventory_version}])


@pytest.mark.parametrize(
    "inventory",
    (
        {},
        [],
        ["Pillow"],
        [{"name": "Pillow"}],
        [{"name": "Pillow\nOther", "version": "12.3.0"}],
        [{"name": "Pillow", "version": "12.3.0; python_version > '3'"}],
        [
            {"name": "Pillow", "version": "12.3.0"},
            {"name": "pillow", "version": "12.3.0"},
        ],
    ),
)
def test_invalid_inventory_cannot_silently_drop_dependencies(inventory: object) -> None:
    """Reject incomplete, duplicated, and requirement-injection inventory records."""

    with pytest.raises(ValueError):
        InstalledDependencyAudit().requirements(inventory)


@pytest.mark.parametrize("audit_result", (0, 1))
def test_cli_retains_strict_audit_flags_and_failure_status(
    monkeypatch: pytest.MonkeyPatch, audit_result: int
) -> None:
    """Delegate all registry findings and collection failures to strict pip-audit."""

    audited: list[str] = []

    def run(
        command: Sequence[str],
        *,
        check: bool,
        text: bool,
        timeout: float,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Supply installed inventory and inspect the real audit invocation."""

        assert not check
        assert text
        assert 0 < timeout <= 600
        if "pip" in command:
            assert list(command[2:]) == ["pip", "list", "--local", "--format=json"]
            assert capture_output
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"name": "Pillow", "version": "12.3.0"}]), ""
            )
        assert "pip_audit" in command
        assert {"--strict", "--no-deps", "--disable-pip"} <= set(command)
        assert command[command.index("--ignore-vuln") + 1] == "CVE-2026-24049"
        requirements = Path(command[command.index("-r") + 1])
        audited.extend(requirements.read_text(encoding="utf-8").splitlines())
        return subprocess.CompletedProcess(command, audit_result)

    monkeypatch.setattr(subprocess, "run", run)

    assert main(["--ignore-vuln", "CVE-2026-24049"]) == audit_result
    assert audited == ["Pillow==12.3.0"]


def _distribution(
    tmp_path: Path,
    *,
    direct_url: str | None,
    name: str = "CuteMica",
    version: str = "0.1.0",
) -> Distribution:
    """Create real installed-distribution metadata at the filesystem boundary."""

    metadata = tmp_path / "cutemica-0.1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.5\nName: {name}\nVersion: {version}\n", encoding="utf-8"
    )
    if direct_url is not None:
        (metadata / "direct_url.json").write_text(direct_url, encoding="utf-8")
    return PathDistribution(metadata)
