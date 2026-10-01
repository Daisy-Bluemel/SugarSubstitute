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

"""Test workspace file action ownership boundaries."""

from __future__ import annotations

from pathlib import Path


def test_workspace_file_actions_do_not_register_output_images_directly() -> None:
    """File actions must delegate Output materialization to the registrar port."""

    source = Path("substitute/presentation/shell/workspace_file_actions.py").read_text(
        encoding="utf-8"
    )

    assert "output_canvas_state_service" not in source
    assert ".register_output_image(" not in source


def test_explicit_save_behavior_has_one_extracted_owner() -> None:
    """Keep Save forwarding and graph-format decisions out of load/export flows."""

    root = Path("substitute/presentation/shell")
    for filename in ("workspace_file_actions.py", "workspace_file_actions.pyi"):
        source = (root / filename).read_text(encoding="utf-8")
        assert "def on_save_clicked(" not in source
        assert "def on_save_as_clicked(" not in source
    source = (root / "workflow_recipe_save_actions.py").read_text(encoding="utf-8")
    assert "workspace_file_actions" not in source
    assert "QMessageBox" not in source
    assert ".exec(" not in source
