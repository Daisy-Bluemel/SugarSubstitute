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

"""Describe observed Comfy startup operations without treating logs as readiness."""

from __future__ import annotations

import re
from dataclasses import dataclass
from sugarsubstitute_shared.localization import ApplicationText, app_text

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass(frozen=True, slots=True)
class ComfyStartupObservation:
    """Pair localized console meaning with optional estimated-work evidence."""

    text: ApplicationText
    milestone: str | None = None


def describe_comfy_startup_output(record: str) -> ApplicationText | None:
    """Render the same semantic observation used by startup estimation."""
    observation = observe_comfy_startup_output(record)
    return None if observation is None else observation.text


def observe_comfy_startup_output(record: str) -> ComfyStartupObservation | None:
    """Translate recognized upstream markers; leave unknown output in diagnostics.

    These messages describe observed activity only. The readiness probe remains
    authoritative, including after Comfy prints its server URL.
    """
    line = _ANSI.sub("", record).strip()
    if line.startswith("[INFO] "):
        line = line[7:]
    if line.startswith(("Adding extra search path ", "Setting models directory to:")):
        return ComfyStartupObservation(app_text("Configuring ComfyUI model folders."))
    if line.startswith("[START] Security scan"):
        return ComfyStartupObservation(app_text("Checking ComfyUI extensions."))
    if line.startswith("[ComfyUI-Manager] Starting dependency installation"):
        return ComfyStartupObservation(app_text("Preparing custom-node dependencies."))
    if line.startswith("Install: pip packages for "):
        return ComfyStartupObservation(
            app_text(
                "Installing dependencies for %1.",
                _extension_name(line.removeprefix("Install: pip packages for ")),
            )
        )
    for prefix in ("Install: install script for ", "## Execute management script for "):
        if line.startswith(prefix):
            return ComfyStartupObservation(
                app_text("Running setup for %1.", _extension_name(line[len(prefix) :]))
            )
    if line.startswith(
        "[ComfyUI-Manager] Restarting to reapply dependency installation."
    ):
        return ComfyStartupObservation(
            app_text("Restarting ComfyUI to apply updated dependencies."),
            "backend.restart",
        )
    if line.startswith(
        (
            "[DONE] Security scan",
            "Prestartup times for custom nodes:",
            "[ComfyUI-Manager] Startup script completed.",
            "Checkpoint files will always be loaded safely.",
        )
    ):
        return ComfyStartupObservation(
            app_text("Loading the ComfyUI runtime."), "backend.runtime"
        )
    if line.startswith(
        ("Total VRAM ", "pytorch version:", "Set vram state to:", "Device:")
    ):
        return ComfyStartupObservation(
            app_text("Preparing ComfyUI's compute device."), "backend.device"
        )
    if line.startswith("Using ") and "attention" in line.lower():
        return ComfyStartupObservation(app_text("Configuring ComfyUI attention."))
    for prefix in (
        "### Loading:",
        "Trying to load custom node ",
        "Importing custom node ",
    ):
        if line.startswith(prefix):
            name = _extension_name(line[len(prefix) :])
            if name:
                return ComfyStartupObservation(
                    app_text("Loading custom node: %1.", name)
                )
    if line.startswith("[Prompt Server] web root:"):
        return ComfyStartupObservation(
            app_text("Loading ComfyUI custom nodes."), "backend.custom_nodes"
        )
    if line.startswith("Import times for custom nodes:"):
        return ComfyStartupObservation(
            app_text("Finishing ComfyUI custom node loading."),
            "backend.imports_complete",
        )
    imported = re.fullmatch(r"[0-9]+\.[0-9]+ seconds( \(IMPORT FAILED\))?: (.+)", line)
    if imported and "custom_nodes/" in imported[2].replace("\\", "/"):
        name = _extension_name(imported[2])
        if imported[1]:
            return ComfyStartupObservation(
                app_text("Custom node %1 could not load.", name)
            )
        return ComfyStartupObservation(app_text("Loaded custom node: %1.", name))
    if line.startswith(
        ("Context impl SQLiteImpl.", "Running upgrade ", "Database upgraded from ")
    ):
        return ComfyStartupObservation(app_text("Preparing the ComfyUI database."))
    if line.startswith("Background asset scan initiated"):
        return ComfyStartupObservation(app_text("Scanning ComfyUI models and assets."))
    if line == "Starting server":
        return ComfyStartupObservation(
            app_text("Starting the ComfyUI server."), "backend.server"
        )
    if line.startswith("To see the GUI go to:"):
        return ComfyStartupObservation(
            app_text("Connecting to ComfyUI."), "backend.connecting"
        )
    fetched = re.fullmatch(r"FETCH ComfyRegistry Data: (\d+)/(\d+)", line)
    if fetched and 0 <= int(fetched[1]) <= int(fetched[2]) and int(fetched[2]) > 0:
        return ComfyStartupObservation(
            app_text(
                "Updating the ComfyUI extension catalog (%1/%2).",
                int(fetched[1]),
                int(fetched[2]),
            )
        )
    if line.startswith(
        ("FETCH ComfyRegistry Data", "[ComfyUI-Manager] default cache updated:")
    ):
        return ComfyStartupObservation(
            app_text("Updating the ComfyUI extension catalog.")
        )
    if line == "[ComfyUI-Manager] All startup tasks have been completed.":
        return ComfyStartupObservation(app_text("ComfyUI extension setup is complete."))
    return None


def _extension_name(value: str) -> str:
    """Keep extension identity while omitting machine-specific parent directories."""
    return value.strip().strip("\"'").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
