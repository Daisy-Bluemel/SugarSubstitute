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

"""Describe and lazily load the pinned Photoshop Session API without inspecting COM."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from importlib import import_module
from typing import Protocol, runtime_checkable


class PhotoshopLayer(Protocol):
    """Expose the only layer field written during image export."""

    name: str


class PhotoshopSelection(Protocol):
    """Describe the source selection operations consumed by the adapter."""

    def selectAll(self) -> object:
        """Select the complete temporary source document."""

    def copy(self) -> object:
        """Copy selected source pixels to the native clipboard."""


class PhotoshopLayers(Protocol):
    """Keep the adapter's native layer-index request explicit."""

    def __getitem__(self, index: int) -> PhotoshopLayer:
        """Resolve the existing integer selector or propagate its native failure."""


class PhotoshopDocument(Protocol):
    """Describe the document operations already consumed by image export."""

    @property
    def selection(self) -> PhotoshopSelection:
        """Return the source document's selection interface."""

    @property
    def artLayers(self) -> PhotoshopLayers:
        """Return the native art-layer collection without enumerating it."""

    @property
    def activeLayer(self) -> PhotoshopLayer:
        """Return the currently active destination layer."""

    @activeLayer.setter
    def activeLayer(self, layer: PhotoshopLayer) -> None:
        """Select the layer returned by the native collection."""

    def paste(self) -> object:
        """Paste copied pixels into the active destination document."""

    def close(self, saving: int) -> object:
        """Close a temporary document with the caller's native save policy."""


class PhotoshopDocuments(Protocol):
    """Expose document creation with the metadata used by the adapter."""

    def add(
        self, *, width: int, height: int, resolution: float, name: str
    ) -> PhotoshopDocument:
        """Create a destination document with the supplied dimensions and label."""


class PhotoshopApplication(Protocol):
    """Describe the native application surface without evaluating its properties."""

    @property
    def documents(self) -> PhotoshopDocuments:
        """Return the native document collection."""

    @property
    def activeDocument(self) -> PhotoshopDocument:
        """Return the active native document."""

    @activeDocument.setter
    def activeDocument(self, document: PhotoshopDocument) -> None:
        """Activate the destination before pasting copied pixels."""

    def open(self, path: str) -> PhotoshopDocument:
        """Open one existing source file as a temporary document."""


class PhotoshopSession(Protocol):
    """Describe the value returned by the pinned Session context manager."""

    @property
    def app(self) -> PhotoshopApplication:
        """Expose the native application for the entered session."""


PhotoshopSessionFactory = Callable[[], AbstractContextManager[PhotoshopSession]]


@runtime_checkable
class _PhotoshopModule(Protocol):
    """Validate only the module export, leaving live COM properties untouched."""

    def Session(self) -> AbstractContextManager[PhotoshopSession]:
        """Construct the documented zero-argument context manager when requested."""


def load_photoshop_session() -> PhotoshopSessionFactory:
    """Load the optional constructor without constructing or probing a COM session.

    The protocols describe the consumed API of the pinned photoshop package.
    Only the module-level callable is inspected here: probing nested native
    properties can execute COM work and change its failure timing. Construction,
    context entry, export operations, and context exit remain with the caller.
    """
    module: object = import_module("photoshop")
    if not isinstance(module, _PhotoshopModule) or not callable(module.Session):
        raise TypeError("Photoshop module does not expose a callable Session.")
    return module.Session


__all__ = ["PhotoshopSessionFactory", "load_photoshop_session"]
