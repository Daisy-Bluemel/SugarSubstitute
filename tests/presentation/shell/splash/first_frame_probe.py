"""Inspect the real splash's first visible paint in an otherwise fresh process."""

from __future__ import annotations

import json
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from shiboken6 import delete


def _prepare_offscreen_cocoa_boundary() -> None:
    """Bypass NSWindow-only adapters because the offscreen test plugin has no NSWindow."""

    if sys.platform != "darwin":
        return
    from qframelesswindow.mac import MacFramelessWindowBase  # type: ignore[import-untyped]
    from qframelesswindow.mac.window_effect import MacWindowEffect  # type: ignore[import-untyped]

    def ignore_native_window_effect(*_args: object, **_kwargs: object) -> None:
        """Leave the absent Cocoa native surface outside this import/rendering probe."""

    setattr(MacWindowEffect, "setAcrylicEffect", ignore_native_window_effect)
    setattr(MacFramelessWindowBase, "updateFrameless", ignore_native_window_effect)
    setattr(
        MacFramelessWindowBase, "_updateSystemTitleBar", ignore_native_window_effect
    )


def main() -> None:
    """Report imports at first paint before queued animation/material enrichment runs."""

    _prepare_offscreen_cocoa_boundary()
    from substitute.presentation.shell.splash_window import SplashWindow

    application = QApplication([])
    application.setQuitOnLastWindowClosed(False)
    splash = SplashWindow(backdrop_mode="mica", defer_animation_until_first_paint=True)
    first_frame_imports: list[str] | None = None

    def capture_first_frame() -> None:
        """Snapshot expensive dependencies at the public first-frame signal boundary."""

        nonlocal first_frame_imports
        prefixes = ("cutemica", "numpy", "PIL", "qfluentwidgets")
        first_frame_imports = sorted(
            name
            for name in sys.modules
            if any(
                name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes
            )
        )
        application.quit()

    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(application.quit)
    splash.firstFramePainted.connect(capture_first_frame)
    try:
        deadline.start(5000)
        splash.show()
        application.exec()
    finally:
        deadline.stop()
        delete(splash)
    assert first_frame_imports is not None, "The splash did not publish a first frame."
    print(json.dumps(first_frame_imports))


if __name__ == "__main__":
    main()
