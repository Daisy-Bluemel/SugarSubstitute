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

"""Protect application support-runtime distribution selection across platforms."""

from __future__ import annotations

import pytest

from sugarsubstitute_shared.app_runtime_torch import app_runtime_torch_policy


def test_linux_app_support_runtime_uses_the_official_cpu_wheel_index() -> None:
    """Linux UI support must not provision an inference GPU toolkit."""
    policy = app_runtime_torch_policy("Linux")
    assert policy is not None
    assert policy.backend == "cpu"
    assert policy.index_url == "https://download.pytorch.org/whl/cpu"
    assert policy.packages == ("torch", "torchvision")


@pytest.mark.parametrize("system", ["Windows", "Darwin", "macos", "win32"])
def test_other_systems_keep_their_existing_package_selection(system: str) -> None:
    """Non-Linux launchers and source installs retain their current resolver policy."""
    assert app_runtime_torch_policy(system) is None
