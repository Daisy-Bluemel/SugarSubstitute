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

"""Restore startup-only editable authority before workspace media fallback."""

from __future__ import annotations

from typing import Any

from cutecanvas import PreparedDocumentRestore


def restore_initial_editable_document(shell: Any) -> None:
    """Use the one-shot lifecycle and any prepared archive on both startup paths.

    Keep this outside reusable workspace materialization: opening or importing a
    recipe in a running session must never replay the previous session archive.
    """
    lifecycle = getattr(shell, "input_editable_document_lifecycle", None)
    restore = getattr(lifecycle, "restore_before_workspace_assets", None)
    if not callable(restore):
        return
    preload = getattr(shell, "_restore_asset_preload", None)
    prepared_getter = getattr(preload, "prepared_editable_document", None)
    prepared = prepared_getter() if callable(prepared_getter) else None
    restore(prepared if isinstance(prepared, PreparedDocumentRestore) else None)


__all__ = ["restore_initial_editable_document"]
