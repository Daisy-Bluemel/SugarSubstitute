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

"""Verify explicit capture-root cleanup, including producer setup failures."""

from __future__ import annotations

from builtins import ExceptionGroup
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from PySide6.QtGui import QFont, QImage
from PySide6.QtWidgets import QApplication, QLabel, QWidget
import pytest
from qfluentwidgets import Theme, theme  # type: ignore[import-untyped]
from shiboken6 import delete, isValid

from substitute.infrastructure.model_recommendations.thumbnail_fetcher import (
    CivitaiThumbnailFetcher,
)
from substitute.presentation.editor.panel.view import EditorPanel
from sugarsubstitute_shared.model_discovery import DiscoveredModel, ModelArtifactKind
from sugarsubstitute_shared.model_updates import ModelUpdateProposal, ModelUsageRecord
from tests.tools.qualification_font_boundary import (
    WindowsFontBoundary,
    windows_font_boundary,
)
from tests.presentation.theme.support import ThemeWidgetOwner
from tools.model_update_lora_render import render_lora_prompt_node_card
from tools.model_update_node_card_render import render_node_card
from tools.model_update_render_surfaces import (
    RealUpdateScenario,
    UpdatePreferenceService,
)
from tools.qualification_font import QualificationFontSession
from tools.qualification_widgets import CaptureWidgetOwner

__all__ = ["windows_font_boundary"]
pytest_plugins = ("tests.support.qt.rendering_font",)
_Widget = TypeVar("_Widget", bound=QWidget)


@pytest.fixture
def dark_capture_theme(qt_application_owner: QApplication) -> Iterator[None]:
    """Match the journey entry point and restore the worker's previous theme."""

    previous_theme = theme()
    try:
        with ThemeWidgetOwner(qt_application_owner).using_theme(Theme.DARK):
            yield
    finally:
        assert theme() == previous_theme


class _SelfDeletingWindow(QWidget):
    """Model a native close handler that completes its own disposal."""

    def close(self) -> bool:
        """Destroy this root before returning from the close boundary."""

        delete(self)
        return True


class _FailedCloseWindow(QWidget):
    """Expose a close failure without preventing targeted deferred deletion."""

    def close(self) -> bool:
        """Fail before the native owner receives its deletion request."""

        raise RuntimeError("injected close failure")


class _RecordingRoots(CaptureWidgetOwner):
    """Retain explicit construction identities for post-disposal assertions."""

    def __init__(self) -> None:
        """Start an ordinary owner with a test-only immutable identity log."""

        super().__init__()
        self.created: list[QWidget] = []

    def own(self, widget: _Widget) -> _Widget:
        """Record only the widget the producer explicitly transfers."""

        self.created.append(widget)
        return super().own(widget)


class _LocalThumbnailFetcher(CivitaiThumbnailFetcher):
    """Supply a real decodable image without a network boundary."""

    def __init__(self, payload: bytes) -> None:
        """Retain the fixture image body for the production thumbnail preparer."""

        self._payload = payload

    def fetch(self, url: str) -> bytes:
        """Return local image data for the scenario's declared thumbnail."""

        return self._payload


def test_owner_accepts_self_deletion_during_close() -> None:
    """Avoid touching an invalid Qt wrapper after close destroys its root."""

    with CaptureWidgetOwner() as roots:
        widget = roots.own(_SelfDeletingWindow())
    assert not isValid(widget)


def test_failed_close_still_disposes_every_owned_root_before_font_release(
    qt_application_owner: QApplication,
    windows_font_boundary: WindowsFontBoundary,
) -> None:
    """A failing close cannot strand other capture widgets or suppress the error."""

    created: list[QWidget] = []

    def require_disposed() -> None:
        """Check every owned root at the font registration release boundary."""

        assert len(created) == 2
        assert all(not isValid(widget) for widget in created)

    windows_font_boundary.before_release = require_disposed
    with pytest.raises(ExceptionGroup, match="widget disposal failed") as caught:
        with QualificationFontSession(qt_application_owner, host_platform="win32"):
            with CaptureWidgetOwner() as roots:
                created.extend((roots.own(QWidget()), roots.own(_FailedCloseWindow())))
    assert str(caught.value.exceptions[0]) == "injected close failure"
    assert not windows_font_boundary.active


@pytest.mark.parametrize(
    "kind", [ModelArtifactKind.CHECKPOINTS, ModelArtifactKind.LORAS]
)
def test_update_producer_setup_failure_disposes_frame_and_editor_before_font_release(
    kind: ModelArtifactKind,
    qt_application_owner: QApplication,
    windows_font_boundary: WindowsFontBoundary,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep both independently created real roots owned when node setup fails."""

    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    thumbnail = tmp_path / "thumbnail.png"
    assert image.save(str(thumbnail))
    fetcher = _LocalThumbnailFetcher(thumbnail.read_bytes())
    scenario = _scenario(kind)
    owner = _RecordingRoots()

    def fail_node_setup(panel: EditorPanel) -> None:
        """Interrupt after the production editor exists but before return."""

        assert panel in owner.created
        raise ValueError("injected node setup failure")

    def require_disposed() -> None:
        """Require the real frame and parentless editor to die before release."""

        assert len(owner.created) == 2
        assert any(isinstance(widget, EditorPanel) for widget in owner.created)
        assert all(not isValid(widget) for widget in owner.created)

    monkeypatch.setattr(EditorPanel, "_build_behavior_snapshot", fail_node_setup)
    windows_font_boundary.before_release = require_disposed
    with pytest.raises(ValueError, match="injected node setup failure"):
        with QualificationFontSession(qt_application_owner, host_platform="win32"):
            with owner:
                if kind is ModelArtifactKind.LORAS:
                    render_lora_prompt_node_card(
                        qt_application_owner,
                        UpdatePreferenceService(),
                        scenario,
                        fetcher,
                        tmp_path,
                        "test",
                        roots=owner,
                    )
                else:
                    render_node_card(
                        qt_application_owner,
                        UpdatePreferenceService(),
                        (scenario,),
                        fetcher,
                        tmp_path,
                        "test",
                        roots=owner,
                        workflow_fixture="workflow_sdxl_baseline.json",
                        cube_alias="Cube 1: SDXL/Text to Image",
                        node_name="checkpoint",
                        input_name="ckpt_name",
                    )
    assert not windows_font_boundary.active


@pytest.mark.parametrize(
    "kind", [ModelArtifactKind.CHECKPOINTS, ModelArtifactKind.LORAS]
)
def test_update_producer_success_captures_readable_surfaces_and_disposes_roots(
    kind: ModelArtifactKind,
    qt_application_owner: QApplication,
    tmp_path: Path,
    dark_capture_theme: None,
) -> None:
    """Exercise real node and prompt interactions using only local thumbnails."""

    _ = dark_capture_theme
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    thumbnail = tmp_path / "thumbnail.png"
    assert image.save(str(thumbnail))
    fetcher = _LocalThumbnailFetcher(thumbnail.read_bytes())
    scenario = _scenario(kind)
    owner = _RecordingRoots()
    before = QFont(qt_application_owner.font())
    with QualificationFontSession(qt_application_owner) as fonts:
        with owner:
            if kind is ModelArtifactKind.LORAS:
                frame = render_lora_prompt_node_card(
                    qt_application_owner,
                    UpdatePreferenceService(),
                    scenario,
                    fetcher,
                    tmp_path,
                    "success",
                    roots=owner,
                )
                expected_captures = 3
            else:
                frame = render_node_card(
                    qt_application_owner,
                    UpdatePreferenceService(),
                    (scenario,),
                    fetcher,
                    tmp_path,
                    "success",
                    roots=owner,
                    workflow_fixture="workflow_sdxl_baseline.json",
                    cube_alias="Cube 1: SDXL/Text to Image",
                    node_name="checkpoint",
                    input_name="ckpt_name",
                )
                expected_captures = 7
            labels = [
                label
                for label in frame.findChildren(QLabel)
                if label.text() and label.isVisibleTo(frame)
            ]
            assert labels
            for label in labels:
                font = fonts.evidence(label)
                assert font["fluent_label"]
            captures = tuple(tmp_path.glob("success-*.png"))
            assert len(captures) == expected_captures
            for capture in captures:
                rendered = QImage(str(capture))
                assert not rendered.isNull()
                assert rendered.width() >= 1000
                assert rendered.height() >= 700
                assert any(
                    rendered.pixelColor(x, y).lightness() > 180
                    for x in range(0, rendered.width(), 4)
                    for y in range(0, rendered.height(), 4)
                )
            assert len(owner.created) == 2
            assert all(isValid(widget) for widget in owner.created)
        assert all(not isValid(widget) for widget in owner.created)
    assert qt_application_owner.font() == before


def _scenario(kind: ModelArtifactKind) -> RealUpdateScenario:
    """Build a real immutable update identity with local-only image retrieval."""

    version = DiscoveredModel(
        artifact_kind=kind,
        model_id=7,
        version_id=8,
        model_name="Fixture model",
        version_name="v8",
        creator="creator",
        base_model="SDXL",
        file_name="fixture.safetensors",
        size_bytes=100,
        sha256="a" * 64,
        download_url="https://civitai.com/api/download/models/8",
        model_page_url="https://civitai.com/models/7",
        thumbnail_url="https://example.invalid/fixture.png",
        provider_rank=1,
    )
    current = ModelUsageRecord(
        sha256=version.sha256,
        path=Path("models") / kind.value / version.file_name,
        artifact_kind=kind,
        model_id=version.model_id,
        version_id=version.version_id,
        base_model=version.base_model,
        usage_count=1,
        last_used_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    candidate = replace(
        version,
        version_id=9,
        version_name="v9",
        sha256="b" * 64,
        download_url="https://civitai.com/api/download/models/9",
    )
    return RealUpdateScenario(
        ModelUpdateProposal(current=current, candidate=candidate), (version, candidate)
    )
