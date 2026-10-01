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

"""Verify installed-candidate spawning at the host's native process boundary."""

from __future__ import annotations

from io import BufferedWriter
import os
from pathlib import Path
import subprocess

import pytest

from launcher.sugarsubstitute_launcher.install_layout import InstallLayout
from tools.ci.installer_ui_qualification import (
    InstalledCandidateLaunch,
    launch_installed_candidate,
)


def test_installed_candidate_launch_is_observed_without_capture_bound_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Updater qualification should observe a process while evidence arrives."""

    install_root = tmp_path / "installed"
    layout = InstallLayout.from_root(install_root)
    layout.root.mkdir(parents=True)
    observed: dict[str, object] = {}

    class CandidateProcess:
        """Expose the nonblocking observation contract without a wait method."""

        pid = 123

        def poll(self) -> int | None:
            """Retain a live candidate while asynchronous evidence is collected."""
            return None

    fake_process = CandidateProcess()

    def _start(command: list[str], **kwargs: object) -> CandidateProcess:
        """Capture the process contract without starting an executable."""

        observed["command"] = command
        observed.update(kwargs)
        if os.name != "nt":
            output = kwargs["stdout"]
            assert isinstance(output, BufferedWriter)
            output.write(b"candidate startup\n")
        return fake_process

    spawn_boundary = (
        "tools.ci.installer_ui_qualification.start_windows_desktop_process"
        if os.name == "nt"
        else "tools.ci.installer_ui_qualification.subprocess.Popen"
    )
    monkeypatch.setattr(spawn_boundary, _start)

    launch = launch_installed_candidate(
        install_root=install_root,
        environment={
            "QUALIFICATION": "1",
            "SSL_CERT_FILE": "candidate-ca.pem",
            "PYTHONHOME": "hosted-python",
            "PYTHONPATH": "hosted-packages",
            "LD_LIBRARY_PATH": "hosted-python/lib",
            "LD_LIBRARY_PATH_ORIG": "system/lib",
            "DYLD_LIBRARY_PATH": "hosted-python/lib",
            "DYLD_FRAMEWORK_PATH": "hosted-python/frameworks",
            "QT_PLUGIN_PATH": "hosted-qt/plugins",
            "QML2_IMPORT_PATH": "hosted-qt/qml",
            "_PYI_ARCHIVE_FILE": "unrelated-frozen-parent",
        },
    )

    assert isinstance(launch, InstalledCandidateLaunch)
    assert launch.process is fake_process
    assert observed["command"] == [str(layout.executable_path)]
    assert observed["cwd"] == layout.root
    environment_argument = "environment" if os.name == "nt" else "env"
    assert observed[environment_argument] == {
        "QUALIFICATION": "1",
        "SSL_CERT_FILE": "candidate-ca.pem",
    }
    if os.name == "nt":
        assert set(observed) == {"command", "cwd", "environment"}
        assert launch.output_path.read_bytes() == b""
    else:
        assert set(observed) == {
            "command",
            "cwd",
            "env",
            "stdin",
            "stdout",
            "stderr",
            "close_fds",
            "start_new_session",
        }
        assert observed["stdin"] == subprocess.DEVNULL
        assert observed["close_fds"] is True
        assert observed["start_new_session"] is True
        output = observed["stdout"]
        assert isinstance(output, BufferedWriter)
        assert observed["stderr"] is output
        assert output.closed
        assert launch.output_path.read_bytes() == b"candidate startup\n"
