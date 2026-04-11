"""Widgets used inside contextual action panels."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont
from textual import events
from textual.containers import Container
from textual.message import Message

from microciv.game.enums import ResourceType
from microciv.tui.renderers.assets import APP_BACKGROUND, RESOURCE_HEX_METRICS, SHADOW_COLOR, TEXT_PRIMARY, rgba
from microciv.tui.renderers.hexes import render_hex_image, resource_color
from microciv.tui.renderers.scaling import image_size_for_cells
from microciv.tui.widgets.image_surface import ImageSurface


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_resource_button_image(
    resource_type: ResourceType,
    value: int | None,
    *,
    width_cells: int,
    height_cells: int,
    active: bool,
) -> Image.Image:
    """Render a resource icon and value into one fixed raster slot."""
    width_px, height_px = image_size_for_cells(width_cells, height_cells)
    image = Image.new("RGBA", (width_px, height_px), rgba(APP_BACKGROUND))
    if not active:
        return image

    hex_image = render_hex_image(resource_color(resource_type), metrics=RESOURCE_HEX_METRICS)
    offset_y = max((height_px - hex_image.height) // 2, 0)
    image.alpha_composite(hex_image, (0, offset_y))

    text = str(value) if value is not None else ""
    if not text:
        return image

    draw = ImageDraw.Draw(image)
    text_area_left = min(hex_image.width + 6, width_px - 4)
    max_text_width = max(width_px - text_area_left - 2, 1)
    max_text_height = max(height_px - 4, 1)
    font = ImageFont.load_default()
    for font_size in range(max_text_height, 6, -1):
        candidate = _load_font(font_size)
        bbox = draw.textbbox((0, 0), text, font=candidate)
        if (bbox[2] - bbox[0]) <= max_text_width and (bbox[3] - bbox[1]) <= max_text_height:
            font = candidate
            break

    bbox = draw.textbbox((0, 0), text, font=font)
    text_x = max(text_area_left - bbox[0], 0)
    text_y = max((height_px - (bbox[3] - bbox[1])) // 2 - bbox[1] - 1, 0)
    draw.text((min(text_x + 1, width_px - 1), min(text_y + 1, height_px - 1)), text, font=font, fill=rgba(SHADOW_COLOR))
    draw.text((text_x, text_y), text, font=font, fill=rgba(TEXT_PRIMARY))
    return image


class ResourceButton(Container):
    """Compact clickable resource icon with a numeric value."""

    class Pressed(Message):
        """Posted when the resource icon is selected."""

        def __init__(self, sender: ResourceButton, resource_type: ResourceType) -> None:
            super().__init__()
            self.sender = sender
            self.resource_type = resource_type

    DEFAULT_CSS = """
    ResourceButton {
        width: 1fr;
        height: 3;
        min-height: 3;
        padding: 0;
        margin: 0 1 0 0;
        background: transparent;
        border: none;
    }
    """

    def __init__(
        self,
        resource_type: ResourceType,
        value: int,
        *,
        id: str | None = None,
        interactive: bool = True,
    ) -> None:
        super().__init__(id=id)
        self.resource_type = resource_type
        self.value = value
        self._interactive = interactive
        self._active = True
        self._image_surface: ImageSurface | None = None
        self._last_cells: tuple[int, int] = (0, 0)

    def compose(self):
        self._image_surface = ImageSurface(id=f"{self.id}-image" if self.id else None)
        yield self._image_surface

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh_image)

    def on_resize(self, event: events.Resize) -> None:
        del event
        size_cells = (max(self.size.width, 1), max(self.size.height, 1))
        if size_cells != self._last_cells:
            self.call_after_refresh(self._refresh_image)

    def on_click(self, event: events.Click) -> None:
        if not self._interactive or not self._active:
            return
        event.stop()
        self.post_message(self.Pressed(self, self.resource_type))

    def set_resource(
        self,
        resource_type: ResourceType,
        value: int,
        *,
        interactive: bool | None = None,
        active: bool | None = None,
    ) -> None:
        """Update the displayed resource type and value without rebuilding the widget."""
        self.resource_type = resource_type
        self.value = value
        if interactive is not None:
            self._interactive = interactive
        if active is not None:
            self._active = active
        self._refresh_image()

    def _refresh_image(self) -> None:
        if not self.is_mounted or self._image_surface is None or not self._image_surface.is_mounted:
            return
        width_cells = max(self.size.width, 1)
        height_cells = max(self.size.height, 1)
        self._last_cells = (width_cells, height_cells)
        self._image_surface.set_image(
            render_resource_button_image(
                self.resource_type,
                self.value,
                width_cells=width_cells,
                height_cells=height_cells,
                active=self._active,
            )
        )
