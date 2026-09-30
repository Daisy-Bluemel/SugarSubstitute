"""Keep early splash preference lookup scoped to the launched installation."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from substitute.app.bootstrap import early_launch_splash


@pytest.mark.parametrize(
    "root_source", ["explicit", "environment", "environment_tilde", "source"]
)
def test_direct_launch_passes_the_authoritative_root_to_its_splash_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, root_source: str
) -> None:
    """Carry the root through the real early orchestration up to process creation."""

    app_root = tmp_path / "application"
    environment_root = tmp_path / "environment"
    explicit_root = tmp_path / "explicit"
    arguments = ["main.py"]
    monkeypatch.delenv("SUGAR_SUBSTITUTE_STARTUP_HARNESS", raising=False)
    monkeypatch.delenv("SUGARSUBSTITUTE_INSTALL_ROOT", raising=False)
    expected_root = app_root
    if root_source in {"explicit", "environment"}:
        monkeypatch.setenv("SUGARSUBSTITUTE_INSTALL_ROOT", str(environment_root))
        expected_root = environment_root
    if root_source == "explicit":
        arguments.append(f"--install-root={explicit_root}")
        expected_root = explicit_root
    if root_source == "environment_tilde":
        monkeypatch.setenv("SUGARSUBSTITUTE_INSTALL_ROOT", "~/sugar-root")
        expected_root = Path("~/sugar-root").expanduser()
    captured_commands: list[list[str]] = []

    def capture_process(command: list[str], **_kwargs: object) -> None:
        """Stop at the process boundary after recording the actual host arguments."""

        captured_commands.append(command)
        raise OSError("Controlled test boundary: no process is launched.")

    monkeypatch.setattr(subprocess, "Popen", capture_process)
    splash, relay = early_launch_splash.start_early_launch_splash(
        arguments, app_root, "en"
    )

    assert splash is None and relay is None
    assert len(captured_commands) == 1
    assert f"--install-root={expected_root}" in captured_commands[0]
