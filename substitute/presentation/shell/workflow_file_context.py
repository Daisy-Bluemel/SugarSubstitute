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

"""Resolve shared workflow-file roots, override scope and explicit-save acknowledgement."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, cast

from substitute.application.workflows.unsaved_work_service import UnsavedWorkService
from substitute.domain.common import GlobalOverrideScope
from substitute.shared.logging.logger import get_logger, log_info

_LOGGER = get_logger("presentation.shell.workflow_file_context")


class _PathBundle(Protocol):
    """Expose the shell's authoritative file roots."""

    projects_dir: Path
    sugar_scripts_dir: Path


class WorkflowFileContext:
    """Share existing file-action context policy without retaining document state."""

    def __init__(self, view: object) -> None:
        """Store the shell surface supplying current roots and workflow owners."""

        self._view = view

    def projects_dir(self, projects_dir: Path | None) -> Path:
        """Resolve the project root from explicit input or the shell path bundle."""

        if projects_dir is not None:
            return Path(projects_dir)
        bundle = cast(_PathBundle | None, getattr(self._view, "path_bundle", None))
        return Path(bundle.projects_dir) if bundle is not None else Path(".")

    def sugar_scripts_dir(self, sugar_scripts_dir: Path | None) -> Path:
        """Resolve the script root from explicit input or the shell path bundle."""

        if sugar_scripts_dir is not None:
            return Path(sugar_scripts_dir)
        bundle = cast(_PathBundle | None, getattr(self._view, "path_bundle", None))
        return Path(bundle.sugar_scripts_dir) if bundle is not None else Path(".")

    def global_override_scopes(self) -> Mapping[str, GlobalOverrideScope] | None:
        """Read current serialization scope while preserving legacy host behavior."""

        manager = getattr(self._view, "active_override_manager", None)
        if manager is None:
            log_info(
                _LOGGER,
                "Workspace file action using legacy global override scope",
                reason="missing_active_override_manager",
            )
            return None
        getter = getattr(manager, "current_serialization_scopes", None)
        if not callable(getter):
            log_info(
                _LOGGER,
                "Workspace file action using legacy global override scope",
                reason="missing_scope_getter",
            )
            return None
        return cast(Mapping[str, GlobalOverrideScope], getter())

    def recipe_source_path(self, workflow_id: str) -> Path | None:
        """Read the document owner's current Sugar Script save target."""

        service = cast(
            UnsavedWorkService | None,
            getattr(self._view, "unsaved_work_service", None),
        )
        source = service.state_for(workflow_id).source_path if service else None
        if source is None or source.suffix.lower() != ".sugar":
            return None
        return source

    def mark_saved(self, workflow_id: str, source_path: Path) -> None:
        """Delegate successful save/load acknowledgement to the document-state owner."""

        service = getattr(self._view, "unsaved_work_service", None)
        mark_saved = getattr(service, "mark_saved", None)
        if callable(mark_saved):
            cast(Callable[[str, Path], None], mark_saved)(workflow_id, source_path)
