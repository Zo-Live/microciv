"""Raster text widget used to avoid Textual text repaint artifacts."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont
from textual import events
from textual.containers import Container

from microciv.tui.renderers.assets import APP_BACKGROUND, SHADOW_COLOR, TEXT_MUTED, TEXT_PRIMARY, rgba
from microciv.tui.renderers.scaling import image_size_for_cells
from microciv.tui.widgets.image_surface import ImageSurface


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_text_image(
    text: str,
    *,
    width_cells: int,
    height_cells: int,
    align: str = "left",
    color: str = TEXT_PRIMARY,
    background: str = APP_BACKGROUND,
) -> Image.Image:
    """Render one raster text line into a fixed cell slot."""
    width_px, height_px = image_size_for_cells(width_cells, height_cells)
    image = Image.new("RGBA", (width_px, height_px), rgba(background))
    content = text.strip()
    if not content:
        return image

    draw = ImageDraw.Draw(image)
    max_text_width = max(width_px - 6, 1)
    max_text_height = max(height_px - 4, 1)
    font = ImageFont.load_default()
    for font_size in range(max_text_height, 6, -1):
        candidate = _load_font(font_size)
        bbox = draw.textbbox((0, 0), content, font=candidate)
        if (bbox[2] - bbox[0]) <= max_text_width and (bbox[3] - bbox[1]) <= max_text_height:
            font = candidate
            break

    bbox = draw.textbbox((0, 0), content, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    if align == "right":
        text_x = max(width_px - text_width - 2 - bbox[0], 0)
    elif align == "center":
        text_x = max((width_px - text_width) // 2 - bbox[0], 0)
    else:
        text_x = max(2 - bbox[0], 0)
    text_y = max((height_px - text_height) // 2 - bbox[1] - 1, 0)
    draw.text((min(text_x + 1, width_px - 1), min(text_y + 1, height_px - 1)), content, font=font, fill=rgba(SHADOW_COLOR))
    draw.text((text_x, text_y), content, font=font, fill=rgba(color))
    return image


class TextImage(Container):
    """Fixed-slot raster text widget."""

    DEFAULT_CSS = """
    TextImage {
        width: 1fr;
        height: 1;
        min-height: 1;
        background: transparent;
        border: none;
        padding: 0;
        margin: 0;
    }
    """

    def __init__(
        self,
        text: str,
        *,
        align: str = "left",
        color: str = TEXT_PRIMARY,
        muted: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._text = text
        self._align = align
        self._color = TEXT_MUTED if muted else color
        self._surface: ImageSurface | None = None
        self._last_cells: tuple[int, int] = (0, 0)

    @property
    def text(self) -> str:
        return self._text

    def compose(self):
        self._surface = ImageSurface(id=f"{self.id}-surface" if self.id else None)
        yield self._surface

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh_image)

    def on_resize(self, event: events.Resize) -> None:
        del event
        size_cells = (max(self.size.width, 1), max(self.size.height, 1))
        if size_cells != self._last_cells:
            self.call_after_refresh(self._refresh_image)

    def set_text(self, text: str) -> None:
        self._text = text
        self._refresh_image()

    def set_color(self, color: str) -> None:
        self._color = color
        self._refresh_image()

    def _refresh_image(self) -> None:
        if not self.is_mounted or self._surface is None or not self._surface.is_mounted:
            return
        width_cells = max(self.size.width, 1)
        height_cells = max(self.size.height, 1)
        self._last_cells = (width_cells, height_cells)
        self._surface.set_image(
            render_text_image(
                self._text,
                width_cells=width_cells,
                height_cells=height_cells,
                align=self._align,
                color=self._color,
            )
        )
