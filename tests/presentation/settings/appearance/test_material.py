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

"""Verify capability-gated material choices and restart-required saves."""

from __future__ import annotations

from typing import cast

import pytest
from PySide6.QtWidgets import QWidget
from qfluentwidgets import ComboBox  # type: ignore[import-untyped]

from substitute.application.appearance import (
    ActiveAppearanceBaseline,
    AppearanceRestartCoordinator,
    WindowMaterialCapabilities,
)
from substitute.application.restart_requirements import RestartRequirementService
from substitute.domain.appearance import AppearanceBackdropMode
from substitute.presentation.settings.settings_catalog_builders import (
    AppearanceSettingsContext,
    build_appearance_settings_page,
)
from tests.presentation.settings.appearance.support import (
    AppearanceRuntime,
    RecordingAppearanceRestartCoordinator,
    label_texts,
    settings_control,
)
from tests.presentation.settings.generation.support import application


@pytest.mark.parametrize(
    ("mica_available", "acrylic_available", "labels"),
    (
        (False, False, ("Plain",)),
        (True, False, ("Plain", "Mica")),
        (False, True, ("Plain", "Acrylic")),
        (True, True, ("Plain", "Mica", "Acrylic")),
    ),
)
def test_material_choices_follow_capabilities_without_saving(
    mica_available: bool,
    acrylic_available: bool,
    labels: tuple[str, ...],
) -> None:
    """Always offer Plain and only effects supported by the active provider."""

    application()
    runtime = AppearanceRuntime(
        material_capabilities=WindowMaterialCapabilities(
            mica_alt_available=mica_available,
            acrylic_available=acrylic_available,
        )
    )
    coordinator = RecordingAppearanceRestartCoordinator()
    parent = QWidget()
    try:
        page = build_appearance_settings_page(
            AppearanceSettingsContext(
                appearance_runtime=runtime,
                appearance_restart_coordinator=cast(
                    AppearanceRestartCoordinator, coordinator
                ),
                show_restart_requirements=None,
            )
        )
        row = settings_control(page, "appearance.window.material").factory(parent)
        combo = row.findChild(ComboBox)
        assert combo is not None
        assert tuple(combo.itemText(index) for index in range(combo.count())) == labels
        assert "Plain is used when window effects are unavailable." in label_texts(row)
        assert combo.currentData() is (
            runtime.resolve_preferences().effective_backdrop_mode
            or AppearanceBackdropMode("plain")
        )
        assert (
            runtime.load_preferences().backdrop_mode is AppearanceBackdropMode.MICA_ALT
        )
        assert coordinator.saved == []
    finally:
        parent.deleteLater()


def test_plain_selection_uses_restart_coordinator() -> None:
    """Save Plain, show pending restart work, and clear it when reverting."""

    application()
    runtime = AppearanceRuntime(
        material_capabilities=WindowMaterialCapabilities(mica_alt_available=True)
    )
    restart_requirements = RestartRequirementService()
    coordinator = AppearanceRestartCoordinator(
        appearance_runtime=runtime,
        active_baseline=ActiveAppearanceBaseline(runtime.load_preferences()),
        restart_requirements=restart_requirements,
    )
    restart_dialog_calls: list[str] = []
    parent = QWidget()
    try:
        page = build_appearance_settings_page(
            AppearanceSettingsContext(
                appearance_runtime=runtime,
                appearance_restart_coordinator=coordinator,
                show_restart_requirements=lambda: restart_dialog_calls.append("show"),
            )
        )
        row = settings_control(page, "appearance.window.material").factory(parent)
        combo = row.findChild(ComboBox)
        assert combo is not None
        plain_index = combo.findText("Plain")
        assert plain_index >= 0
        combo.setCurrentIndex(plain_index)
        assert runtime.load_preferences().backdrop_mode.value == "plain"
        assert restart_requirements.snapshot().count == 1
        assert restart_dialog_calls == ["show"]
        combo.setCurrentIndex(combo.findData(AppearanceBackdropMode.MICA_ALT))
        assert restart_requirements.snapshot().count == 0
        assert restart_dialog_calls == ["show"]
    finally:
        parent.deleteLater()
