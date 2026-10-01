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

"""Characterize optional Photoshop export through controlled external boundaries."""

from __future__ import annotations

from functools import partial
from pathlib import Path
import sys
import tempfile
from types import ModuleType

import pytest

from substitute.infrastructure.external import photoshop_gateway as module
from substitute.infrastructure.external.photoshop_gateway import PhotoshopGateway

from .support import Host, Image, Session, install_session, metadata


@pytest.mark.parametrize("factory_kind", ["class", "callable"])
def test_single_export_preserves_metadata_copy_and_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, factory_kind: str
) -> None:
    """Both supported constructor shapes must preserve the native export contract."""
    source = tmp_path / "existing.png"
    source.write_bytes(b"existing-image")
    host = Host()

    class SessionClass(Session):
        """Provide the actual class-shaped export of the pinned dependency."""

        def __init__(self) -> None:
            """Construct at the same point as the callable boundary variant."""
            host.operation("construct")
            super().__init__(host)

    install_session(
        monkeypatch, SessionClass if factory_kind == "class" else host.session
    )
    image = Image(dots_per_meter=10000)

    assert PhotoshopGateway().open_image(image=image, image_meta=metadata(source))

    document, width, height, dpi, name = host.documents.created[0]
    assert (width, height, dpi, name) == (320, 240, 254.0, "003 Workflow Cube")
    assert [layer.name for layer in document.pasted_layers] == [name]
    assert host.activeDocument is document
    assert [(path, temporary.close_modes) for path, temporary in host.opened] == [
        (str(source), [2])
    ]
    assert host.events == [
        "construct",
        "enter",
        "add",
        "open",
        "select_all",
        "copy",
        "paste",
        "close",
        "exit",
    ]
    assert host.exits == [None]
    assert image.saves == []
    assert source.read_bytes() == b"existing-image"


@pytest.mark.parametrize("number", [-1, 0])
def test_single_export_preserves_empty_name_fallback_and_default_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, number: int
) -> None:
    """Absent labels and DPI must keep existing default naming and resolution."""
    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    host = Host()
    install_session(monkeypatch, host.session)
    meta = metadata(source, cube="", number=number)
    meta.workflow_name = ""

    assert PhotoshopGateway().open_image(image=Image(), image_meta=meta)

    assert host.documents.created[0][3:] == (72.0, "Layer" if number < 0 else "000")


def test_multiple_exports_preserve_canvas_size_input_order_and_layer_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A sequence must preserve source ordering and its existing final index request."""
    source_a, source_b = tmp_path / "a.png", tmp_path / "b.png"
    source_a.write_bytes(b"a")
    source_b.write_bytes(b"b")
    host = Host()
    install_session(monkeypatch, host.session)
    images = [
        (
            Image(width_value=200, height_value=600),
            metadata(source_a, cube="First", number=7),
        ),
        (
            Image(width_value=800, height_value=300, dots_per_meter=10000),
            metadata(source_b, cube=""),
        ),
    ]

    assert PhotoshopGateway().open_images(images=images)

    document, width, height, dpi, name = host.documents.created[0]
    assert (width, height, dpi, name) == (800, 600, 254.0, "007 Workflow")
    assert [path for path, _document in host.opened] == [str(source_a), str(source_b)]
    assert [layer.name for layer in document.pasted_layers] == ["First", "Layer"]
    assert [temporary.close_modes for _path, temporary in host.opened] == [[2], [2]]
    assert document.artLayers.index_requests == [-1]
    assert document.activeLayer is document.artLayers.final_layer
    assert host.exits == [None]


@pytest.mark.parametrize(
    "failure",
    [
        "construct",
        "enter",
        "add",
        "open",
        "select_all",
        "copy",
        "paste",
        "close",
        "exit",
    ],
)
@pytest.mark.parametrize("multiple", [False, True])
def test_external_failure_returns_false_and_respects_context_lifetime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str, multiple: bool
) -> None:
    """Native failures must never become successful exports or suppress cleanup."""
    source = tmp_path / "source.png"
    source.write_bytes(b"unchanged")
    host = Host(fail_at=failure)
    install_session(monkeypatch, host.session)
    gateway = PhotoshopGateway()
    image, meta = Image(), metadata(source)

    result = (
        gateway.open_images(images=[(image, meta)])
        if multiple
        else gateway.open_image(image=image, image_meta=meta)
    )

    assert result is False
    assert failure in host.events
    if failure in {"construct", "enter"}:
        assert host.exits == []
    elif failure == "exit":
        assert host.exits == [None]
    else:
        assert host.exits == [RuntimeError]
    assert source.read_bytes() == b"unchanged"


@pytest.mark.parametrize("export", [None, 42, object()])
def test_unusable_session_export_returns_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, export: object
) -> None:
    """Malformed optional module exports must not escape as successful integration."""
    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    install_session(monkeypatch, export)
    assert not PhotoshopGateway().open_image(image=Image(), image_meta=metadata(source))


def test_non_context_session_result_remains_an_observable_export_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The normal operation error boundary must handle a malformed returned context."""
    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    install_session(monkeypatch, object)
    assert not PhotoshopGateway().open_image(image=Image(), image_meta=metadata(source))


def test_absent_optional_module_fails_before_image_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux without Photoshop must fail closed without constructing export assets."""
    monkeypatch.setitem(sys.modules, "photoshop", None)
    image = Image()
    assert not PhotoshopGateway().open_image(image=image, image_meta=metadata(None))
    assert image.saves == []


def test_missing_session_attribute_fails_before_image_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incomplete dependency must retain the normal unavailable outcome."""
    monkeypatch.setitem(sys.modules, "photoshop", ModuleType("photoshop"))
    image = Image()
    assert not PhotoshopGateway().open_image(image=image, image_meta=metadata(None))
    assert image.saves == []


def test_empty_sequence_does_not_resolve_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty request has no native or dependency side effects."""
    host = Host()
    install_session(monkeypatch, host.session)
    assert not PhotoshopGateway().open_images(images=[])
    assert host.events == []


@pytest.mark.parametrize("width,height", [(0, 240), (320, 0), (-1, 240)])
def test_invalid_single_image_dimensions_never_construct_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, width: int, height: int
) -> None:
    """Invalid source extents must be rejected before native construction."""
    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    host = Host()
    install_session(monkeypatch, host.session)
    assert not PhotoshopGateway().open_image(
        image=Image(width_value=width, height_value=height), image_meta=metadata(source)
    )
    assert host.events == []


@pytest.mark.parametrize("save_result", [False, True])
def test_missing_source_uses_image_writer_and_respects_save_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, save_result: bool
) -> None:
    """Generated source paths must reflect the real writer result before COM starts."""
    monkeypatch.setattr(
        module, "NamedTemporaryFile", partial(tempfile.NamedTemporaryFile, dir=tmp_path)
    )
    host = Host()
    install_session(monkeypatch, host.session)
    image = Image(save_result=save_result)

    assert (
        PhotoshopGateway().open_image(image=image, image_meta=metadata(None))
        is save_result
    )

    assert len(image.saves) == 1
    path, format_name = image.saves[0]
    assert path.parent == tmp_path and format_name == "PNG"
    if save_result:
        assert path.read_bytes() == b"image-writer-output"
        assert host.opened[0][0] == str(path)
    else:
        assert host.events == []


def test_long_source_path_is_staged_without_changing_original(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """External-editor staging must copy the original bytes to its owned short path."""
    source = tmp_path / "source.png"
    source.write_bytes(b"original-image")
    monkeypatch.setattr(
        module, "NamedTemporaryFile", partial(tempfile.NamedTemporaryFile, dir=tmp_path)
    )
    monkeypatch.setattr(module, "exceeds_windows_legacy_path_limit", lambda _path: True)
    host = Host()
    install_session(monkeypatch, host.session)
    image = Image()

    assert PhotoshopGateway().open_image(image=image, image_meta=metadata(source))

    staged = Path(host.opened[0][0])
    assert staged != source and staged.parent == tmp_path and staged.suffix == ".png"
    assert staged.read_bytes() == source.read_bytes() == b"original-image"
    assert image.saves == []
