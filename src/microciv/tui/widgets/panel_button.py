"""Raster-backed clickable button used by the game side panel."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont
from textual import events
from textual.containers import Container
from textual.message import Message

from microciv.tui.renderers.assets import APP_BACKGROUND, SHADOW_COLOR, TEXT_ACCENT, TEXT_MUTED, TEXT_PRIMARY, rgba
from microciv.tui.renderers.scaling import image_size_for_cells
from microciv.tui.widgets.image_surface import ImageSurface


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_panel_button_image(
    label: str,
    *,
    width_cells: int,
    height_cells: int,
    accent: bool = False,
    muted: bool = False,
) -> Image.Image:
    """Render a compact raster button that avoids Textual text layout."""
    width_px, height_px = image_size_for_cells(width_cells, height_cells)
    image = Image.new("RGBA", (width_px, height_px), rgba(APP_BACKGROUND))
    draw = ImageDraw.Draw(image)

    body_color = "#1d1c18"
    text_color = TEXT_PRIMARY
    if muted:
        body_color = "#171614"
        text_color = TEXT_MUTED
    elif accent:
        body_color = "#232019"
        text_color = TEXT_ACCENT

    pad_x = max(width_px // 24, 4)
    pad_y = max(height_px // 10, 3)
    shadow_offset = max(height_px // 14, 1)
    radius = max(min(height_px, width_px) // 12, 2)
    shadow_rect = (
        pad_x,
        pad_y + shadow_offset,
        max(width_px - pad_x - 1, pad_x),
        max(height_px - pad_y - 1, pad_y + shadow_offset),
    )
    body_rect = (
        pad_x,
        pad_y,
        max(width_px - pad_x - 1, pad_x),
        max(height_px - pad_y - 1, pad_y),
    )
    draw.rounded_rectangle(shadow_rect, radius=radius, fill=rgba(SHADOW_COLOR, 180))
    draw.rounded_rectangle(body_rect, radius=radius, fill=rgba(body_color))

    text = label.strip()
    if not text:
        return image

    max_text_width = max(width_px - (pad_x + 6) * 2, 1)
    max_text_height = max(height_px - (pad_y + 4) * 2, 1)
    font = ImageFont.load_default()
    for font_size in range(max_text_height, 7, -1):
        candidate = _load_font(font_size)
        bbox = draw.textbbox((0, 0), text, font=candidate)
        if (bbox[2] - bbox[0]) <= max_text_width and (bbox[3] - bbox[1]) <= max_text_height:
            font = candidate
            break

    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    text_x = max((width_px - text_width) // 2 - bbox[0], 0)
    text_y = max((height_px - text_height) // 2 - bbox[1] - 1, 0)
    shadow_xy = (text_x + 1, min(text_y + 1, height_px - text_height))
    draw.text(shadow_xy, text, font=font, fill=rgba(SHADOW_COLOR))
    draw.text((text_x, text_y), text, font=font, fill=rgba(text_color))
    return image


class PanelButton(Container):
    """Raster-backed alternative to ``Button`` for low-churn side panel actions."""

    class Pressed(Message):
        """Posted when the panel button is clicked."""

        def __init__(self, sender: PanelButton, button_id: str) -> None:
            super().__init__()
            self.sender = sender
            self.button_id = button_id

    DEFAULT_CSS = """
    PanelButton {
        width: 1fr;
        min-height: 2;
        height: 2;
        background: transparent;
        border: none;
        padding: 0;
        margin: 0;
    }

    PanelButton > ImageSurface {
        width: auto;
        height: auto;
        background: transparent;
        border: none;
        padding: 0;
        margin: 0;
    }
    """

    def __init__(self, label: str, *, id: str | None = None, classes: str | None = None, disabled: bool = False) -> None:
        super().__init__(id=id, classes=classes)
        self._label = label
        self._disabled = disabled
        self._surface: ImageSurface | None = None
        self._last_cells: tuple[int, int] = (0, 0)

    @property
    def label(self) -> str:
        return self._label

    def compose(self):
        self._surface = ImageSurface(id=f"{self.id}-surface" if self.id else None)
        yield self._surface

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh_image)

    def on_resize(self, event: events.Resize) -> None:
        del event
        size_cells = self._button_cells()
        if size_cells != self._last_cells:
            self.call_after_refresh(self._refresh_image)

    def set_label(self, label: str) -> None:
        self._label = label
        self._refresh_image()

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = disabled
        self.set_class(disabled, "-muted")
        self._refresh_image()

    def set_class(self, add: bool, *class_names: str) -> PanelButton:
        super().set_class(add, *class_names)
        self._refresh_image()
        return self

    def on_click(self, event: events.Click) -> None:
        if self._disabled or self.id is None or not self._label.strip():
            return
        event.stop()
        self.post_message(self.Pressed(self, self.id))

    def _button_cells(self) -> tuple[int, int]:
        width = max(self.size.width, 1)
        height = max(self.size.height, 2)
        return (width, height)

    def _refresh_image(self) -> None:
        if not self.is_mounted or self._surface is None or not self._surface.is_mounted:
            return
        width_cells, height_cells = self._button_cells()
        self._last_cells = (width_cells, height_cells)
        self._surface.set_image(
            render_panel_button_image(
                self._label,
                width_cells=width_cells,
                height_cells=height_cells,
                accent="-accent" in self.classes,
                muted=self._disabled,
            )
        )
