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

"""Prove playback geometry follows the current native display frame."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from tests.support.mpv_video_player import create_video_player


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"dw": 160, "dh": 90, "rotate": 0}, (160, 90)),
        ({"dw": 160, "dh": 90, "rotate": 90}, (90, 160)),
        ({"dw": 160, "dh": 90, "rotate": 180}, (160, 90)),
        ({"dw": 160, "dh": 90, "rotate": 270}, (90, 160)),
        ({"dw": 90, "dh": 160, "rotate": 0}, (90, 160)),
        ({"dw": 1024, "dh": 576, "rotate": 0}, (1024, 576)),
        ({"dw": 1024, "dh": 576, "rotate": 270}, (576, 1024)),
    ],
)
def test_player_publishes_display_dimensions_instead_of_coded_raster(
    tmp_path: Path, params: dict[str, object], expected: tuple[int, int]
) -> None:
    """Apply output aspect/crop and residual rotation exactly once."""

    player, native, _events, video = create_video_player(tmp_path)
    try:
        player.load(uuid4(), video)
        native.emit("width", 160)
        native.emit("height", 90)
        native.emit("video-out-params", {"w": 160, "h": 90, **params})
        native.emit("seeking", False)
        player.poll_playback_state()

        assert (player.snapshot().width, player.snapshot().height) == expected
    finally:
        player.close()


@pytest.mark.parametrize("seeking", [None, True])
@pytest.mark.parametrize("same_path", [False, True])
def test_replacement_waits_for_its_first_frame_before_accepting_retained_geometry(
    tmp_path: Path, seeking: object, same_path: bool
) -> None:
    """Keep old VO dimensions out of a new load, including same-path retries."""

    player, native, _events, video = create_video_player(tmp_path)
    try:
        player.load(uuid4(), video)
        native.emit("video-out-params", {"dw": 160, "dh": 90, "rotate": 270})
        player.poll_playback_state()
        assert (player.snapshot().width, player.snapshot().height) == (90, 160)
        replacement = video if same_path else tmp_path / "replacement.mp4"
        replacement.write_bytes(b"test media")
        player.load(uuid4(), replacement)
        native.emit("seeking", seeking)
        native.emit("core-idle", False)
        native.emit("time-pos", 0.0)
        player.poll_playback_state()
        assert (player.snapshot().width, player.snapshot().height) == (None, None)

        native.emit("video-out-params", {"dw": 768, "dh": 576, "rotate": 0})
        native.emit("seeking", False)
        player.poll_playback_state()
        assert (player.snapshot().width, player.snapshot().height) == (768, 576)
        player.unload()
        assert (player.snapshot().width, player.snapshot().height) == (None, None)
    finally:
        player.close()


@pytest.mark.parametrize("observed_path", [None, "", "other.mp4"])
def test_unknown_or_previous_path_cannot_supply_initial_geometry(
    tmp_path: Path, observed_path: object
) -> None:
    """Require explicit current-file identity even if the VO reports ready."""

    player, native, _events, video = create_video_player(tmp_path)
    try:
        player.load(uuid4(), video)
        native.emit("path", observed_path)
        native.emit("video-out-params", {"dw": 160, "dh": 90, "rotate": 270})
        player.poll_playback_state()
        assert (player.snapshot().width, player.snapshot().height) == (None, None)
        native.emit("path", str(video.resolve()))
        player.poll_playback_state()
        assert (player.snapshot().width, player.snapshot().height) == (90, 160)
    finally:
        player.close()


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "not a node map",
        {},
        {"dw": 160, "dh": 90},
        {"dw": True, "dh": 90, "rotate": 0},
        {"dw": 0, "dh": 90, "rotate": 0},
        {"dw": 160, "dh": -1, "rotate": 0},
        {"dw": 160, "dh": "90", "rotate": 0},
        {"dw": 160.5, "dh": 90, "rotate": 0},
        {"dw": float("nan"), "dh": 90, "rotate": 0},
        {"dw": 160, "dh": float("inf"), "rotate": 0},
        {"dw": 160, "dh": 90, "rotate": False},
        {"dw": 160, "dh": 90, "rotate": 90.0},
        {"dw": 160, "dh": 90, "rotate": 45},
    ],
)
def test_unavailable_display_map_clears_both_dimensions_without_coded_fallback(
    tmp_path: Path, invalid: object
) -> None:
    """Avoid stale or guessed geometry while retaining healthy playback state."""

    player, native, events, video = create_video_player(tmp_path)
    try:
        player.load(uuid4(), video)
        native.emit("width", 160)
        native.emit("height", 90)
        native.emit("video-out-params", {"dw": 160, "dh": 90, "rotate": 270})
        player.poll_playback_state()
        state = player.snapshot().state
        native.emit("video-out-params", invalid)
        player.poll_playback_state()
        snapshot = player.snapshot()
        assert (snapshot.width, snapshot.height) == (None, None)
        assert snapshot.state is state
        assert snapshot.error is None
        count = len(events)
        player.poll_playback_state()
        assert len(events) == count
        native.emit("video-out-params", {"dw": 768, "dh": 576, "rotate": 90})
        player.poll_playback_state()
        assert (player.snapshot().width, player.snapshot().height) == (576, 768)
    finally:
        player.close()


def test_seek_preserves_known_geometry_until_a_current_frame_is_ready(
    tmp_path: Path,
) -> None:
    """Avoid transient VO parameters changing an active viewport during a seek."""

    player, native, events, video = create_video_player(tmp_path)
    try:
        player.load(uuid4(), video)
        native.emit("video-out-params", {"dw": 160, "dh": 90, "rotate": 270})
        player.poll_playback_state()
        native.emit("seeking", True)
        native.emit("video-out-params", None)
        player.poll_playback_state()
        assert (player.snapshot().width, player.snapshot().height) == (90, 160)
        native.emit("video-out-params", {"dw": 768, "dh": 576, "rotate": 0})
        player.poll_playback_state()
        assert (player.snapshot().width, player.snapshot().height) == (90, 160)
        native.emit("seeking", False)
        player.poll_playback_state()
        assert (player.snapshot().width, player.snapshot().height) == (768, 576)
        count = len(events)
        player.poll_playback_state()
        assert len(events) == count
    finally:
        player.close()
