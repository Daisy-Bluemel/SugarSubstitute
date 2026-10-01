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

"""Own native support facts and their player-versus-media diagnostic lifetime."""

from substitute.application.ports.video import (
    VideoPlaybackDiagnostics,
    VideoPresentationSampling,
)
from substitute.domain.generation import VideoPlaybackSettings
from substitute.infrastructure.video.mpv_observation_values import optional_string
from substitute.infrastructure.video.mpv_playback_fallback import playback_fallback


class MpvPlaybackDiagnosticsState:
    """Retain observed renderer facts while resetting decoder facts per media."""

    def __init__(self, *, settings: VideoPlaybackSettings, render_api: bool) -> None:
        """Start with requested policy and no observed native capabilities."""

        self._settings = settings
        self._render_api = render_api
        self._actual_video_output: str | None = None
        self._gpu_api: str | None = None
        self._gpu_context: str | None = None
        self._hardware_decoder: str | None = None
        self._hardware_decoder_observed = False
        self._pixel_format: str | None = None
        self._codec: str | None = None
        self._presentation_sampling = VideoPresentationSampling.BILINEAR

    def reset_media(self) -> None:
        """Invalidate decoder facts without forgetting the retained renderer."""

        self._hardware_decoder = None
        self._hardware_decoder_observed = False
        self._pixel_format = None
        self._codec = None

    def observe(self, name: str, value: object) -> None:
        """Fold current-media native support facts after the player's identity gate."""

        if name == "current-vo":
            self._actual_video_output = optional_string(value)
        elif name == "gpu-api":
            self._gpu_api = optional_string(value)
        elif name == "gpu-context":
            self._gpu_context = optional_string(value)
        elif name == "hwdec-current":
            self._hardware_decoder_observed = True
            self._hardware_decoder = optional_string(value)
        elif name == "video-params/pixelformat":
            self._pixel_format = optional_string(value)
        elif name == "video-codec":
            self._codec = optional_string(value)

    def set_sampling(self, sampling: VideoPresentationSampling) -> None:
        """Record the sampler actually accepted by the viewport adapter."""

        self._presentation_sampling = sampling

    def snapshot(self) -> VideoPlaybackDiagnostics:
        """Project owned facts without claiming an unobserved hardware fallback."""

        return VideoPlaybackDiagnostics(
            requested_hardware_decoding=self._settings.hardware_decoding,
            requested_renderer=self._settings.renderer,
            actual_video_output=self._actual_video_output,
            gpu_api=self._gpu_api,
            gpu_context=self._gpu_context,
            hardware_decoder=self._hardware_decoder,
            pixel_format=self._pixel_format,
            codec=self._codec,
            fallback=playback_fallback(
                settings=self._settings,
                render_api=self._render_api,
                actual_video_output=self._actual_video_output,
                hardware_decoder_observed=self._hardware_decoder_observed,
                hardware_decoder=self._hardware_decoder,
            ),
            presentation_sampling=self._presentation_sampling,
        )


__all__ = ["MpvPlaybackDiagnosticsState"]
