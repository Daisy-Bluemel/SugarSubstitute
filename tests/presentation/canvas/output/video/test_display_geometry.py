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

"""Verify physical video sizing follows changes in authoritative display geometry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtTest import QSignalSpy
import pytest

from substitute.application.ports.video import (
    VideoPlaybackEvent,
    VideoPresentationSampling,
)
from substitute.presentation.canvas.output.video_playback_controller import (
    VideoPlaybackController,
    VideoViewportMode,
)
from tests.support.qt.lifecycle import ensure_qt_application
from tests.support.qt.semantic_wait import wait_for_qt_signal
from tests.support.video_playback_controller import FakeVideoPlayer, playback_snapshot


@pytest.mark.parametrize("pixel_ratio", [1.0, 2.0])
def test_actual_size_tracks_rotated_display_geometry_and_later_changes(
    tmp_path: Path, pixel_ratio: float
) -> None:
    """Keep display pixels physically 1:1 when the output aspect changes."""

    ensure_qt_application()
    players: list[FakeVideoPlayer] = []

    def create(callback: Callable[[VideoPlaybackEvent], None]) -> FakeVideoPlayer:
        """Capture commands at the external native player boundary."""

        player = FakeVideoPlayer(callback)
        players.append(player)
        return player

    controller = VideoPlaybackController(player_factory=create)
    media_id = uuid4()
    path = tmp_path / "rotated.mp4"
    path.write_bytes(b"video")
    try:
        controller.set_surface_metrics(
            width=643, height=573, device_pixel_ratio=pixel_ratio
        )
        controller.activate(media_id, path)
        changed = QSignalSpy(controller.snapshotChanged)
        players[0].emit(replace(playback_snapshot(media_id), width=90, height=160))
        wait_for_qt_signal(changed, timeout_ms=1000)
        controller.set_actual_size_viewport(
            surface_width=643,
            surface_height=573,
            device_pixel_ratio=pixel_ratio,
        )
        actual = controller.session_for(media_id)
        assert actual.viewport_mode is VideoViewportMode.ACTUAL_SIZE
        assert actual.zoom == pytest.approx(160 / (573 * pixel_ratio))
        assert players[0].commands[-1][-1] is VideoPresentationSampling.BILINEAR
        assert players[0].actual_size_mode

        changed = QSignalSpy(controller.snapshotChanged)
        players[0].emit(replace(playback_snapshot(media_id), width=320, height=180))
        wait_for_qt_signal(changed, timeout_ms=1000)
        resized = controller.session_for(media_id)
        assert resized.viewport_mode is VideoViewportMode.ACTUAL_SIZE
        assert resized.zoom == pytest.approx(320 / (643 * pixel_ratio))
        assert players[0].commands[-1][-1] is VideoPresentationSampling.BILINEAR

        controller.reset_viewport()
        assert controller.session_for(media_id).zoom == 1.0
        assert controller.session_for(media_id).viewport_mode is VideoViewportMode.FIT
        assert not players[0].actual_size_mode
    finally:
        controller.close()


def test_actual_size_clamps_retained_pan_when_display_shrinks(tmp_path: Path) -> None:
    """Keep a newly smaller frame visible after a previously anchored zoom."""

    ensure_qt_application()
    players: list[FakeVideoPlayer] = []

    def create(callback: Callable[[VideoPlaybackEvent], None]) -> FakeVideoPlayer:
        """Record native viewport commands for the real controller."""

        player = FakeVideoPlayer(callback)
        players.append(player)
        return player

    controller = VideoPlaybackController(player_factory=create)
    media_id = uuid4()
    path = tmp_path / "changing.mp4"
    path.write_bytes(b"video")
    try:
        controller.set_surface_metrics(width=80, height=45, device_pixel_ratio=1.0)
        controller.activate(media_id, path)
        changed = QSignalSpy(controller.snapshotChanged)
        players[0].emit(playback_snapshot(media_id))
        wait_for_qt_signal(changed, timeout_ms=1000)
        controller.set_actual_size_viewport(
            surface_width=80,
            surface_height=45,
            device_pixel_ratio=1.0,
            anchor_x=0.75,
            anchor_y=-0.75,
        )
        anchored = controller.session_for(media_id)
        assert (anchored.zoom, anchored.pan_x, anchored.pan_y) == (4.0, -2.25, 2.25)

        changed = QSignalSpy(controller.snapshotChanged)
        players[0].emit(replace(playback_snapshot(media_id), width=64, height=36))
        wait_for_qt_signal(changed, timeout_ms=1000)
        smaller = controller.session_for(media_id)
        assert (smaller.zoom, smaller.pan_x, smaller.pan_y) == (0.8, 0.0, 0.0)
        assert players[0].commands[-1] == (
            "viewport",
            0.8,
            0.0,
            0.0,
            VideoPresentationSampling.BILINEAR,
        )
    finally:
        controller.close()
