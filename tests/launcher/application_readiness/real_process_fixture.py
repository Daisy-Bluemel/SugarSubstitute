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

"""Own bounded real-process lifetimes for readiness relay fixtures."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import socket
import sys

from launcher.sugarsubstitute_launcher.application_readiness_supervisor import (
    ApplicationReadinessSupervisor,
    stop_candidate_process,
)
from launcher.sugarsubstitute_launcher.install_layout import InstallLayout
from launcher.sugarsubstitute_launcher.process_execution import (
    ChildProcess,
    spawn_supervised_process,
)
from sugarsubstitute_shared.application_readiness import (
    ApplicationReadinessReceipt,
    ApplicationReadinessSurface,
    READINESS_PATH_ENV,
    READINESS_TOKEN_ENV,
    publish_application_readiness_receipt,
)


class ReadinessProcessFixture:
    """Hold real children until the test releases them and own failure cleanup."""

    def __init__(self, root: Path, listener: socket.socket, cleanup: ExitStack) -> None:
        """Retain one test's log namespace and release listener."""
        self._root = root
        self._listener = listener
        self._cleanup = cleanup
        self._launch_count = 0

    @property
    def environment(self) -> dict[str, str]:
        """Expose only the ephemeral local release endpoint to each child."""
        return {"TEST_RELEASE_PORT": str(self._listener.getsockname()[1])}

    @staticmethod
    def command() -> list[str]:
        """Execute the receipt writer with the active repository interpreter."""
        return [
            sys.executable,
            "-c",
            "from tests.launcher.application_readiness.real_process_fixture "
            "import publish_and_wait; publish_and_wait()",
        ]

    def start(
        self,
        command: Sequence[str],
        environment: Mapping[str, str],
    ) -> tuple[ChildProcess, Path]:
        """Use the production spawn boundary with private logs and immediate cleanup."""
        self._launch_count += 1
        process, log_path = spawn_supervised_process(
            command,
            environment=environment,
            startup_log_path=self._root / f"candidate-{self._launch_count}.log",
            allow_handoff=True,
        )
        self._cleanup.callback(stop_candidate_process, process)
        return process, log_path

    def release(self, process: ChildProcess) -> None:
        """Acknowledge the child's held state, release it and prove normal exit."""
        connection, _address = self._listener.accept()
        with connection:
            connection.settimeout(15)
            assert connection.recv(1) == b"R"
            connection.shutdown(socket.SHUT_RDWR)
        assert process.wait(timeout=5) == 0


@contextmanager
def readiness_process_fixture(root: Path) -> Iterator[ReadinessProcessFixture]:
    """Keep release and child ownership scoped even when a receipt assertion fails."""
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener,
        ExitStack() as cleanup,
    ):
        listener.settimeout(15)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        yield ReadinessProcessFixture(root, listener, cleanup)


def publish_and_wait() -> None:
    """Publish a real receipt and wait for release or loss of the supervising peer."""
    port = int(os.environ["TEST_RELEASE_PORT"])
    with socket.create_connection(("127.0.0.1", port), timeout=15) as connection:
        Path(os.environ["TEST_PID_PATH"]).write_text(str(os.getpid()), encoding="utf-8")
        publish_application_readiness_receipt(
            receipt_path=Path(os.environ[READINESS_PATH_ENV]),
            receipt=ApplicationReadinessReceipt(
                pid=os.getpid(),
                parent_pid=os.getppid(),
                token=os.environ[READINESS_TOKEN_ENV],
                surface=ApplicationReadinessSurface(os.environ["TEST_SURFACE"]),
            ),
        )
        connection.sendall(b"R")
        connection.recv(1)


def run_legacy_launcher() -> None:
    """Relay an unadvertised schema-3 outer through the current real supervisor."""
    layout = InstallLayout.from_root(Path(os.environ["TEST_INSTALL_ROOT"]))
    with readiness_process_fixture(layout.root) as fixture:
        process = ApplicationReadinessSupervisor(
            timeout_seconds=10,
            process_starter=fixture.start,
        ).launch_until_ready(
            layout=layout,
            command=fixture.command(),
            environment={
                **os.environ,
                **fixture.environment,
                "TEST_SURFACE": ApplicationReadinessSurface.MAIN_SHELL.value,
                "TEST_PID_PATH": str(layout.root / "app.pid"),
            },
        )
        fixture.release(process)
