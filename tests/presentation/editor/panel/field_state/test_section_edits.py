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

"""Verify semantic field edits publish the actual mutated section identity."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QWidget
from qfluentwidgets import LineEdit  # type: ignore[import-untyped]

from substitute.application.node_behavior import FieldBehavior, ResolvedFieldSpec
from substitute.presentation.editor.panel.menus.node_input_preset_apply import (
    apply_node_input_preset,
)
from substitute.domain.comfy_workflow import ComfyWorkflowConverter, DirectWorkflowState
from substitute.domain.generation.seed_control import SeedControlState, SeedMode
from substitute.presentation.widgets.seed_box import SeedBox
from substitute.presentation.widgets.combo_box import ComboBox
from substitute.presentation.editor.panel.widgets.fields.choice_combo import (
    EditorChoiceComboBox,
)
from substitute.domain.workflow import CubeState
from substitute.presentation.editor.panel.field_state_binding import EditorFieldBinding
from substitute.presentation.editor.panel.field_value_store import EditorFieldValueStore
from substitute.presentation.editor.panel.runtime_access import (
    field_state_controller_for_panel,
)
from tests.support.qt.lifecycle import destroy_qt_object, ensure_qt_application


class _Panel(QWidget):
    """Expose the real panel edit signal without optional preset consumers."""

    sectionEdited = Signal(object)

    def __init__(self, section: CubeState | DirectWorkflowState) -> None:
        """Own a replaceable projection with one authored field."""
        super().__init__()
        self._cube_states: dict[str, object] = {"A": section}


def _section(kind: str) -> CubeState | DirectWorkflowState:
    """Build a real document projection with an explicitly authored text input."""
    if kind == "cube":
        return CubeState(
            cube_id="test",
            version="1",
            alias="A",
            original_cube={},
            buffer={
                "nodes": {
                    "1": {"class_type": "TextSource", "inputs": {"text": "initial"}}
                }
            },
        )
    workflow: dict[str, object] = {
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
    return DirectWorkflowState(
        source_path=Path("source.json"),
        source_workflow=workflow,
        buffer=ComfyWorkflowConverter().convert(workflow),
    )


def _value(section: CubeState | DirectWorkflowState) -> object:
    """Read the field through the state owner's public editable buffer."""
    nodes = section.buffer["nodes"]
    assert isinstance(nodes, Mapping)
    node = nodes["1"]
    assert isinstance(node, Mapping)
    inputs = node["inputs"]
    assert isinstance(inputs, Mapping)
    return inputs["text"]


def _line_edit(panel: _Panel, section: CubeState | DirectWorkflowState) -> QLineEdit:
    """Wire a production Qt line edit through the panel's controller resolver."""
    widget: QLineEdit = LineEdit(panel)
    widget.setProperty(
        "input_metadata",
        {"cube_alias": "A", "node_name": "1", "key": "text", "type": "STRING"},
    )
    field_state_controller_for_panel(panel).wire_lineedit_state(widget, section)
    return widget


@pytest.mark.parametrize("kind", ["cube", "direct"])
@pytest.mark.parametrize("already_dirty", [False, True])
def test_field_edit_publishes_identity_without_preset_context(
    kind: str, already_dirty: bool
) -> None:
    """Each changed value emits once even when its section was already dirty."""
    ensure_qt_application()
    section = _section(kind)
    section.dirty = already_dirty
    panel = _Panel(section)
    changed: list[object] = []
    panel.sectionEdited.connect(changed.append)
    try:
        widget = _line_edit(panel, section)
        assert widget.text() == "initial"
        assert changed == []
        widget.setText("edited")
        assert _value(section) == "edited"
        assert section.dirty is True
        assert len(changed) == 1 and changed[0] is section
        widget.setText("edited")
        assert len(changed) == 1
        if isinstance(section, DirectWorkflowState):
            nodes = section.source_workflow["nodes"]
            assert isinstance(nodes, list) and isinstance(nodes[0], dict)
            assert nodes[0]["widgets_values"] == ["edited"]
    finally:
        destroy_qt_object(panel)


@pytest.mark.parametrize("kind", ["cube", "direct"])
def test_text_undo_redo_each_publish_authored_change(kind: str) -> None:
    """Undo and Redo must reach explicit-save tracking just like typed edits."""
    ensure_qt_application()
    section = _section(kind)
    panel = _Panel(section)
    observed: list[tuple[object, object]] = []
    panel.sectionEdited.connect(
        lambda actual: observed.append((actual, _value(section)))
    )
    try:
        widget = _line_edit(panel, section)
        widget.setCursorPosition(len(widget.text()))
        QTest.keyClicks(widget, "x")
        widget.undo()
        widget.redo()
        assert [value for _actual, value in observed] == [
            "initialx",
            "initial",
            "initialx",
        ]
        assert all(actual is section for actual, _value_at_edit in observed)
    finally:
        destroy_qt_object(panel)


def test_rebound_widget_publishes_the_replacement_state() -> None:
    """An old control resolves the live projection before identifying its mutation."""
    ensure_qt_application()
    old, replacement = _section("cube"), _section("cube")
    panel = _Panel(old)
    changed: list[object] = []
    panel.sectionEdited.connect(changed.append)
    try:
        widget = _line_edit(panel, old)
        panel._cube_states = {"A": replacement}
        widget.setText("current")
        assert _value(old) == "initial"
        assert _value(replacement) == "current"
        assert len(changed) == 1 and changed[0] is replacement
    finally:
        destroy_qt_object(panel)


@pytest.mark.parametrize("kind", ["cube", "direct"])
@pytest.mark.parametrize("with_widget", [False, True])
def test_preset_apply_publishes_once_without_relying_on_widget_feedback(
    kind: str, with_widget: bool
) -> None:
    """Applying authored values must notify before any already-current widget reacts."""
    ensure_qt_application()
    section = _section(kind)
    panel = _Panel(section)
    changed: list[object] = []
    panel.sectionEdited.connect(changed.append)
    try:
        field_state_controller_for_panel(panel)
        widget = _line_edit(panel, section) if with_widget else None
        spec = ResolvedFieldSpec(
            cube_alias="A",
            node_name="1",
            class_type="TextSource",
            field_key="text",
            field_type="STRING",
            constraints={},
            meta_info={},
            field_info=None,
            value="initial",
            field_behavior=FieldBehavior(field_key="text"),
        )
        report = apply_node_input_preset(
            field_writer=field_state_controller_for_panel(panel),
            cube_state=section,
            cube_alias="A",
            node_name="1",
            node_type="TextSource",
            preset_id="owned",
            preset_label="Owned",
            preset_inputs={"text": "preset"},
            node_inputs={"text": "initial"},
            field_specs={"text": spec},
            is_connection=lambda _value: False,
            input_widgets_by_field_key={("A", "1", "text"): widget}
            if widget is not None
            else {},
        )
        assert report.applied_keys == ("text",)
        assert _value(section) == "preset"
        assert len(changed) == 1 and changed[0] is section
        if widget is not None:
            assert widget.text() == "preset"
    finally:
        destroy_qt_object(panel)


def test_seed_mode_restoration_is_silent_and_changed_modes_publish() -> None:
    """Persisted seed intent uses the same identified edit path as numeric values."""
    ensure_qt_application()
    section = CubeState(
        cube_id="test",
        version="1",
        alias="A",
        original_cube={},
        buffer={"nodes": {"1": {"class_type": "KSampler", "inputs": {"seed": 42}}}},
        field_control_states={"1": {"seed": SeedControlState(SeedMode.FIXED)}},
    )
    panel = _Panel(section)
    changed: list[object] = []
    panel.sectionEdited.connect(changed.append)
    try:
        seed = SeedBox(panel)
        seed.setProperty(
            "input_metadata",
            {"cube_alias": "A", "node_name": "1", "key": "seed", "type": "INT"},
        )
        field_state_controller_for_panel(panel).bind_node_widget_state(
            seed, section, {}
        )
        assert seed.value() == 42
        assert seed.mode() == "fixed"
        assert changed == []
        seed.setMode("random")
        assert section.field_control_states["1"]["seed"].mode is SeedMode.RANDOM
        assert len(changed) == 1 and changed[0] is section
        seed.setMode("random")
        assert len(changed) == 1
        seed.setMode("fixed")
        assert len(changed) == 2 and changed[1] is section
    finally:
        destroy_qt_object(panel)


@pytest.mark.parametrize("prepared", [False, True], ids=["legacy", "prepared"])
@pytest.mark.parametrize(
    "literal", ["euler", "heun"], ids=["same_literal", "different_literal"]
)
def test_unlinking_a_choice_publishes_exactly_once(
    prepared: bool, literal: str
) -> None:
    """Clearing a link is an authored edit even when its literal stays identical."""
    ensure_qt_application()
    link = {"from_cube": "Other", "from_node": "sampler"}
    node: dict[str, object] = {
        "class_type": "KSampler",
        "inputs": {"sampler_name": "euler"},
        "sampler_link": link.copy(),
    }
    section = CubeState(
        cube_id="test",
        version="1",
        alias="A",
        original_cube={},
        buffer={"nodes": {"1": node}},
    )
    panel = _Panel(section)
    changed: list[object] = []
    panel.sectionEdited.connect(changed.append)
    try:
        combo: ComboBox
        if prepared:
            editor_combo = EditorChoiceComboBox(panel)
            editor_combo.reconcile_choice_items(
                (("Linked", link), ("euler", "euler"), ("heun", "heun")), "Linked"
            )
            combo = editor_combo
        else:
            combo = ComboBox(panel)
            combo.addItems(["🔗 Other", "euler", "heun"])
        combo.setProperty(
            "input_metadata",
            {
                "cube_alias": "A",
                "node_name": "1",
                "key": "sampler_name",
                "type": "LIST",
            },
        )
        field_state_controller_for_panel(panel).wire_combobox_state(combo, section)
        assert changed == []
        combo.setCurrentText(literal)
        assert "sampler_link" not in node
        assert node["inputs"] == {"sampler_name": literal}
        assert section.dirty
        assert len(changed) == 1 and changed[0] is section
        combo.currentTextChanged.emit(literal)
        assert len(changed) == 1
    finally:
        destroy_qt_object(panel)


def test_rejected_canonical_write_does_not_publish_or_change_data() -> None:
    """Unknown direct-node identities stay outside authored edit publication."""
    section = _section("direct")
    changed: list[object] = []
    store = EditorFieldValueStore(section_edited=changed.append)
    before = deepcopy(section.buffer)
    binding = EditorFieldBinding(
        cube_alias="A",
        node_name="absent",
        field_key="text",
        storage_kind="input",
        value_source=None,
        resolved_display_value=None,
        prompt_field_identity="absent.text",
    )
    assert not store.set_field_value(section, binding, "invalid")
    assert section.buffer == before
    assert not section.dirty
    assert changed == []


def test_authored_edit_is_published_before_presentation_failure() -> None:
    """A failed value-specific consumer cannot prevent document edit tracking."""
    section = _section("cube")
    published: list[object] = []
    presentation_saw_published: list[bool] = []

    def fail_presentation(_binding: EditorFieldBinding, _value: object) -> None:
        """Fail after observing that explicit-save tracking was already notified."""
        presentation_saw_published.append(
            len(published) == 1 and published[0] is section
        )
        raise RuntimeError("Controlled presentation failure")

    store = EditorFieldValueStore(fail_presentation, section_edited=published.append)
    binding = EditorFieldBinding(
        cube_alias="A",
        node_name="1",
        field_key="text",
        storage_kind="input",
        value_source=None,
        resolved_display_value=None,
        prompt_field_identity="1.text",
    )
    assert store.set_field_value(section, binding, "edited")
    assert _value(section) == "edited"
    assert section.dirty
    assert len(published) == 1 and published[0] is section
    assert presentation_saw_published == [True]
