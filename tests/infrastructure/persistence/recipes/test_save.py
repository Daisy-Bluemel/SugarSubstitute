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

"""Verify atomic recipe publication, recovery copies, and failure cleanup."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import shutil
from stat import S_IMODE

import pytest

from substitute.infrastructure.persistence import FileRecipeRepository
from sugarsubstitute_shared.windows_long_paths import operational_path


@pytest.mark.parametrize("existing", [False, True])
def test_failed_recipe_staging_preserves_destination_and_unrelated_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    """A partial write must leave the previous destination bytes recoverable in place."""

    target = tmp_path / "recipe.sugar"
    previous = b"# original\r\nuse Original\r\n"
    if existing:
        target.write_bytes(previous)
    unrelated = tmp_path / ".recipe.sugar.unrelated"
    unrelated.write_bytes(b"not owned by this save")
    write_text = Path.write_text

    def fail_write(
        path: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        """Model a storage failure after some replacement bytes were written."""

        write_text(path, data[:8], encoding=encoding, errors=errors, newline=newline)
        raise OSError("staging failed")

    monkeypatch.setattr(Path, "write_text", fail_write)
    with pytest.raises(OSError, match="staging failed"):
        FileRecipeRepository().save_recipe_document(
            target, project_name="Replacement", sugar_script_text="use Replacement"
        )

    assert target.exists() is existing
    if existing:
        assert target.read_bytes() == previous
    assert unrelated.read_bytes() == b"not owned by this save"
    assert set(tmp_path.iterdir()) == ({target, unrelated} if existing else {unrelated})


def test_failed_recipe_flush_preserves_previous_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after staging must not move or replace the previous recipe."""

    target = tmp_path / "recipe.sugar"
    previous = b"use Original"
    target.write_bytes(previous)

    def fail_flush(descriptor: int) -> None:
        """Reject the filesystem durability boundary after the temporary write."""

        del descriptor
        assert target.read_bytes() == previous
        raise OSError("flush failed")

    monkeypatch.setattr(os, "fsync", fail_flush)
    with pytest.raises(OSError, match="flush failed"):
        FileRecipeRepository().save_recipe_document(
            target, project_name="Replacement", sugar_script_text="use Replacement"
        )

    assert target.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [target]


def test_failed_recipe_backup_preserves_original_and_cleans_partial_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partially copied backup must never remove the live recipe or older backups."""

    target = tmp_path / "recipe.sugar"
    previous = b"use Original"
    target.write_bytes(previous)
    versions = tmp_path / "versions"
    versions.mkdir()
    older = versions / "recipe_older.sugar"
    older.write_bytes(b"older saved recipe")

    def fail_copy(source: Path, destination: Path) -> str:
        """Model an incomplete backup copy while the source remains readable."""

        assert source.read_bytes() == previous
        destination.write_bytes(b"incomplete backup")
        raise OSError("backup failed")

    monkeypatch.setattr(shutil, "copy2", fail_copy)
    with pytest.raises(OSError, match="backup failed"):
        FileRecipeRepository().save_recipe_document(
            target, project_name="Replacement", sugar_script_text="use Replacement"
        )

    assert target.read_bytes() == previous
    assert older.read_bytes() == b"older saved recipe"
    assert set(tmp_path.iterdir()) == {target, versions}
    assert list(versions.iterdir()) == [older]


@pytest.mark.parametrize("existing", [False, True])
def test_failed_recipe_publication_preserves_previous_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    """Failed replacement leaves the destination unchanged and cleans staging."""

    target = tmp_path / "recipe.sugar"
    previous = b"use Original"
    if existing:
        target.write_bytes(previous)

    def fail_replace(source: Path, destination: Path) -> None:
        """Reject final publication after the complete recipe has been staged."""

        assert destination == target
        assert source.read_text(encoding="utf-8") == "# Project: New\n\nuse New"
        assert target.exists() is existing
        if existing:
            assert target.read_bytes() == previous
        raise OSError("publication failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="publication failed"):
        FileRecipeRepository().save_recipe_document(
            target, project_name="New", sugar_script_text="use New"
        )

    assert target.exists() is existing
    if existing:
        assert target.read_bytes() == previous
        versions = tmp_path / "versions"
        assert set(tmp_path.iterdir()) == {target, versions}
        assert [path.read_bytes() for path in versions.iterdir()] == [previous]
    else:
        assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("previous", [b"use Original\r\n", b"\xff original bytes"])
def test_recipe_publication_keeps_exact_backups_and_avoids_name_collisions(
    tmp_path: Path, previous: bytes
) -> None:
    """Retain original bytes and permissions under collision-safe Sugar version names."""

    target = tmp_path / "recipe.txt"
    target.write_bytes(previous)
    target.chmod(0o600)
    original_mode = S_IMODE(target.stat().st_mode)
    timestamp = datetime.fromtimestamp(target.stat().st_ctime).strftime("%Y%m%d_%H%M%S")
    versions = tmp_path / "versions"
    versions.mkdir()
    older = versions / f"recipe_{timestamp}.sugar"
    older.write_bytes(b"existing version one")
    newer = versions / f"recipe_{timestamp}_2.sugar"
    newer.write_bytes(b"existing version two")
    expected = versions / f"recipe_{timestamp}_3.sugar"
    reference = tmp_path / "reference.sugar"
    reference.write_text("default permissions", encoding="utf-8")

    FileRecipeRepository().save_recipe_document(
        target, project_name="  New project  ", sugar_script_text="use New\n"
    )

    assert target.read_text(encoding="utf-8") == "# Project: New project\n\nuse New\n"
    assert expected.read_bytes() == previous
    assert S_IMODE(expected.stat().st_mode) == original_mode
    assert S_IMODE(target.stat().st_mode) == S_IMODE(reference.stat().st_mode)
    assert older.read_bytes() == b"existing version one"
    assert newer.read_bytes() == b"existing version two"
    assert set(versions.iterdir()) == {older, newer, expected}
    assert set(tmp_path.iterdir()) == {target, reference, versions}


def test_recipe_save_creates_nested_destination_without_backup(tmp_path: Path) -> None:
    """Publish a new headered recipe and remove all private staging paths."""

    target = tmp_path / "nested" / "recipe.sugar"

    FileRecipeRepository().save_recipe_document(
        target, project_name="  New  ", sugar_script_text="use Café\n"
    )

    assert target.read_text(encoding="utf-8") == "# Project: New\n\nuse Café\n"
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize("header", ["", "# Project: Same\n\n"])
def test_identical_recipe_save_does_not_touch_destination_or_create_version(
    tmp_path: Path, header: str
) -> None:
    """Preserve the original no-op contract and recognize generated project headers."""

    target = tmp_path / "recipe.sugar"
    target.write_text(f"{header}use Same\n", encoding="utf-8")
    os.utime(target, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    previous = target.read_bytes()
    modified_ns = target.stat().st_mtime_ns

    FileRecipeRepository().save_recipe_document(
        target, project_name=" Same ", sugar_script_text="use Same\n"
    )

    assert target.read_bytes() == previous
    assert target.stat().st_mtime_ns == modified_ns
    assert list(tmp_path.iterdir()) == [target]


def test_changed_project_name_creates_new_recipe_version(tmp_path: Path) -> None:
    """A changed project header remains an observable save even for the same script."""

    target = tmp_path / "recipe.sugar"
    target.write_text("# Project: Before\n\nuse Same", encoding="utf-8")
    previous = target.read_bytes()

    FileRecipeRepository().save_recipe_document(
        target, project_name="After", sugar_script_text="use Same"
    )

    assert target.read_text(encoding="utf-8") == "# Project: After\n\nuse Same"
    assert [path.read_bytes() for path in (tmp_path / "versions").iterdir()] == [
        previous
    ]


def test_recipe_save_accepts_long_valid_destination_basename(tmp_path: Path) -> None:
    """Keep temporary names within filesystem component limits independently of the target."""

    target = operational_path(tmp_path / f"{'r' * 240}.sugar")

    FileRecipeRepository().save_recipe_document(
        target, project_name="New", sugar_script_text="use New"
    )

    assert target.read_text(encoding="utf-8") == "# Project: New\n\nuse New"
    assert list(target.parent.iterdir()) == [target]


def test_successful_recipe_publication_reports_cleanup_failure_without_failing_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Report leftover staging after publication without falsely reporting a failed save."""

    target = tmp_path / "recipe.sugar"
    target.write_bytes(b"use Original")

    def fail_cleanup(*args: object, **kwargs: object) -> None:
        """Model an inaccessible temporary directory after the atomic commit."""

        del args, kwargs
        raise OSError("cleanup failed")

    with monkeypatch.context() as filesystem:
        filesystem.setattr(shutil, "rmtree", fail_cleanup)
        FileRecipeRepository().save_recipe_document(
            target, project_name="New", sugar_script_text="use New"
        )

    assert target.read_text(encoding="utf-8") == "# Project: New\n\nuse New"
    versions = tmp_path / "versions"
    assert [path.read_bytes() for path in versions.iterdir()] == [b"use Original"]
    assert "Saved recipe but failed to clean staging directory" in caplog.text
    assert "cleanup failed" in caplog.text
    remaining = set(tmp_path.iterdir()) - {target, versions}
    assert len(remaining) == 1
    for directory in remaining:
        assert list(directory.iterdir()) == []
        directory.rmdir()
