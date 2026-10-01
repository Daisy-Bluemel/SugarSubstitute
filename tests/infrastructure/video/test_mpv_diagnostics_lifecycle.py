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

"""Characterize native diagnostics lifetime separately from playback control."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from substitute.application.ports.video import (
    VideoPlaybackFallback,
    VideoPresentationSampling,
)
from substitute.domain.generation import VideoHardwareDecoding, VideoPlaybackSettings
from tests.support.mpv_video_player import create_video_player


def test_new_media_resets_decode_facts_and_retains_player_render_facts(
    tmp_path: Path,
) -> None:
    """Avoid stale codec/hardware claims while retaining the existing renderer."""

    player, native, _events, video = create_video_player(
        tmp_path,
        render_api=True,
        settings=VideoPlaybackSettings(hardware_decoding=VideoHardwareDecoding.AUTO),
    )
    try:
        player.load(uuid4(), video)
        for name, value in {
            "current-vo": "libmpv",
            "gpu-api": "opengl",
            "gpu-context": "x11",
            "hwdec-current": "vaapi",
            "video-codec": "h264",
            "video-params/pixelformat": "yuv420p",
        }.items():
            native.emit(name, value)
        player.set_viewport(2.0, 0.0, 0.0, VideoPresentationSampling.NEAREST)
        player.poll_playback_state()
        before = player.snapshot().diagnostics
        assert (before.codec, before.pixel_format, before.hardware_decoder) == (
            "h264",
            "yuv420p",
            "vaapi",
        )
        assert before.fallback is None

        player.load(uuid4(), video)
        pending = player.snapshot().diagnostics
        assert (pending.codec, pending.pixel_format, pending.hardware_decoder) == (
            None,
            None,
            None,
        )
        assert pending.fallback is None
        assert (pending.actual_video_output, pending.gpu_api, pending.gpu_context) == (
            "libmpv",
            "opengl",
            "x11",
        )
        assert pending.presentation_sampling is VideoPresentationSampling.NEAREST
        native.emit("hwdec-current", None)
        player.poll_playback_state()
        assert (
            player.snapshot().diagnostics.fallback
            is VideoPlaybackFallback.SOFTWARE_DECODING
        )
    finally:
        player.close()


def test_previous_media_observations_cannot_replace_reset_diagnostics(
    tmp_path: Path,
) -> None:
    """Preserve generation/path ownership for diagnostic observations."""

    player, native, _events, video = create_video_player(tmp_path)
    other = tmp_path / "other.mp4"
    other.write_bytes(b"video")
    try:
        player.load(uuid4(), video)
        native.emit("video-codec", "h264")
        player.poll_playback_state()
        player.load(uuid4(), other)
        native.emit("path", str(video.resolve()))
        native.emit("video-codec", "wrong-file-codec")
        player.poll_playback_state()
        assert player.snapshot().diagnostics.codec is None
        native.emit("path", str(other.resolve()))
        native.emit("video-codec", "vp9")
        player.poll_playback_state()
        assert player.snapshot().diagnostics.codec == "vp9"
    finally:
        player.close()


def test_malformed_native_diagnostic_values_become_unknown(tmp_path: Path) -> None:
    """Keep non-string external properties out of support diagnostics."""

    player, native, _events, video = create_video_player(tmp_path)
    try:
        player.load(uuid4(), video)
        for name, value in {
            "current-vo": False,
            "gpu-api": 42,
            "gpu-context": {},
            "hwdec-current": [],
            "video-codec": "",
            "video-params/pixelformat": None,
        }.items():
            native.emit(name, value)
        player.poll_playback_state()
        facts = player.snapshot().diagnostics
        assert (
            facts.actual_video_output,
            facts.gpu_api,
            facts.gpu_context,
            facts.hardware_decoder,
            facts.codec,
            facts.pixel_format,
        ) == (None, None, None, None, None, None)
    finally:
        player.close()
