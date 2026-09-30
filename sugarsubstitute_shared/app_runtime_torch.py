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

"""Own Torch distribution selection for the application support runtime."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AppRuntimeTorchPolicy:
    """Describe the app's support dependencies independently of ComfyUI inference."""

    backend: str
    index_url: str
    packages: tuple[str, ...]


def app_runtime_torch_policy(system: str) -> AppRuntimeTorchPolicy | None:
    """Keep Linux app support on CPU while retaining other platform defaults."""
    if system.casefold() == "linux":
        return AppRuntimeTorchPolicy(
            backend="cpu",
            index_url="https://download.pytorch.org/whl/cpu",
            packages=("torch", "torchvision"),
        )
    return None
