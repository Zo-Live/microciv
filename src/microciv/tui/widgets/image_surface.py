"""Shared image widget wrapper for raster-rendered TUI assets."""

from __future__ import annotations

from typing import Callable

from PIL import Image as PILImage
from textual.containers import Container
from textual_image.widget import Image as AutoImage
from textual_image.widget import get_cell_size


class ImageSurface(Container):
    """Thin wrapper around ``textual-image`` with a stable local API."""

    DEFAULT_CSS = """
    ImageSurface {
        width: auto;
        height: auto;
        background: transparent;
        border: none;
        padding: 0;
        margin: 0;
    }

    ImageSurface > Container {
        width: auto;
        height: auto;
        background: transparent;
        border: none;
        padding: 0;
        margin: 0;
    }

    ImageSurface AutoImage {
        width: auto;
        height: auto;
        background: transparent;
        border: none;
        padding: 0;
        margin: 0;
    }
    """

    def __init__(
        self,
        image: PILImage.Image | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._image = image

    @property
    def image(self) -> PILImage.Image | None:
        """Return the currently assigned PIL image."""
        return self._image

    def compose(self):
        width_cells, height_cells = self._cell_dimensions(self._image)
        self.styles.width = width_cells
        self.styles.height = height_cells
        with Container():
            auto_image = AutoImage(self._image, id=f"{self.id}-image" if self.id else None)
            auto_image.styles.width = width_cells
            auto_image.styles.height = height_cells
            yield auto_image

    def set_image(self, image: PILImage.Image | None) -> None:
        """Replace the displayed image."""
        self._image = image
        auto_image = self.query_one(AutoImage)
        width_cells, height_cells = self._cell_dimensions(image)
        self.styles.width = width_cells
        self.styles.height = height_cells
        auto_image.styles.width = width_cells
        auto_image.styles.height = height_cells
        auto_image.image = image

    def render_with(self, renderer: Callable[..., PILImage.Image], /, *args, **kwargs) -> None:
        """Render a new image and display it immediately."""
        self.set_image(renderer(*args, **kwargs))

    def _cell_dimensions(self, image: PILImage.Image | None) -> tuple[int, int]:
        if image is None:
            return (1, 1)
        cell_size = get_cell_size()
        width = max(1, (image.width + cell_size.width - 1) // cell_size.width)
        height = max(1, (image.height + cell_size.height - 1) // cell_size.height)
        return (width, height)
