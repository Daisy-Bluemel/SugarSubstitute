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

"""Model the consumed external Session contract and image boundary for export tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from types import ModuleType, TracebackType

import pytest

from substitute.domain.workflow import ImageMeta


def install_session(monkeypatch: pytest.MonkeyPatch, export: object) -> None:
    """Install only the optional module boundary for one test."""
    library = ModuleType("photoshop")
    setattr(library, "Session", export)
    monkeypatch.setitem(sys.modules, "photoshop", library)


@dataclass
class Image:
    """Provide image metadata and record the externally supplied PNG writer."""

    width_value: int = 320
    height_value: int = 240
    dots_per_meter: int = 0
    save_result: bool = True
    saves: list[tuple[Path, str]] = field(default_factory=list)

    def width(self) -> int:
        """Return the supplied source width."""
        return self.width_value

    def height(self) -> int:
        """Return the supplied source height."""
        return self.height_value

    def dotsPerMeterX(self) -> int:
        """Return the supplied horizontal resolution."""
        return self.dots_per_meter

    def save(self, path: str, format_name: str) -> bool:
        """Record the requested format without implementing image encoding."""
        target = Path(path)
        self.saves.append((target, format_name))
        if self.save_result:
            target.write_bytes(b"image-writer-output")
        return self.save_result


@dataclass
class Layer:
    """Expose the mutable native layer name used by the adapter."""

    name: str = "Unnamed"


class Selection:
    """Require selection before the native copy operation."""

    def __init__(self, host: Host) -> None:
        """Retain the native operation recorder."""
        self.host = host
        self.selected = False

    def selectAll(self) -> None:
        """Select source pixels before copying."""
        self.host.operation("select_all")
        self.selected = True

    def copy(self) -> None:
        """Reject an export that did not select the source document."""
        self.host.operation("copy")
        assert self.selected
        self.host.clipboard_ready = True


class Layers:
    """Record the adapter's existing final layer-index request."""

    def __init__(self, host: Host) -> None:
        """Create a sentinel distinct from the most recently pasted layer."""
        self.host = host
        self.final_layer = Layer("Native indexed layer")
        self.index_requests: list[int] = []

    def __getitem__(self, index: int) -> Layer:
        """Return a deterministic native boundary result without claiming COM indexing."""
        self.index_requests.append(index)
        return self.final_layer


class Document:
    """Expose one Photoshop document while recording observed export effects."""

    def __init__(self, host: Host, *, temporary: bool) -> None:
        """Initialize source-selection and destination-layer state."""
        self.host = host
        self.temporary = temporary
        self.selection = Selection(host)
        self.artLayers = Layers(host)
        self.activeLayer = Layer()
        self.pasted_layers: list[Layer] = []
        self.close_modes: list[int] = []

    def paste(self) -> Layer:
        """Require destination activation and a successfully copied selection."""
        self.host.operation("paste")
        assert self.host.activeDocument is self
        assert self.host.clipboard_ready
        self.host.clipboard_ready = False
        layer = Layer()
        self.pasted_layers.append(layer)
        self.activeLayer = layer
        return layer

    def close(self, saving: int) -> None:
        """Record the caller's exact temporary-document save policy."""
        self.host.operation("close")
        self.close_modes.append(saving)


class Documents:
    """Record new-document metadata at the native collection boundary."""

    def __init__(self, host: Host) -> None:
        """Keep created documents and their requested metadata."""
        self.host = host
        self.created: list[tuple[Document, int, int, float, str]] = []

    def add(self, *, width: int, height: int, resolution: float, name: str) -> Document:
        """Create the destination for the supplied metadata."""
        self.host.operation("add")
        document = Document(self.host, temporary=False)
        self.created.append((document, width, height, resolution, name))
        return document


class Host:
    """Represent the native application boundary with controlled failure points."""

    def __init__(self, *, fail_at: str | None = None) -> None:
        """Initialize mutable state independently for each export scenario."""
        self.fail_at = fail_at
        self.events: list[str] = []
        self.documents = Documents(self)
        self.opened: list[tuple[str, Document]] = []
        self.activeDocument: Document | None = None
        self.clipboard_ready = False
        self.exits: list[type[BaseException] | None] = []

    def operation(self, name: str) -> None:
        """Fail only at the explicitly selected external operation."""
        self.events.append(name)
        if name == self.fail_at:
            raise RuntimeError(f"external {name} failed")

    def open(self, path: str) -> Document:
        """Open and activate a temporary native source document."""
        self.operation("open")
        document = Document(self, temporary=True)
        self.opened.append((path, document))
        self.activeDocument = document
        return document

    def session(self) -> Session:
        """Construct one session at the caller's ordinary execution point."""
        self.operation("construct")
        return Session(self)


class Session:
    """Preserve the external context-manager lifecycle and failure propagation."""

    def __init__(self, host: Host) -> None:
        """Expose the native application for this session."""
        self.app = host

    def __enter__(self) -> Session:
        """Enter only when construction has succeeded."""
        self.app.operation("enter")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Record the context exit without suppressing external exceptions."""
        self.app.exits.append(exc_type)
        self.app.operation("exit")


def metadata(path: Path | None, *, cube: str = "Cube", number: int = 3) -> ImageMeta:
    """Create source routing metadata without a Qt or application dependency."""
    return ImageMeta(
        workflow_name="Workflow",
        cube_name=cube,
        image_number=number,
        suffix=".png",
        path=str(path) if path is not None else "",
    )
