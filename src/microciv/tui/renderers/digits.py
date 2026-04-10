"""Blocky numeric renderers for score and turn displays."""

from __future__ import annotations

from PIL import Image, ImageDraw
from rich.console import Group, RenderableType
from rich.text import Text

from microciv.tui.renderers.assets import (
    APP_BACKGROUND,
    LARGE_DIGIT_CELL_PX,
    LARGE_DIGIT_GLYPH_GAP_PX,
    SHADOW_COLOR,
    SMALL_DIGIT_CELL_PX,
    SMALL_DIGIT_GLYPH_GAP_PX,
    TEXT_ACCENT,
    rgba,
)

BODY = "█"
SHADOW = "▒"
BLANK = " "

SMALL_PATTERNS: dict[str, tuple[str, ...]] = {
    "0": ("███▒", "█  █▒", "█  █▒", " ███▒"),
    "1": (" ██▒", "  █▒", "  █▒", " ███▒"),
    "2": ("███▒", "  ██▒", "██▒  ", "████▒"),
    "3": ("███▒", "  ██▒", "  ██▒", "███▒"),
    "4": ("█  █▒", "████▒", "   █▒", "   █▒"),
    "5": ("████▒", "██▒  ", "  ██▒", "███▒"),
    "6": (" ███▒", "██▒  ", "█  █▒", " ███▒"),
    "7": ("████▒", "  ██▒", "  █▒ ", "  █▒ "),
    "8": (" ███▒", "█  █▒", "█  █▒", " ███▒"),
    "9": (" ███▒", "█  █▒", "  ██▒", " ███▒"),
}

LARGE_PATTERNS: dict[str, tuple[str, ...]] = {
    "0": (
        "   █████▒▒",
        " ██▒▒   ██▒▒",
        "██▒▒     ██▒▒",
        "██▒▒     ██▒▒",
        "██▒▒     ██▒▒",
        "██▒▒     ██▒▒",
        " ██▒▒   ██▒▒",
        "   █████▒▒",
    ),
    "1": (
        "    ██▒▒",
        "  ████▒▒",
        "    ██▒▒",
        "    ██▒▒",
        "    ██▒▒",
        "    ██▒▒",
        "    ██▒▒",
        "  █████▒▒",
    ),
    "2": (
        "   █████▒▒",
        " ██▒▒   ██▒▒",
        "      ██▒▒",
        "    ██▒▒  ",
        "  ██▒▒    ",
        "██▒▒      ",
        "██▒▒      ",
        "████████▒▒",
    ),
    "3": (
        "   █████▒▒",
        " ██▒▒   ██▒▒",
        "      ██▒▒",
        "   ████▒▒ ",
        "      ██▒▒",
        "      ██▒▒",
        " ██▒▒   ██▒▒",
        "   █████▒▒",
    ),
    "4": (
        "██▒▒   ██▒▒",
        "██▒▒   ██▒▒",
        "██▒▒   ██▒▒",
        "████████▒▒",
        "      ██▒▒",
        "      ██▒▒",
        "      ██▒▒",
        "      ██▒▒",
    ),
    "5": (
        "████████▒▒",
        "██▒▒      ",
        "██▒▒      ",
        "██████▒▒  ",
        "      ██▒▒",
        "      ██▒▒",
        " ██▒▒   ██▒▒",
        "   █████▒▒",
    ),
    "6": (
        "   █████▒▒",
        " ██▒▒     ",
        "██▒▒      ",
        "██████▒▒  ",
        "██▒▒   ██▒▒",
        "██▒▒   ██▒▒",
        " ██▒▒   ██▒▒",
        "   █████▒▒",
    ),
    "7": (
        "████████▒▒",
        "     ██▒▒ ",
        "    ██▒▒  ",
        "   ██▒▒   ",
        "   ██▒▒   ",
        "  ██▒▒    ",
        "  ██▒▒    ",
        "  ██▒▒    ",
    ),
    "8": (
        "   █████▒▒",
        " ██▒▒   ██▒▒",
        "██▒▒     ██▒▒",
        " ███████▒▒",
        "██▒▒     ██▒▒",
        "██▒▒     ██▒▒",
        " ██▒▒   ██▒▒",
        "   █████▒▒",
    ),
    "9": (
        "   █████▒▒",
        " ██▒▒   ██▒▒",
        "██▒▒     ██▒▒",
        "██▒▒     ██▒▒",
        " ██████▒▒▒",
        "      ██▒▒",
        "    ██▒▒  ",
        " ████▒▒   ",
    ),
}


def render_small_number(
    value: int | str,
    *,
    body_color: str = TEXT_ACCENT,
    shadow_color: str = SHADOW_COLOR,
) -> RenderableType:
    """Render a compact numeric display using the text fallback."""
    return _render_number(str(value), SMALL_PATTERNS, body_color=body_color, shadow_color=shadow_color)


def render_large_number(
    value: int | str,
    *,
    body_color: str = TEXT_ACCENT,
    shadow_color: str = SHADOW_COLOR,
) -> RenderableType:
    """Render a larger numeric display using the text fallback."""
    return _render_number(str(value), LARGE_PATTERNS, body_color=body_color, shadow_color=shadow_color)


def render_small_number_image(
    value: int | str,
    *,
    body_color: str = TEXT_ACCENT,
    shadow_color: str = SHADOW_COLOR,
    background: str = APP_BACKGROUND,
) -> Image.Image:
    """Render a compact number as a raster image."""
    return _render_number_image(
        str(value),
        SMALL_PATTERNS,
        cell_size=SMALL_DIGIT_CELL_PX,
        glyph_gap=SMALL_DIGIT_GLYPH_GAP_PX,
        body_color=body_color,
        shadow_color=shadow_color,
        background=background,
    )


def render_large_number_image(
    value: int | str,
    *,
    body_color: str = TEXT_ACCENT,
    shadow_color: str = SHADOW_COLOR,
    background: str = APP_BACKGROUND,
) -> Image.Image:
    """Render a large number as a raster image."""
    return _render_number_image(
        str(value),
        LARGE_PATTERNS,
        cell_size=LARGE_DIGIT_CELL_PX,
        glyph_gap=LARGE_DIGIT_GLYPH_GAP_PX,
        body_color=body_color,
        shadow_color=shadow_color,
        background=background,
    )


def scale_number_image(image: Image.Image, scale: float) -> Image.Image:
    """Return a nearest-neighbor scaled copy for compact panel use."""
    width = max(int(round(image.width * scale)), 1)
    height = max(int(round(image.height * scale)), 1)
    return image.resize((width, height), Image.Resampling.NEAREST)


def _render_number(
    value: str,
    patterns: dict[str, tuple[str, ...]],
    *,
    body_color: str,
    shadow_color: str,
) -> RenderableType:
    rows = len(next(iter(patterns.values())))
    lines: list[Text] = []
    for row_index in range(rows):
        line = Text()
        for char_index, char in enumerate(value):
            if char_index:
                line.append("  ")
            pattern = patterns.get(char, patterns["0"])
            line.append(_styled_row(pattern[row_index], body_color=body_color, shadow_color=shadow_color))
        lines.append(line)
    return Group(*lines)


def _styled_row(row: str, *, body_color: str, shadow_color: str) -> Text:
    text = Text()
    for char in row:
        if char == BODY:
            text.append(char, style=body_color)
        elif char == SHADOW:
            text.append(char, style=shadow_color)
        else:
            text.append(char)
    return text


def _render_number_image(
    value: str,
    patterns: dict[str, tuple[str, ...]],
    *,
    cell_size: int,
    glyph_gap: int,
    body_color: str,
    shadow_color: str,
    background: str,
) -> Image.Image:
    value = value or "0"
    glyphs = [patterns.get(char, patterns["0"]) for char in value]
    rows = len(glyphs[0])
    cols_per_glyph = [max(len(row) for row in glyph) for glyph in glyphs]
    width = sum(cols * cell_size for cols in cols_per_glyph) + glyph_gap * max(len(glyphs) - 1, 0)
    height = rows * cell_size
    image = Image.new("RGBA", (width, height), rgba(background))
    draw = ImageDraw.Draw(image)

    x_offset = 0
    for glyph, cols in zip(glyphs, cols_per_glyph, strict=True):
        for row_index, row in enumerate(glyph):
            padded_row = row.ljust(cols)
            for col_index, cell in enumerate(padded_row):
                if cell == BLANK:
                    continue
                left = x_offset + col_index * cell_size
                top = row_index * cell_size
                right = left + cell_size - 1
                bottom = top + cell_size - 1
                inset = max(1, cell_size // 8)
                radius = max(1, cell_size // 4)
                fill = body_color if cell == BODY else shadow_color
                draw.rounded_rectangle(
                    (left + inset, top + inset, right - inset, bottom - inset),
                    radius=radius,
                    fill=rgba(fill),
                )
        x_offset += cols * cell_size + glyph_gap

    return image
