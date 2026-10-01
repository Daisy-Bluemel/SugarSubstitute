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

"""Verify lazy optional module loading without traversing native Photoshop state."""

from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType, TracebackType

import pytest

from substitute.infrastructure.external.photoshop_gateway import PhotoshopGateway
from substitute.infrastructure.external.photoshop_session import load_photoshop_session

from .support import Host, Image, install_session, metadata


def test_module_resolution_returns_the_original_constructor_without_entering_com(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolving the optional module must not construct, enter, or probe a session."""
    host = Host()
    constructor = host.session
    install_session(monkeypatch, constructor)

    resolved = load_photoshop_session()

    assert id(resolved) == id(constructor)
    assert host.events == []
    with resolved():
        assert host.events == ["construct", "enter"]
    assert host.events == ["construct", "enter", "exit"]


@pytest.mark.parametrize("export", [None, 42, object()])
def test_module_resolution_rejects_a_non_callable_export(
    monkeypatch: pytest.MonkeyPatch, export: object
) -> None:
    """The typed constructor boundary must not return a malformed vendor export."""
    install_session(monkeypatch, export)
    with pytest.raises(TypeError, match="callable Session"):
        load_photoshop_session()


def test_module_resolution_propagates_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gateway must remain responsible for the unavailable integration outcome."""
    monkeypatch.setitem(sys.modules, "photoshop", None)
    with pytest.raises(ImportError):
        load_photoshop_session()


def test_module_resolution_rejects_missing_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incomplete module cannot satisfy the lazy typed dependency contract."""
    monkeypatch.setitem(sys.modules, "photoshop", ModuleType("photoshop"))
    with pytest.raises(TypeError, match="callable Session"):
        load_photoshop_session()


def test_live_application_property_failure_stays_inside_context_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """COM properties must be read during export, with the context already entered."""
    events: list[str] = []

    class NativeSession:
        """Expose a failing native property only after the real context boundary."""

        def __init__(self) -> None:
            """Record native construction."""
            events.append("construct")

        def __enter__(self) -> NativeSession:
            """Record entry before exposing native state."""
            events.append("enter")
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            """Require the native property exception to reach ordinary cleanup."""
            assert exc_type is RuntimeError
            events.append("exit")

        @property
        def app(self) -> object:
            """Fail at an actual operation rather than dependency validation."""
            events.append("app")
            raise RuntimeError("native application unavailable")

    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    install_session(monkeypatch, NativeSession)

    assert not PhotoshopGateway().open_image(image=Image(), image_meta=metadata(source))
    assert events == ["construct", "enter", "app", "exit"]
