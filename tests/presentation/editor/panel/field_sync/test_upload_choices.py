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

"""Keep authored file choices truthful through real widget hydration and edits."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from substitute.application.localization import NodePresentationService
from substitute.domain.localization import (
    NodeFieldPresentationRequest,
    NodePresentationRequest,
    NodeTextCatalogSnapshot,
)
from sugarsubstitute_shared.localization import render_source_application_text
from substitute.presentation.editor.panel.node_presentation_binding import (
    NodeCardPresentationBinding,
)
from substitute.presentation.editor.panel.widgets.field_row import FieldRowBuilder
from substitute.application.node_behavior import (
    FieldBehavior,
    RowMode,
    EditorBehaviorSnapshot,
    NodeBehaviorService,
)
from substitute.domain.comfy_workflow import (
    ComfyApiGraphBuilder,
    ComfyWorkflowConverter,
    DirectWorkflowState,
)
from substitute.presentation.editor.catalog.snapshots import (
    CatalogSnapshotIdentity,
    CatalogSnapshotReadiness,
    CatalogSnapshotStatus,
)
from substitute.presentation.editor.panel.choice_field_surface_reconciler import (
    ChoiceFieldSurfaceReconciler,
)
from substitute.presentation.editor.panel.current_field_state_resolver import (
    CurrentEditorFieldStateResolver,
)
from substitute.presentation.editor.panel.factories.choice_factory import (
    widget_factory_list_str,
)
from substitute.presentation.editor.panel.field_registry import EditorFieldRegistry
from substitute.presentation.editor.panel.field_state_binding import EditorFieldBinding
from substitute.presentation.editor.panel.field_value_store import EditorFieldValueStore
from substitute.presentation.editor.panel.field_widget_state_controller import (
    FieldWidgetStateController,
)
from substitute.presentation.editor.panel.model_choice_snapshots import (
    PanelModelChoiceSnapshot,
    PanelModelChoiceSnapshotKind,
    PanelModelChoiceSnapshotRequest,
)
from substitute.presentation.editor.panel.widgets.fields.choice_combo import (
    EditorChoiceComboBox,
    RETAINED_FILE_NOTICE,
)
from substitute.presentation.widgets.media_wall import unavailable_thumbnail_readiness
from tests.support.qt.lifecycle import destroy_qt_object, ensure_qt_application
from tests.support.qt.semantic_wait import wait_for_qt_condition

_SELECTED = "selected-new.mp4"
_OLD = "old.mp4"


class _Gateway:
    """Expose replaceable backend listings while preserving upload metadata."""

    def __init__(self, options: tuple[str, ...] | None = (_OLD,)) -> None:
        """Keep the listing external to the authored selection."""
        self.options = options

    def field_info(self) -> list[object]:
        """Return native typed COMBO metadata for a video reference."""
        metadata: dict[str, object] = {"video_upload": True}
        if self.options is not None:
            metadata["options"] = list(self.options)
        return ["COMBO", metadata]

    def get_node_definition(self, class_type: str) -> dict[str, object]:
        """Publish the current cached backend definition."""
        return {class_type: {"input": {"required": {"resource": self.field_info()}}}}

    def get_required_node_definition(self, class_type: str) -> dict[str, object]:
        """Return the same definition for mandatory lookups."""
        return self.get_node_definition(class_type)


class _OrdinaryChoice:
    """Keep file references outside graphical model catalog presentation."""

    def snapshot_for_field(
        self, _request: PanelModelChoiceSnapshotRequest
    ) -> PanelModelChoiceSnapshot:
        """Return the ordinary combo decision for this non-model input."""
        return PanelModelChoiceSnapshot(
            identity=CatalogSnapshotIdentity(source_revision=1),
            status=CatalogSnapshotStatus(
                CatalogSnapshotReadiness.DISABLED, unavailable_reason="ordinary_choice"
            ),
            kind=PanelModelChoiceSnapshotKind.NONE,
            thumbnail_readiness=unavailable_thumbnail_readiness("ordinary_choice"),
        )


class _Host:
    """Mount the real field widget, state binding, and live reconciliation owners."""

    def __init__(
        self, *, options: tuple[str, ...] | None = (_OLD,), value: str = _SELECTED
    ) -> None:
        """Import a selected file and mount its current editor projection."""
        self.node_definition_gateway = _Gateway(options)
        workflow: dict[str, object] = {
            "nodes": [
                {
                    "id": 1,
                    "type": "CustomSource",
                    "inputs": [],
                    "outputs": [],
                    "widgets_values": [value],
                }
            ],
            "links": [],
        }
        payload = self.node_definition_gateway.get_node_definition("CustomSource")
        definition = payload["CustomSource"]
        assert isinstance(definition, Mapping)
        definitions = {"CustomSource": definition}
        self.document = DirectWorkflowState(
            source_path=Path("owned-upload.json"),
            source_workflow=deepcopy(workflow),
            buffer=ComfyWorkflowConverter().convert(
                workflow, node_definitions=definitions
            ),
        )
        self._cube_states = {"Workflow": self.document}
        self._stack_order = ["Workflow"]
        self.behavior = NodeBehaviorService(
            node_definition_gateway=self.node_definition_gateway
        )
        self.owner = QWidget()
        self.owner.resize(480, 150)
        spec = self.current_behavior_snapshot().field_specs_by_alias["Workflow"]["1"][
            "resource"
        ]
        candidate = widget_factory_list_str(
            self.owner,
            "1",
            "resource",
            spec.value,
            {},
            field_type=spec.field_type,
            node_type="CustomSource",
            node_definition_gateway=self.node_definition_gateway,
            field_info=spec.field_info,
        )
        assert isinstance(candidate, EditorChoiceComboBox)
        self.combo = candidate
        self.combo.resize(320, 34)
        self.combo.setProperty(
            "input_metadata",
            {
                "cube_alias": "Workflow",
                "node_name": "1",
                "key": "resource",
                "node_type": "CustomSource",
                "type": "COMBO",
                "value_source": "explicit",
            },
        )
        self.changes: list[object] = []
        store = EditorFieldValueStore(
            lambda _binding, value: self.changes.append(value)
        )
        FieldWidgetStateController(
            store, CurrentEditorFieldStateResolver(self)
        ).wire_combo_state(self.combo, self.document)
        registry = EditorFieldRegistry()
        binding = EditorFieldBinding.from_widget(self.combo)
        assert binding is not None
        registry.register(binding, self.combo)
        self.reconciler = ChoiceFieldSurfaceReconciler(
            host=self,
            field_registry=registry,
            snapshot_controller=_OrdinaryChoice(),
            thumbnail_repository_available=False,
        )

    def current_behavior_snapshot(self) -> EditorBehaviorSnapshot:
        """Resolve current live metadata against the real direct document."""
        return self.behavior.build_snapshot(
            cube_states=self._cube_states, stack_order=self._stack_order
        )

    def refresh(self, options: tuple[str, ...] | None) -> None:
        """Refresh only the existing control through the production reconciler."""
        self.node_definition_gateway.options = options
        result = self.reconciler.reconcile(("CustomSource",))
        assert result.fallback_node_classes == ()
        assert result.reconciled_field_count == 1


@pytest.fixture
def editor() -> Iterator[_Host]:
    """Own and synchronously destroy every widget in this test editor."""
    ensure_qt_application()
    host = _Host()
    try:
        yield host
    finally:
        destroy_qt_object(host.owner)


@pytest.mark.parametrize(
    "options", [(_OLD,), (), None], ids=["stale", "empty", "unavailable"]
)
@pytest.mark.parametrize("value", [_SELECTED, ""], ids=["filename", "blank"])
def test_initial_hydration_displays_exact_authored_file(
    options: tuple[str, ...] | None, value: str
) -> None:
    """A populated, empty, or missing listing cannot impersonate a selection."""
    ensure_qt_application()
    host = _Host(options=options, value=value)
    try:
        assert host.combo.currentText() == value
        assert host.changes == []
        assert not host.document.dirty
        assert host.combo.property("choice_availability") == (
            "unavailable" if options is None else "populated" if options else "empty"
        )
    finally:
        destroy_qt_object(host.owner)


def test_refreshes_preserve_file_identity_and_only_explicit_choice_commits(
    editor: _Host,
) -> None:
    """Repeated and late listings cannot overwrite the user's latest selection."""
    original = deepcopy(editor.document.source_workflow)
    for options in ((_OLD, _SELECTED), (_OLD,), (), None, (_OLD,)):
        editor.refresh(options)
        assert editor.combo.currentText() == _SELECTED
        assert editor.document.source_workflow == original
        assert not editor.document.dirty
        assert editor.changes == []
    editor.combo.setCurrentText(_OLD)
    assert editor.document.dirty
    assert editor.changes == [_OLD]
    snapshot = editor.current_behavior_snapshot()
    assert snapshot.field_specs_by_alias["Workflow"]["1"]["resource"].value == _OLD
    nodes = editor.document.source_workflow["nodes"]
    assert isinstance(nodes, list) and isinstance(nodes[0], dict)
    assert nodes[0]["widgets_values"] == [_OLD]
    editor.refresh((_SELECTED,))
    assert editor.combo.currentText() == _OLD
    assert editor.changes == [_OLD]
    graph = ComfyApiGraphBuilder().build(editor.document.buffer)
    node = graph["1"]
    assert isinstance(node, Mapping)
    inputs = node["inputs"]
    assert isinstance(inputs, Mapping)
    assert inputs["resource"] == _OLD


def test_search_cancel_and_focus_loss_do_not_commit_an_old_file(editor: _Host) -> None:
    """Keyboard search stays transient until the user confirms a listed result."""
    editor.owner.show()
    editor.combo.show()
    editor.combo.setFocus()
    wait_for_qt_condition(lambda: editor.combo.hasFocus(), timeout_ms=1000)
    outside = QLabel("Outside", editor.owner)
    outside.setGeometry(340, 80, 100, 30)
    outside.show()
    for cancel in ("escape", "outside"):
        editor.combo.setFocus()
        QTest.keyClicks(editor.combo, "old")
        assert editor.combo.currentText() == _SELECTED
        if cancel == "outside":
            QTest.mouseClick(outside, Qt.MouseButton.LeftButton)
        else:
            QTest.keyClick(editor.combo, Qt.Key.Key_Escape)
        wait_for_qt_condition(lambda: editor.combo.text() == "", timeout_ms=1000)
        assert editor.combo.currentText() == _SELECTED
        assert editor.changes == []
        assert not editor.document.dirty
        editor.combo.setFocus()
    QTest.keyClicks(editor.combo, "old")
    QTest.keyClick(editor.combo, Qt.Key.Key_Return)
    assert editor.combo.currentText() == _OLD
    assert editor.changes == [_OLD]
    assert editor.document.dirty


@pytest.mark.parametrize("row_kind", ["scalar", "full_width", "grouped"])
def test_retained_status_survives_field_help_and_locale_rebinding(
    editor: _Host, row_kind: str
) -> None:
    """Keep the visible retained-reference notice separate from backend field help."""
    behavior = FieldBehavior(
        field_key="resource",
        row_mode=RowMode.FULL_WIDTH if row_kind == "full_width" else RowMode.INLINE,
    )
    builder = FieldRowBuilder(
        editor.owner,
        icon_builder=lambda _icon: QWidget(),
        icon_resolver=lambda _node, _key, _index: None,
    )
    if row_kind == "grouped":
        built = builder.build_n_column_row(
            fields=[("resource", editor.combo)], field_behaviors={"resource": behavior}
        )
    else:
        built = builder.build_input_row(
            label="resource", widget=editor.combo, field_behavior=behavior
        )
    layout = QVBoxLayout(editor.owner)
    layout.addWidget(built.row)
    catalog = NodeTextCatalogSnapshot(
        effective_language_identifier="en",
        revision=1,
        active_layers=(),
        english_layers=(),
    )
    binding = NodeCardPresentationBinding(
        owner=built.row,
        service=NodePresentationService(
            lambda: catalog, application_text_renderer=render_source_application_text
        ),
        request=NodePresentationRequest(
            class_type="CustomSource",
            node_name="1",
            fields=(
                NodeFieldPresentationRequest(
                    field_key="resource", raw_tooltip="Backend-owned help"
                ),
            ),
        ),
    )
    binding.add_field_targets(built.text_targets)
    editor.owner.show()
    indicator = editor.combo.retained_choice_indicator
    for _refresh in range(2):
        binding.retranslate()
        QApplication.sendEvent(built.row, QEvent(QEvent.Type.LanguageChange))
        assert editor.combo.accessibleDescription() == "Backend-owned help"
        assert indicator.isVisible()
        assert indicator.toolTip() == str(RETAINED_FILE_NOTICE)
        assert indicator.accessibleName() == str(RETAINED_FILE_NOTICE)
        assert editor.combo.currentText() == _SELECTED
        assert editor.changes == []
        assert not editor.document.dirty
    editor.refresh((_OLD, _SELECTED))
    assert not indicator.isVisible()
    editor.refresh((_OLD,))
    assert indicator.isVisible()
    editor.combo.setCurrentText(_OLD)
    assert not indicator.isVisible()
    assert editor.changes == [_OLD]
