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

"""Dispose only explicitly owned qualification widgets through Qt's lifecycle."""

from __future__ import annotations

from builtins import ExceptionGroup
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Self, TypeVar

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

_Widget = TypeVar("_Widget", bound=QWidget)


class CaptureWidgetOwner(AbstractContextManager["CaptureWidgetOwner"]):
    """Retain capture-created roots without inspecting unrelated Qt windows."""

    def __init__(self) -> None:
        """Start with no ownership of the process's existing widgets."""

        self._roots: list[QWidget] = []

    def __enter__(self) -> Self:
        """Make explicit ownership available before capture construction starts."""

        return self

    def own(self, widget: _Widget) -> _Widget:
        """Register a newly constructed independent root before fallible setup."""

        self._roots.append(widget)
        return widget

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Synchronously deliver deferred deletion for capture-owned roots only."""

        errors: list[Exception] = []
        roots, self._roots = self._roots, []
        for root in reversed(roots):
            if not isValid(root):
                continue
            try:
                root.close()
            except Exception as error:
                # A failed close must not strand this or another owned root.
                errors.append(error)
            if not isValid(root):
                continue
            try:
                root.deleteLater()
                QCoreApplication.sendPostedEvents(root, QEvent.Type.DeferredDelete)
                if isValid(root):
                    raise RuntimeError(
                        "Qt did not dispose a qualification-owned widget."
                    )
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("Qualification widget disposal failed.", errors)


__all__ = ["CaptureWidgetOwner"]
