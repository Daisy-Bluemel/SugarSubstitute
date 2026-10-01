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

"""Decode native libmpv screenshot geometry and detached row-strided pixels."""

from __future__ import annotations

from collections.abc import Mapping

from substitute.application.ports.video import VideoRepresentativeFrame


def decode_mpv_screenshot(
    value: object,
    *,
    time_seconds: float,
) -> VideoRepresentativeFrame:
    """Normalize one python-mpv screenshot node into detached BGR0 bytes."""

    if not isinstance(value, Mapping) or value.get("format") != "bgr0":
        raise ValueError("libmpv returned an unsupported screenshot format")
    width = _positive_integer(value["w"], "width")
    height = _positive_integer(value["h"], "height")
    stride = _positive_integer(value["stride"], "stride")
    pixels = value["data"]
    if not isinstance(pixels, (bytes, bytearray, memoryview)):
        raise TypeError("libmpv screenshot pixels are not bytes")
    return VideoRepresentativeFrame(
        time_seconds=time_seconds,
        width=width,
        height=height,
        stride=stride,
        pixels=bytes(pixels),
    )


def _positive_integer(value: object, label: str) -> int:
    """Return one required positive integer screenshot field."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"libmpv screenshot {label} is not numeric")
    integer = int(value)
    if integer <= 0:
        raise ValueError(f"libmpv screenshot {label} is not positive")
    return integer


__all__ = ["decode_mpv_screenshot"]
