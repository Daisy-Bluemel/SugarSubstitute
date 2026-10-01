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

"""Preserve native Sugar Script filter syntax across translated save dialogs."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QApplication
import pytest

from tools.translation_catalog_registry import (
    TranslationDomain,
    release_translation_catalogs,
)
from .support import SaveDialog, make_save_view

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_CATALOGS = tuple(
    artifact.source_path
    for artifact in release_translation_catalogs(_PROJECT_ROOT)
    if artifact.domain is TranslationDomain.APPLICATION
) + (_PROJECT_ROOT / "translations" / "app_qps_ploc.ts",)


class _CatalogTranslator(QTranslator):
    """Expose actual TS catalog text through Qt without a test-time compiler."""

    def __init__(self, path: Path) -> None:
        """Read the generated or authored application messages verbatim."""

        super().__init__()
        self.messages = {
            message.findtext("source", ""): message.findtext("translation", "")
            for context in ET.parse(path).getroot().findall("context")
            if context.findtext("name") == "AppText"
            for message in context.findall("message")
        }

    def translate(
        self,
        context: str,
        source_text: str,
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str:
        """Let the real rendering owner interpolate opaque arguments afterward."""

        return self.messages.get(source_text, "") if context == "AppText" else ""


@pytest.mark.parametrize("catalog", _CATALOGS, ids=lambda path: path.stem)
def test_save_as_translates_label_without_changing_native_filter(
    tmp_path: Path, qt_application_owner: QApplication, catalog: Path
) -> None:
    """Every release and generated pseudo label keeps the literal file pattern."""

    translator = _CatalogTranslator(catalog)
    assert qt_application_owner.installTranslator(translator)
    try:
        view = make_save_view(tmp_path)
        dialog = SaveDialog("")
        assert (
            view.workspace_file_actions.recipe_save_actions.on_save_as_clicked(
                file_dialog=dialog
            )
            is False
        )
        assert dialog.calls == 1
        assert "(*.sugar)" in dialog.requested_filter
        template = translator.messages.get(
            "Sugar Script (%1)", translator.messages.get("Sugar Script (*.sugar)", "")
        )
        assert template
        assert dialog.requested_filter == template.replace("%1", "*.sugar")
        assert "%1" not in dialog.requested_filter
        if catalog.stem == "app_qps_ploc":
            assert dialog.requested_filter != "Sugar Script (*.sugar)"
        assert view.unsaved_work_service.state_for("workflow").dirty is True
        assert view.reports.reports == []
    finally:
        qt_application_owner.removeTranslator(translator)
