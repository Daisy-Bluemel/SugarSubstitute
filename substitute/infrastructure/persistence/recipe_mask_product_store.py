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

"""Own immutable companion mask directories for explicit recipe saves."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import shutil
from uuid import uuid4

from substitute.shared.logging.logger import get_logger, log_exception
from substitute.shared.util.path_safety import ensure_within_root

_LOGGER = get_logger("infrastructure.persistence.recipe_mask_product_store")


class RecipeMaskProductStore:
    """Retain successful products and clean only a failed save's new directory."""

    @contextmanager
    def create(self, destination: Path) -> Iterator[Path]:
        """Allocate a collision-safe namespace contained by the recipe parent."""

        parent = destination.parent.resolve()
        product_root = ensure_within_root(
            parent / "masks" / ".saved",
            root_path=parent,
            subject="Recipe mask products",
        )
        product_root.mkdir(parents=True, exist_ok=True)
        attempt = ensure_within_root(
            product_root / uuid4().hex,
            root_path=parent,
            subject="Recipe mask save attempt",
        )
        attempt.mkdir(exist_ok=False)
        try:
            yield attempt
        except Exception:
            try:
                shutil.rmtree(attempt)
            except OSError:
                log_exception(
                    _LOGGER,
                    "Could not remove unpublished recipe mask products",
                    destination_path=str(destination),
                    attempt_path=str(attempt),
                )
            raise


__all__ = ["RecipeMaskProductStore"]
