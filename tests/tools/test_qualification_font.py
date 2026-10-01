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

"""Verify platform font policy, real text resolution, and registration lifetimes."""

from __future__ import annotations

import os
from typing import cast

from PySide6.QtGui import QFont, QFontInfo, QRawFont
from PySide6.QtWidgets import QApplication
import pytest
from qfluentwidgets.common.font import fontFamilies  # type: ignore[import-untyped]
from shiboken6 import isValid

from substitute.presentation.localization import LocalizedSubtitleLabel
from tests.tools.qualification_font_boundary import (
    WindowsFontBoundary,
    windows_font_boundary,
)
from tools.qualification_font import QualificationFontSession, resolved_font_evidence
from tools.qualification_widgets import CaptureWidgetOwner

__all__ = ["windows_font_boundary"]
pytest_plugins = ("tests.support.qt.rendering_font",)


@pytest.mark.parametrize("host_platform", ["linux", "darwin"])
@pytest.mark.parametrize("windows_root", [None, "/not-a-windows-font-directory"])
def test_native_policy_preserves_real_fonts_and_renders_fluent_text(
    host_platform: str,
    windows_root: str | None,
    qt_application_owner: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    offscreen_rendering_font: None,
) -> None:
    """Resolve and paint actual Fluent glyphs without consulting Windows paths."""

    _ = offscreen_rendering_font
    before = QFont(qt_application_owner.font())
    fluent_before = fontFamilies()
    if windows_root is None:
        monkeypatch.delenv("WINDIR", raising=False)
    else:
        monkeypatch.setenv("WINDIR", windows_root)

    def forbid_windows_read(key: str, default: str | None = None) -> str | None:
        """Reject the original Linux regression at its environment boundary."""

        if key == "WINDIR":
            raise AssertionError("Native font policy read WINDIR.")
        return environ_get(key, default)

    environ_get = os.environ.get
    monkeypatch.setattr(os.environ, "get", forbid_windows_read)
    with QualificationFontSession(
        qt_application_owner, host_platform=host_platform
    ) as fonts:
        with CaptureWidgetOwner() as roots:
            label = roots.own(LocalizedSubtitleLabel("Readable Model 0123"))
            label.setStyleSheet("color: black; background-color: white;")
            label.adjustSize()
            evidence = fonts.evidence(label)
            image = label.grab().toImage()
            assert not image.isNull()
            assert any(
                image.pixelColor(x, y).lightness() < 100
                for x in range(image.width())
                for y in range(image.height())
            )
            assert any(
                image.pixelColor(x, y).lightness() > 240
                for x in range(image.width())
                for y in range(image.height())
            )
            fluent = cast(dict[str, object], evidence["fluent_label"])
            application = cast(dict[str, object], evidence["application"])
            assert evidence["source"] == "native-qt"
            assert evidence["qt_platform"] == qt_application_owner.platformName()
            assert fluent["resolved_family"] == QFontInfo(label.font()).family()
            assert fluent["raw_family"]
            assert fluent["glyphs_available"] is True
            assert application["resolved_family"] == QFontInfo(before).family()
            assert qt_application_owner.font() == before
    assert not isValid(label)
    assert qt_application_owner.font() == before
    assert fontFamilies() == fluent_before


def test_windows_keeps_installed_segoe_at_ten_points_and_restores_font(
    qt_application_owner: QApplication,
    windows_font_boundary: WindowsFontBoundary,
) -> None:
    """Preserve characterized Windows selection and release its exact registration."""

    before = QFont(qt_application_owner.font())
    with QualificationFontSession(qt_application_owner, host_platform="win32"):
        assert windows_font_boundary.paths == [str(windows_font_boundary.path)]
        assert qt_application_owner.font().family() == "Segoe UI"
        assert qt_application_owner.font().pointSize() == 10
        assert windows_font_boundary.active == {29}
    assert qt_application_owner.font() == before
    assert not windows_font_boundary.active
    assert windows_font_boundary.removed == [29]


@pytest.mark.parametrize("failure", ["root", "file", "registration", "family"])
def test_windows_setup_failures_are_actionable_and_release_partial_resources(
    failure: str,
    qt_application_owner: QApplication,
    windows_font_boundary: WindowsFontBoundary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject missing/invalid Segoe prerequisites without leaking partial state."""

    before = QFont(qt_application_owner.font())
    messages = {
        "root": "WINDIR is required",
        "file": "font is missing",
        "registration": "could not register",
        "family": "no font family",
    }
    if failure == "root":
        monkeypatch.delenv("WINDIR")
    elif failure == "file":
        windows_font_boundary.path.unlink()
    elif failure == "registration":
        windows_font_boundary.registration_fails = True
    else:
        windows_font_boundary.families = []
    with pytest.raises(RuntimeError, match=messages[failure]):
        with QualificationFontSession(qt_application_owner, host_platform="win32"):
            pytest.fail("A broken Windows font setup entered the capture.")
    assert qt_application_owner.font() == before
    assert not windows_font_boundary.active
    assert windows_font_boundary.removed == ([29] if failure == "family" else [])


@pytest.mark.parametrize("fail_capture", [False, True])
def test_capture_roots_dispose_before_font_release_without_touching_other_widgets(
    fail_capture: bool,
    qt_application_owner: QApplication,
    windows_font_boundary: WindowsFontBoundary,
) -> None:
    """Keep an unrelated window alive through success and exceptional cleanup."""

    before = QFont(qt_application_owner.font())
    with CaptureWidgetOwner() as existing:
        unrelated = existing.own(LocalizedSubtitleLabel("Existing window"))
        unrelated.show()
        created: list[LocalizedSubtitleLabel] = []

        def check_disposal() -> None:
            """Require capture destruction and font restoration at release time."""

            assert created and all(not isValid(widget) for widget in created)
            assert isValid(unrelated) and unrelated.isVisible()
            assert qt_application_owner.font() == before

        windows_font_boundary.before_release = check_disposal
        try:
            with QualificationFontSession(qt_application_owner, host_platform="win32"):
                with CaptureWidgetOwner() as roots:
                    created.append(roots.own(LocalizedSubtitleLabel("Capture title")))
                    if fail_capture:
                        raise ValueError("capture failed")
        except ValueError as error:
            assert fail_capture and str(error) == "capture failed"
        assert isValid(unrelated) and unrelated.isVisible()
    assert not windows_font_boundary.active
    assert qt_application_owner.font() == before


def test_nested_and_repeated_sessions_preserve_each_previous_font(
    qt_application_owner: QApplication,
    windows_font_boundary: WindowsFontBoundary,
) -> None:
    """Release inner IDs without invalidating an outer font registration."""

    before = QFont(qt_application_owner.font())
    session = QualificationFontSession(qt_application_owner, host_platform="win32")
    for _ in range(2):
        with session:
            outer_font = QFont(qt_application_owner.font())
            with QualificationFontSession(qt_application_owner, host_platform="win32"):
                assert len(windows_font_boundary.active) == 2
            assert len(windows_font_boundary.active) == 1
            assert qt_application_owner.font() == outer_font
        assert qt_application_owner.font() == before
        assert not windows_font_boundary.active
    assert windows_font_boundary.removed == [30, 29, 32, 31]


def test_invalid_native_font_and_post_registration_resolution_fail_cleanly(
    qt_application_owner: QApplication,
    windows_font_boundary: WindowsFontBoundary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A font name cannot claim readability when Qt has no usable native font."""

    before = QFont(qt_application_owner.font())
    monkeypatch.setattr(QRawFont, "fromFont", lambda _font: QRawFont())
    for platform in ("linux", "win32"):
        with pytest.raises(RuntimeError, match="readable qualification font"):
            with QualificationFontSession(qt_application_owner, host_platform=platform):
                pytest.fail("An unresolved font entered the capture.")
        assert qt_application_owner.font() == before
        assert not windows_font_boundary.active
    assert windows_font_boundary.removed == [29]


def test_font_release_failure_is_actionable(
    qt_application_owner: QApplication,
    windows_font_boundary: WindowsFontBoundary,
) -> None:
    """Do not silently claim cleanup when Qt rejects font deregistration."""

    before = QFont(qt_application_owner.font())
    windows_font_boundary.release_fails = True
    with pytest.raises(RuntimeError, match="release qualification font registration"):
        with QualificationFontSession(qt_application_owner, host_platform="win32"):
            pass
    assert qt_application_owner.font() == before


def test_font_evidence_uses_resolved_family_for_an_unavailable_requested_name(
    qt_application_owner: QApplication,
    offscreen_rendering_font: None,
) -> None:
    """Distinguish actual fallback from the requested font name in evidence."""

    _ = offscreen_rendering_font
    font = QFont(qt_application_owner.font())
    font.setFamily("SugarSubstitute missing qualification family")
    evidence = resolved_font_evidence(font)
    assert evidence["requested_families"] == [font.family()]
    assert evidence["resolved_family"] != font.family()
    assert evidence["raw_family"]
