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

"""Identify the exact workflow whose authored editor section changed."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from copy import deepcopy
import json
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from substitute.application.workflows.editor_projection_service import (
    WorkflowEditorProjectionService,
)
from substitute.application.workflows.unsaved_work_service import (
    UnsavedWorkDecision,
    UnsavedWorkService,
)
from substitute.domain.comfy_workflow import ComfyWorkflowConverter, DirectWorkflowState
from substitute.domain.workflow import CubeState, WorkflowState
from substitute.presentation.editor.panel.field_state_binding import EditorFieldBinding
from substitute.presentation.editor.panel.field_value_store import EditorFieldValueStore
from substitute.presentation.shell.editor_section_unsaved_work_observer import (
    EditorSectionUnsavedWorkObserver,
)
from substitute.presentation.shell.session_autosave_controller import (
    SessionAutosaveController,
)
from substitute.presentation.shell.unsaved_work_controller import UnsavedWorkController
from tests.presentation.shell.recipe_save.support import SaveView
from tests.support.passthrough_cube_analysis import PassthroughCubeWorkflowAnalyzer
from tests.support.canonical_cube_graph import graph_backed_cube_workflow_from_states
from tests.support.qt.lifecycle import destroy_qt_object, ensure_qt_application


class _Edits(QObject):
    """Provide a real Qt signal independently owned from its receiver."""

    changed = Signal(object)


@dataclass
class _Harness:
    """Retain the exact source, receiver, document service and observed saves."""

    parent: QObject
    edits: _Edits
    service: UnsavedWorkService
    observer: EditorSectionUnsavedWorkObserver
    saves: list[tuple[str, ...]]


@contextmanager
def _observe(
    workflows: dict[str, WorkflowState], *, muted: Callable[[], bool] = lambda: False
) -> Iterator[_Harness]:
    """Own and destroy the signal source and panel-lifetime receiver exactly."""
    ensure_qt_application()
    parent, edits = QObject(), _Edits()
    service = UnsavedWorkService()
    for workflow_id in workflows:
        service.mark_saved(workflow_id, Path(workflow_id + ".sugar"))
    saves: list[tuple[str, ...]] = []
    observer = EditorSectionUnsavedWorkObserver(
        parent=parent,
        edits=edits.changed,
        workflows=lambda: workflows,
        unsaved_work=service,
        edits_muted=muted,
        request_autosave=lambda: saves.append(
            service.dirty_workflow_ids(tuple(workflows))
        ),
    )
    try:
        yield _Harness(parent, edits, service, observer, saves)
    finally:
        if isValid(parent):
            destroy_qt_object(parent)
        destroy_qt_object(edits)


def _workflow(kind: str) -> WorkflowState:
    """Build real legacy, canonical Cube, and ordinary Comfy document owners."""
    cube = CubeState(
        cube_id="test/text.cube",
        version="1",
        alias="A",
        original_cube={},
        buffer={
            "nodes": {"1": {"class_type": "TextSource", "inputs": {"text": "initial"}}}
        },
    )
    if kind == "cube":
        return WorkflowState(cubes={"A": cube}, stack_order=["A"])
    if kind == "graph_cube":
        return graph_backed_cube_workflow_from_states(cube)
    graph: dict[str, object] = {
        "nodes": [
            {
                "id": 1,
                "type": "TextSource",
                "inputs": [
                    {
                        "name": "text",
                        "type": "STRING",
                        "widget": {"name": "text"},
                        "link": None,
                    }
                ],
                "outputs": [],
                "widgets_values": ["initial"],
            }
        ],
        "links": [],
    }
    direct = DirectWorkflowState(
        source_path=Path("source.json"),
        source_workflow=graph,
        buffer=ComfyWorkflowConverter().convert(graph),
    )
    return WorkflowState(direct_workflow=direct)


def _section(workflow: WorkflowState) -> object:
    """Use the same authoritative section projection as the real editor."""
    return next(
        iter(WorkflowEditorProjectionService().project(workflow).states.values())
    )


def _binding() -> EditorFieldBinding:
    """Identify the authored text field without assigning workflow authority."""
    return EditorFieldBinding(
        cube_alias="A",
        node_name="1",
        field_key="text",
        storage_kind="input",
        value_source=None,
        resolved_display_value=None,
        prompt_field_identity="1.text",
    )


@pytest.mark.parametrize("kind", ["cube", "direct", "graph_cube"])
def test_field_mutation_marks_only_exact_inactive_document_before_autosave(
    kind: str,
) -> None:
    """Same names and inactive tabs cannot redirect a real persisted field edit."""
    owner, active = _workflow(kind), _workflow(kind)
    workflows = {"active": active, "inactive": owner}
    with _observe(workflows) as harness:
        store = EditorFieldValueStore(section_edited=harness.edits.changed.emit)
        assert store.set_field_value(_section(owner), _binding(), "edited")
        assert harness.service.state_for("inactive").dirty
        assert harness.service.state_for("inactive").source_path == Path(
            "inactive.sugar"
        )
        assert not harness.service.state_for("active").dirty
        assert harness.saves == [("inactive",)]
        assert not store.set_field_value(_section(owner), _binding(), "edited")
        assert harness.saves == [("inactive",)]
        harness.service.mark_saved("inactive", Path("saved.sugar"))
        assert store.set_field_value(_section(owner), _binding(), "edited again")
        assert harness.saves == [("inactive",), ("inactive",)]


@pytest.mark.parametrize("kind", ["cube", "direct", "graph_cube"])
def test_equal_detached_or_replaced_sections_do_not_dirty_current_documents(
    kind: str,
) -> None:
    """Membership uses identity, including after the workflow projection changes."""
    old, replacement = _workflow(kind), _workflow(kind)
    workflows = {"owner": old}
    with _observe(workflows) as harness:
        harness.edits.changed.emit(_section(replacement))
        assert harness.saves == []
        workflows["owner"] = replacement
        harness.edits.changed.emit(_section(old))
        harness.edits.changed.emit(object())
        assert harness.saves == []
        assert not harness.service.state_for("owner").dirty
        harness.edits.changed.emit(_section(replacement))
        assert harness.saves == [("owner",)]


def test_shared_section_has_no_unique_document_owner() -> None:
    """Reject ambiguous ownership instead of defaulting to an active workflow."""
    shared = _workflow("cube")
    other = WorkflowState(cubes=shared.cubes.copy(), stack_order=["A"])
    with _observe({"one": shared, "two": other}) as harness:
        harness.edits.changed.emit(_section(shared))
        assert harness.saves == []
        assert harness.service.dirty_workflow_ids(("one", "two")) == ()


def test_duplicate_section_membership_in_one_workflow_is_one_owner() -> None:
    """Deduplicate by document identity without treating aliases as authority."""
    workflow = _workflow("cube")
    workflow.cubes["also A"] = workflow.cubes["A"]
    with _observe({"owner": workflow}) as harness:
        harness.edits.changed.emit(workflow.cubes["A"])
        assert harness.saves == [("owner",)]


class _LifecycleShell:
    """Expose the production restore lifecycle consumed by mute policy."""

    def __init__(self, lifecycle: str) -> None:
        """Retain the current shell lifecycle without changing document state."""
        self._shell_restore_lifecycle = lifecycle


@pytest.mark.parametrize(
    "lifecycle", ["constructing", "prehydrating", "restoring", "gui_reloading"]
)
def test_restore_muting_keeps_the_document_clean(lifecycle: str) -> None:
    """Restoration notifications cannot turn hydration into an authored edit."""
    workflow = _workflow("direct")
    controller = SessionAutosaveController(_LifecycleShell(lifecycle))
    with _observe(
        {"owner": workflow}, muted=controller.session_autosave_muted
    ) as harness:
        harness.edits.changed.emit(_section(workflow))
        assert not harness.service.state_for("owner").dirty
        assert harness.saves == []


def test_destroyed_panel_disconnects_the_document_observer() -> None:
    """Late source signals cannot invoke a receiver owned by a deleted panel."""
    workflow = _workflow("cube")
    with _observe({"owner": workflow}) as harness:
        destroy_qt_object(harness.parent)
        assert not isValid(harness.observer)
        harness.edits.changed.emit(_section(workflow))
        assert harness.saves == []
        assert not harness.service.state_for("owner").dirty


class _Decision:
    """Return a controlled user choice at the native close-dialog boundary."""

    def __init__(self, decision: UnsavedWorkDecision) -> None:
        """Keep the decision separate from actual save and close orchestration."""
        self.decision = decision

    def decide(self, *, parent: QWidget, workflow_name: str) -> UnsavedWorkDecision:
        """Observe the named document and return the selected response."""
        assert workflow_name == "Recipe"
        return self.decision


@pytest.mark.parametrize(
    "decision", [UnsavedWorkDecision.CANCEL, UnsavedWorkDecision.SAVE]
)
def test_cancel_or_unsupported_save_retains_real_edited_document(
    tmp_path: Path, decision: UnsavedWorkDecision
) -> None:
    """Field edits must reach the real close guard and survive refused persistence."""
    ensure_qt_application()
    workflow = _workflow("direct")
    direct = workflow.direct_workflow
    assert direct is not None
    direct.cube_analysis = PassthroughCubeWorkflowAnalyzer().analyze(
        direct.source_workflow
    )
    original = tmp_path / "original.json"
    original.write_text(json.dumps(direct.source_workflow))
    original_bytes = original.read_bytes()
    view = SaveView(tmp_path, workflow)
    view.unsaved_work_service.mark_saved("workflow", original)
    parent, edits = QObject(), _Edits()
    observer = EditorSectionUnsavedWorkObserver(
        parent=parent,
        edits=edits.changed,
        workflows=lambda: view.workflow_session_service.workflows,
        unsaved_work=view.unsaved_work_service,
        edits_muted=lambda: False,
        request_autosave=lambda: None,
    )
    try:
        assert observer.parent() is parent
        store = EditorFieldValueStore(section_edited=edits.changed.emit)
        assert store.set_field_value(direct, _binding(), "authored edit")
        edited = deepcopy(direct.source_workflow)
        assert view.unsaved_work_service.state_for("workflow").dirty
        controller = UnsavedWorkController(view, prompt=_Decision(decision))
        assert not controller.confirm_workflow_close("workflow")
        assert not controller.confirm_shutdown()
        assert direct.source_workflow == edited
        assert view.workflow_session_service.get_active_workflow() is workflow
        assert view.unsaved_work_service.state_for("workflow").dirty
        assert original.read_bytes() == original_bytes
        assert list(tmp_path.iterdir()) == [original]
        if decision is UnsavedWorkDecision.SAVE:
            assert len(view.reports.reports) == 2
            assert all(
                "Export to Comfy Workflow" in report.message
                for report in view.reports.reports
            )
        else:
            assert view.reports.reports == []
    finally:
        destroy_qt_object(parent)
        destroy_qt_object(edits)
