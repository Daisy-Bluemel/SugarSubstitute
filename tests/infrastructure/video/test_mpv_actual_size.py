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

"""Verify exact native Actual Size policy avoids inverse-fit rounding."""

from __future__ import annotations

from math import log2
from pathlib import Path
from uuid import uuid4

import pytest

from substitute.application.ports.video import VideoPresentationSampling
from tests.support.mpv_video_player import create_video_player


@pytest.mark.parametrize("fit_relative_zoom", [160 / 573, 90 / 643, 4.0])
def test_actual_size_uses_native_unscaled_display_pixels(
    tmp_path: Path, fit_relative_zoom: float
) -> None:
    """Delegate exact size to mpv instead of scaling an integer fitted rectangle."""

    player, native, _events, video = create_video_player(tmp_path)
    try:
        player.load(uuid4(), video)
        player.set_viewport(
            fit_relative_zoom,
            0.1,
            -0.2,
            VideoPresentationSampling.BILINEAR,
            actual_size=True,
        )
        assert native.video_unscaled == "yes"
        assert native.video_zoom == 0.0
        assert native.video_pan_x == 0.1
        assert native.video_pan_y == -0.2
        assert native.scale == "bilinear"
    finally:
        player.close()


def test_fit_custom_and_new_media_restore_scaled_native_policy(tmp_path: Path) -> None:
    """Avoid leaking one video's Actual Size mode into another presentation."""

    player, native, _events, video = create_video_player(tmp_path)
    try:
        player.load(uuid4(), video)
        player.set_viewport(
            160 / 573, 0.0, 0.0, VideoPresentationSampling.BILINEAR, actual_size=True
        )
        player.set_viewport(2.0, 0.25, -0.25, VideoPresentationSampling.NEAREST)
        assert native.video_unscaled == "no"
        assert native.video_zoom == log2(2.0)
        assert native.scale == "nearest"
        player.set_viewport(
            160 / 573, 0.1, -0.2, VideoPresentationSampling.BILINEAR, actual_size=True
        )
        player.load(uuid4(), video)
        assert native.video_unscaled == "no"
        assert native.video_zoom == 0.0
        assert native.video_pan_x == native.video_pan_y == 0.0
    finally:
        player.close()
