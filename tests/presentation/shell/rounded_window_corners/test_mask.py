"""Exercise Linux corner regions through real QWidget lifecycle events."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QWidget
import pytest

import substitute.presentation.shell.rounded_window_corners as corners
from tests.support.qt.lifecycle import destroy_qt_object


@pytest.fixture
def linux_corner_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select the Linux policy without changing the platform's actual Qt implementation."""

    monkeypatch.setattr(corners, "_PLATFORM", "linux")


def test_restored_region_tracks_resize_and_keeps_eight_dip_corner_radius(
    linux_corner_policy: None,
) -> None:
    """Clip both restored sizes while keeping the same logical-pixel corner curve."""

    window = QWidget()
    window.resize(120, 80)
    owner = corners.RoundedWindowCorners(window)
    try:
        first_mask = window.mask()
        assert owner.parent() is window
        assert first_mask.boundingRect() == window.rect()
        assert not first_mask.contains(QPoint(0, 0))
        assert first_mask.contains(QPoint(8, 0))
        window.show()
        window.resize(240, 160)
        resized_mask = window.mask()
        assert resized_mask.boundingRect() == window.rect()
        assert not resized_mask.contains(window.rect().bottomRight())
        for x in range(12):
            for y in range(12):
                point = QPoint(x, y)
                assert first_mask.contains(point) == resized_mask.contains(point)
    finally:
        destroy_qt_object(window)


@pytest.mark.parametrize(
    "state", [Qt.WindowState.WindowMaximized, Qt.WindowState.WindowFullScreen]
)
def test_screen_filling_windows_clear_the_mask_and_restore_rounded_corners(
    linux_corner_policy: None, state: Qt.WindowState
) -> None:
    """Avoid cut-out screen corners while maximized/fullscreen and restore on return."""

    window = QWidget()
    window.resize(120, 80)
    corners.RoundedWindowCorners(window)
    try:
        restored_mask = window.mask()
        assert not restored_mask.isEmpty()
        window.setWindowState(state)
        assert window.mask().isEmpty()
        window.setWindowState(Qt.WindowState.WindowNoState)
        assert window.mask() == restored_mask
    finally:
        destroy_qt_object(window)


def test_show_and_surface_creation_restore_the_owned_mask(
    linux_corner_policy: None,
) -> None:
    """Reapply clipping after toolkit/native surface recreation discards a mask."""

    window = QWidget()
    window.resize(120, 80)
    corners.RoundedWindowCorners(window)
    try:
        expected_mask = window.mask()
        window.clearMask()
        window.show()
        assert window.mask() == expected_mask
        window.clearMask()
        surface = window.windowHandle()
        assert surface is not None
        surface.destroy()
        surface.create()
        assert window.mask() == expected_mask
    finally:
        destroy_qt_object(window)


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_native_platforms_keep_their_existing_corner_policy(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    """Leave native platform window masks untouched through show and resizing."""

    monkeypatch.setattr(corners, "_PLATFORM", platform)
    window = QWidget()
    window.resize(120, 80)
    existing_mask = QRegion(QRect(2, 2, 100, 60))
    window.setMask(existing_mask)
    corners.RoundedWindowCorners(window)
    try:
        window.show()
        window.resize(240, 160)
        assert window.mask() == existing_mask
    finally:
        destroy_qt_object(window)
