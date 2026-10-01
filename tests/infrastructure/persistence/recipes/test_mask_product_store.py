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

"""Preserve immutable recipe products through failures and uncertain termination."""

from pathlib import Path

import pytest

from substitute.infrastructure.persistence.recipe_mask_product_store import (
    RecipeMaskProductStore,
)


def test_failed_attempt_removes_only_its_exclusive_directory(tmp_path: Path) -> None:
    """Failure must retain products referenced by any earlier recipe or backup."""

    store = RecipeMaskProductStore()
    destination = tmp_path / "recipe.sugar"
    with store.create(destination) as committed:
        earlier = committed / "mask.png"
        earlier.write_bytes(b"earlier pixels")
    with pytest.raises(OSError):
        with store.create(destination) as failed:
            (failed / "mask.png").write_bytes(b"new pixels")
            raise OSError("Publication failed")
    assert earlier.read_bytes() == b"earlier pixels"
    assert not failed.exists()
    assert committed != failed


@pytest.mark.parametrize("interruption", (KeyboardInterrupt, SystemExit))
def test_uncertain_interruption_retains_possibly_committed_products(
    tmp_path: Path, interruption: type[BaseException]
) -> None:
    """Process-level interruption cannot prove the atomic recipe commit failed."""

    with pytest.raises(interruption):
        with RecipeMaskProductStore().create(tmp_path / "recipe.sugar") as attempt:
            product = attempt / "mask.png"
            product.write_bytes(b"possibly referenced pixels")
            raise interruption()
    assert product.read_bytes() == b"possibly referenced pixels"


@pytest.mark.platforms("linux", "macos")
def test_companion_symlink_outside_recipe_parent_is_rejected(tmp_path: Path) -> None:
    """POSIX companion symlinks must not redirect product writes outside the save."""

    selected = tmp_path / "selected"
    outside = tmp_path / "outside"
    selected.mkdir()
    outside.mkdir()
    (selected / "masks").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        with RecipeMaskProductStore().create(selected / "recipe.sugar"):
            raise AssertionError("Unsafe namespace must not be allocated")
    assert tuple(outside.iterdir()) == ()
