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

"""Publish explicit recipes only after every live Input mask is prepared."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Protocol

from substitute.application.recipes.recipe_io_service import RecipeIoService
from substitute.domain.common import GlobalOverrideScope
from substitute.domain.workflow import WorkflowState


class RecipeInputPreparationPort(Protocol):
    """Prepare durable input products while retaining a failed attempt's cleanup."""

    def prepare(
        self, *, workflow_id: str, workflow: WorkflowState, destination: Path
    ) -> AbstractContextManager[WorkflowState]:
        """Yield a detached serializable workflow until recipe publication ends."""


class RecipeMaskProductStorePort(Protocol):
    """Allocate one exclusively owned immutable mask-product namespace."""

    def create(self, destination: Path) -> AbstractContextManager[Path]:
        """Retain the new namespace on success and remove only it on failure."""


class WorkflowRecipeSaveService:
    """Coordinate input preparation and the atomic recipe publication boundary."""

    def __init__(
        self,
        *,
        recipes: RecipeIoService,
        input_preparation: Callable[[], RecipeInputPreparationPort],
    ) -> None:
        """Bind persistence and lazily resolved UI-owned capture preparation."""

        self._recipes = recipes
        self._input_preparation = input_preparation

    def save(
        self,
        *,
        destination: Path,
        workflow_id: str,
        workflow_name: str,
        workflow: WorkflowState,
        global_override_scopes: Mapping[str, GlobalOverrideScope] | None = None,
    ) -> None:
        """Publish once while keeping every previous recipe and product untouched."""

        preparation = (
            self._input_preparation().prepare(
                workflow_id=workflow_id, workflow=workflow, destination=destination
            )
            if workflow.canvas.mask_ids()
            else nullcontext(workflow)
        )
        with preparation as prepared:
            self._recipes.save_workflow_recipe(
                destination,
                workflow_name=workflow_name,
                workflow=prepared,
                global_override_scopes=global_override_scopes,
            )


__all__ = [
    "RecipeInputPreparationPort",
    "RecipeMaskProductStorePort",
    "WorkflowRecipeSaveService",
]
