"""Verify the real estimate adapter retains transport and readiness guarantees."""

from contextlib import nullcontext

from substitute.app.bootstrap.launch_splash_client import NullLaunchSplashClient
from substitute.app.bootstrap.startup_estimate_splash import (
    StartupEstimateSplashClient,
    adopt_startup_estimate,
    observe_backend_ready_phase,
    observe_backend_restart_phase,
    observe_hidden_restore_runtime_prepared,
    report_startup_milestone,
)
from sugarsubstitute_shared.launch_splash.progress import SplashProgress


class RecordingClient(NullLaunchSplashClient):
    """Record the external splash boundary while running the real estimate owner."""

    def __init__(self) -> None:
        """Initialize observable transport records."""
        self.progress: list[SplashProgress] = []
        self.logs: list[str] = []
        self.close_result = True

    def set_progress(self, progress: SplashProgress, *, status: str) -> None:
        """Retain the emitted units."""
        self.progress.append(progress)

    def append_log(self, line: str) -> None:
        """Retain unmodified upstream console lines."""
        self.logs.append(line)

    def close(self) -> bool:
        """Return the chosen native acknowledgement."""
        return self.close_result


def test_semantic_logs_advance_but_catalog_and_duplicates_do_not() -> None:
    """Interpret known ANSI markers while retaining optional catalog diagnostics."""
    transport = RecordingClient()
    client = StartupEstimateSplashClient(transport)
    client.observe_startup("gui.prepare_main_window")
    output = client.bind_backend_output()
    before = client.estimate.progress
    output("\x1b[32m[INFO]\x1b[0m Total VRAM 100 MB")
    assert client.estimate.progress.completed > before.completed
    before = client.estimate.progress
    for line in (
        "Device: cpu",
        "FETCH ComfyRegistry Data: 9/10",
        "FETCH ComfyRegistry Data: 10/20",
        "FETCH ComfyRegistry Data: 20/20",
        "[ComfyUI-Manager] All startup tasks have been completed.",
        "unknown",
    ):
        output(line)
        client.append_log(line)
    assert client.estimate.progress == before
    output("To see the GUI go to: http://localhost:8188")
    client.append_log("To see the GUI go to: http://localhost:8188")
    assert client.estimate.progress.completed < 10000
    with observe_backend_ready_phase(client, nullcontext()):
        assert client.estimate.remaining_ms > 0
    assert client.estimate.progress.completed < 10000
    assert transport.logs[-1].startswith("To see the GUI")


def test_close_acknowledgement_adoption_and_painted_completion() -> None:
    """Failed close keeps the client live; successful close does not mean ready."""
    transport = RecordingClient()
    client = StartupEstimateSplashClient(transport)
    assert adopt_startup_estimate(client) is client
    transport.close_result = False
    assert client.close() is False
    client.observe_startup("gui.prepare_main_window")
    assert transport.progress
    transport.close_result = True
    assert client.close() is True
    count = len(transport.progress)
    client.append_log("Starting server")
    client.observe_startup("shell.reveal")
    assert len(transport.progress) == count
    assert not transport.logs
    assert client.estimate.progress.completed < 10000
    client.observe_startup("shell.painted")
    assert client.estimate.progress.completed == 10000
    assert len(transport.progress) == count


def test_missing_or_failed_optional_estimate_cannot_abort_startup() -> None:
    """Keep estimate failures isolated from authoritative application readiness."""

    class BrokenReporter:
        """Fail optional progress presentation."""

        def observe_startup(self, milestone: str, *, status: str | None = None) -> None:
            """Simulate a disappeared optional feedback surface."""
            raise RuntimeError("gone")

    report_startup_milestone(object(), "backend.ready")
    report_startup_milestone(BrokenReporter(), "backend.ready")


def test_app_recovery_relaunch_rebases_remaining_backend_work() -> None:
    """Reset old backend evidence even when Manager emits no restart marker."""
    client = StartupEstimateSplashClient(RecordingClient())
    client.observe_startup("gui.prepare_main_window")
    output = client.bind_backend_output()
    output("To see the GUI go to: http://localhost:8188")
    client.append_log("To see the GUI go to: http://localhost:8188")
    before = client.estimate.progress
    remaining = client.estimate.remaining_ms
    with observe_backend_restart_phase(client, nullcontext()):
        assert client.estimate.progress == before
        assert client.estimate.remaining_ms > remaining
    output("To see the GUI go to: http://stale:8188")
    assert client.estimate.progress == before
    new_output = client.bind_backend_output()
    new_output("Device: cpu")
    assert before.completed < client.estimate.progress.completed < 10000


def test_backend_ready_does_not_credit_later_restored_runtime_work() -> None:
    """Keep workspace allocation outstanding until the real preparation callback."""
    client = StartupEstimateSplashClient(RecordingClient())
    client.observe_startup("gui.prepare_main_window")
    client.observe_startup("backend.connecting")
    with observe_backend_ready_phase(client, nullcontext()):
        after_http = client.estimate.progress
    assert client.estimate.progress == after_http
    assert after_http.completed < 8000
    states: list[bool] = []
    observe_hidden_restore_runtime_prepared(client, states.append, True)
    assert states == [True]
    assert after_http.completed < client.estimate.progress.completed < 10000
