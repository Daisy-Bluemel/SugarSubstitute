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

"""Render and reconcile ordinary finite-choice fields in the editor."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, IconWidget  # type: ignore[import-untyped]

from sugarsubstitute_shared.presentation.localization import (
    ApplicationMessage,
    app_text,
    clear_localized_property,
    set_localized_placeholder,
    set_localized_accessible_name,
    set_localized_tooltip,
)
from substitute.presentation.widgets import ComboBox

EMPTY_CHOICE_PLACEHOLDER: ApplicationMessage = app_text("No options available")
RETAINED_FILE_NOTICE: ApplicationMessage = app_text(
    "This filename is not in Comfy's current list. It will be checked when generating."
)


class EditorChoiceComboBox(ComboBox):
    """Own editor choice rows, empty presentation, and silent replacement."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize an editor combo with no backend-value mappings."""

        super().__init__(parent)
        self._editor_choice_values_by_label: dict[str, object] = {}
        self._retained_value: str | None = None
        self._retained_status: QWidget = IconWidget(FluentIcon.INFO, self)
        self._retained_status.setFixedSize(16, 16)
        set_localized_tooltip(self._retained_status, RETAINED_FILE_NOTICE)
        set_localized_accessible_name(self._retained_status, RETAINED_FILE_NOTICE)
        self._retained_status.hide()
        self.currentTextChanged.connect(self._update_retained_status)

    @property
    def retained_choice_indicator(self) -> QWidget:
        """Expose a separate row-owned status target safe from field-help rebinding."""

        return self._retained_status

    def reconcile_choice_items(
        self,
        items: Sequence[tuple[str, object]],
        selected_label: str,
        *,
        retained_value: str | None = None,
    ) -> None:
        """Replace listing rows silently while keeping an unmatched file explicit."""

        previous_block_state = self.blockSignals(True)
        try:
            self.clear()
            self._retained_value = retained_value
            self._editor_choice_values_by_label = dict(items)
            labels = [label for label, _value in items]
            if retained_value is not None:
                labels.insert(0, retained_value)
                self._editor_choice_values_by_label[retained_value] = retained_value
            self.addItems(labels)
            has_options = bool(labels)
            self.setEnabled(has_options)
            if has_options:
                clear_localized_property(self, "placeholder")
                self.setPlaceholderText("")
            else:
                set_localized_placeholder(self, EMPTY_CHOICE_PLACEHOLDER)
            if has_options:
                self.setCurrentText(
                    selected_label
                    if retained_value is not None
                    else selected_label or labels[0]
                )
        finally:
            self.blockSignals(previous_block_state)
        self._update_retained_status()

    def _update_retained_status(self, _text: str = "") -> None:
        """Distinguish the retained filename without altering its committed text."""

        self._retained_status.setVisible(
            self._retained_value is not None
            and self.currentText() == self._retained_value
        )

    def editor_choice_value(self, label: str) -> object | None:
        """Return the backend value represented by one visible label."""

        return self._editor_choice_values_by_label.get(label)


__all__ = ["EMPTY_CHOICE_PLACEHOLDER", "EditorChoiceComboBox"]
