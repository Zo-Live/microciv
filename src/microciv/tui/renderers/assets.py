"""Shared raster constants and helpers for TUI image rendering."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import ImageColor

APP_BACKGROUND = "#111111"
TEXT_PRIMARY = "#f7efdd"
TEXT_ACCENT = "#f2dfb4"
TEXT_MUTED = "#a9b7be"
SHADOW_COLOR = "#5b5448"


@dataclass(frozen=True)
class HexRasterMetrics:
    """Raster dimensions for a family of flat-top hexes."""

    cell_side: int
    fill_inset: int
    selection_width: int
    margin: int


LOGO_HEX_METRICS = HexRasterMetrics(cell_side=30, fill_inset=1, selection_width=4, margin=3)
RESOURCE_HEX_METRICS = HexRasterMetrics(cell_side=18, fill_inset=1, selection_width=3, margin=3)
PREVIEW_MAP_HEX_METRICS = HexRasterMetrics(cell_side=16, fill_inset=1, selection_width=3, margin=4)
DETAIL_MAP_HEX_METRICS = HexRasterMetrics(cell_side=22, fill_inset=1, selection_width=4, margin=5)
FINAL_MAP_HEX_METRICS = HexRasterMetrics(cell_side=28, fill_inset=1, selection_width=5, margin=6)
MAP_HEX_METRICS = HexRasterMetrics(cell_side=32, fill_inset=1, selection_width=5, margin=6)

SMALL_DIGIT_CELL_PX = 9
SMALL_DIGIT_GLYPH_GAP_PX = 6
LARGE_DIGIT_CELL_PX = 12
LARGE_DIGIT_GLYPH_GAP_PX = 10


def rgb(color: str) -> tuple[int, int, int]:
    """Convert a color string to an RGB tuple."""
    return ImageColor.getrgb(color)


def rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    """Convert a color string to an RGBA tuple."""
    red, green, blue = rgb(color)
    return red, green, blue, alpha
