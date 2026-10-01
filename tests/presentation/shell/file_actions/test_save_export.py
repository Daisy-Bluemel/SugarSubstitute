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

"""Test recipe save and export destination policy."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any


from tests.presentation.shell.file_actions.support import (
    _import_module,
    _append,
    _append_then,
    _noop_output_registrar,
    _TabItem,
)


def test_on_export_clicked_validates_destination_via_export_service(
    tmp_path: Path,
) -> None:
    """Export should delegate default-path and destination validation to the export service."""

    mod = _import_module()
    destination = tmp_path / "Recipe.json"
    validated_paths: list[Path] = []
    export_calls: list[dict[str, object]] = []
    file_dialog = SimpleNamespace(
        getSaveFileName=lambda *_args, **_kwargs: (str(destination), "ComfyUI Workflow")
    )
    view = SimpleNamespace(
        workflow_tabbar=SimpleNamespace(
            currentIndex=lambda: 0,
            tabItem=lambda _index: _TabItem("wf-1", "Recipe"),
        ),
        recipe_io_service=SimpleNamespace(
            serialize_workflow_to_sugar_script=lambda workflow, *, global_override_scopes=None: (
                "# sugar"
            )
        ),
        workflow_export_service=SimpleNamespace(
            build_default_export_path=lambda workflow_name, output_dir: (
                output_dir / f"{workflow_name}.json"
            ).resolve(),
            validate_export_destination=lambda path: _append_then(
                validated_paths,
                path,
                path,
            ),
            export_workflow_json=lambda **kwargs: _append(export_calls, kwargs),
        ),
        get_active_workflow=lambda: {"nodes": {}},
        path_bundle=SimpleNamespace(
            projects_dir=tmp_path,
            sugar_scripts_dir=tmp_path / "sugarscripts",
            cubes_dir=tmp_path / "cubes",
        ),
    )
    actions = mod.WorkspaceFileActions(
        view,
        add_workflow_tab_requested=lambda: None,
        build_cube_load_ui_callbacks=lambda **_kwargs: "callbacks",
        output_image_registrar=_noop_output_registrar(),
    )

    actions.on_export_comfy_workflow_clicked(
        output_dir=tmp_path,
        file_dialog=file_dialog,
        message_box=SimpleNamespace(critical=lambda *_args, **_kwargs: None),
    )

    assert validated_paths == [destination.resolve()]
    assert export_calls == [
        {
            "destination_path": destination.resolve(),
            "sugar_script_text": "# sugar",
            "output_dir": tmp_path,
            "workflow": {"nodes": {}},
            "global_override_scopes": None,
        }
    ]


def test_on_export_clicked_reports_failure_through_error_presenter(
    tmp_path: Path,
) -> None:
    """Export failures should use the unified error modal presenter when available."""

    mod = _import_module()
    destination = tmp_path / "Recipe.json"
    presented: list[dict[str, Any]] = []
    critical_calls: list[object] = []
    failure = RuntimeError("cannot export")
    view = SimpleNamespace(
        workflow_tabbar=SimpleNamespace(
            currentIndex=lambda: 0,
            tabItem=lambda _index: _TabItem("wf-1", "Recipe"),
        ),
        workflow_session_service=SimpleNamespace(active_workflow_id="wf-1"),
        recipe_io_service=SimpleNamespace(
            serialize_workflow_to_sugar_script=lambda workflow, *, global_override_scopes=None: (
                "# sugar"
            )
        ),
        workflow_export_service=SimpleNamespace(
            build_default_export_path=lambda workflow_name, output_dir: (
                output_dir / f"{workflow_name}.json"
            ).resolve(),
            validate_export_destination=lambda path: path,
            export_workflow_json=lambda **_kwargs: (_ for _ in ()).throw(failure),
        ),
        get_active_workflow=lambda: {"nodes": {}},
        path_bundle=SimpleNamespace(
            projects_dir=tmp_path, sugar_scripts_dir=tmp_path / "sugarscripts"
        ),
    )
    actions = mod.WorkspaceFileActions(
        view,
        add_workflow_tab_requested=lambda: None,
        build_cube_load_ui_callbacks=lambda **_kwargs: "callbacks",
        output_image_registrar=_noop_output_registrar(),
        error_presenter=SimpleNamespace(
            show_exception_report=lambda **kwargs: _append(presented, kwargs)
        ),
    )

    actions.on_export_comfy_workflow_clicked(
        output_dir=tmp_path,
        file_dialog=SimpleNamespace(
            getSaveFileName=lambda *_args, **_kwargs: (
                str(destination),
                "ComfyUI Workflow",
            )
        ),
        message_box=SimpleNamespace(
            critical=lambda *args, **_kwargs: _append(critical_calls, args)
        ),
    )

    assert critical_calls == []
    assert presented[0]["title"] == "Export workflow failed"
    assert presented[0]["stage"] == "export"
    assert presented[0]["error"] is failure
    context = presented[0]["context"]
    assert context.operation == "export_workflow_json"
    assert context.workflow_id == "wf-1"
    assert context.workflow_name == "Recipe"
    assert context.path == str(destination.resolve())
