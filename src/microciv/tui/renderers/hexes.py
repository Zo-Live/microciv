"""Shared hex rendering helpers for both fallback text and raster images."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, sqrt
from typing import Iterable

from PIL import Image, ImageDraw
from rich.console import Group, RenderableType
from rich.text import Text

from microciv.game.enums import OccupantType, ResourceType, TerrainType
from microciv.game.models import Tile
from microciv.tui.renderers.assets import (
    APP_BACKGROUND,
    HexRasterMetrics,
    MAP_HEX_METRICS,
    RESOURCE_HEX_METRICS,
    rgba,
)

HEX_WIDTH = 8
HEX_HEIGHT = 4
COMPACT_HEX_WIDTH = 8
COMPACT_HEX_HEIGHT = 3

PLAIN_COLOR = "#7fa44d"
FOREST_COLOR = "#2f7d44"
MOUNTAIN_COLOR = "#8e8d90"
RIVER_COLOR = "#4ea9d8"
WASTELAND_COLOR = "#d0a35d"
CITY_COLOR = "#ff6858"
ROAD_COLOR = "#f3c987"
SELECTED_BORDER_COLOR = "#f8f7f2"
EMPTY_STYLE = APP_BACKGROUND

SQRT_3 = sqrt(3)


@dataclass(frozen=True)
class RasterHexSpec:
    """One colored hex to be drawn into a cluster image."""

    coord: tuple[int, int]
    color: str
    selected: bool = False


def tile_color(tile: Tile) -> str:
    """Return the display color for a tile."""
    if tile.occupant is OccupantType.CITY:
        return CITY_COLOR
    if tile.occupant is OccupantType.ROAD:
        return ROAD_COLOR
    return terrain_color(tile.base_terrain)


def terrain_color(terrain: TerrainType) -> str:
    """Return the color for a terrain."""
    if terrain is TerrainType.PLAIN:
        return PLAIN_COLOR
    if terrain is TerrainType.FOREST:
        return FOREST_COLOR
    if terrain is TerrainType.MOUNTAIN:
        return MOUNTAIN_COLOR
    if terrain is TerrainType.RIVER:
        return RIVER_COLOR
    return WASTELAND_COLOR


def resource_color(resource_type: ResourceType) -> str:
    """Return the display color for a resource icon."""
    if resource_type is ResourceType.FOOD:
        return PLAIN_COLOR
    if resource_type is ResourceType.WOOD:
        return FOREST_COLOR
    if resource_type is ResourceType.ORE:
        return MOUNTAIN_COLOR
    return RIVER_COLOR


def axial_center(coord: tuple[int, int], *, cell_side: int) -> tuple[float, float]:
    """Return the center of a flat-top axial hex."""
    q, r = coord
    return (
        cell_side * 1.5 * q,
        SQRT_3 * cell_side * (r + q / 2),
    )


def hex_polygon(
    center_x: float,
    center_y: float,
    *,
    side: float,
) -> list[tuple[float, float]]:
    """Return the polygon points for a flat-top hex centered at ``(x, y)``."""
    half_side = side / 2
    half_height = SQRT_3 * side / 2
    return [
        (center_x + side, center_y),
        (center_x + half_side, center_y + half_height),
        (center_x - half_side, center_y + half_height),
        (center_x - side, center_y),
        (center_x - half_side, center_y - half_height),
        (center_x + half_side, center_y - half_height),
    ]


def render_hex_image(
    color: str,
    *,
    selected: bool = False,
    metrics: HexRasterMetrics = MAP_HEX_METRICS,
    background: str = APP_BACKGROUND,
) -> Image.Image:
    """Render one flat-top raster hex."""
    return render_hex_cluster_image(
        [RasterHexSpec((0, 0), color=color, selected=selected)],
        metrics=metrics,
        background=background,
    )


def render_hex_cluster_image(
    hexes: Iterable[RasterHexSpec],
    *,
    metrics: HexRasterMetrics = MAP_HEX_METRICS,
    background: str = APP_BACKGROUND,
) -> Image.Image:
    """Render a cluster of axial flat-top hexes into one raster image."""
    hex_specs = list(hexes)
    if not hex_specs:
        return Image.new("RGBA", (1, 1), rgba(background))

    centers = [axial_center(spec.coord, cell_side=metrics.cell_side) for spec in hex_specs]
    half_height = SQRT_3 * metrics.cell_side / 2

    min_x = floor(min(center_x - metrics.cell_side for center_x, _ in centers)) - metrics.margin
    max_x = ceil(max(center_x + metrics.cell_side for center_x, _ in centers)) + metrics.margin
    min_y = floor(min(center_y - half_height for _, center_y in centers)) - metrics.margin
    max_y = ceil(max(center_y + half_height for _, center_y in centers)) + metrics.margin

    image = Image.new("RGBA", (max_x - min_x, max_y - min_y), rgba(background))
    draw = ImageDraw.Draw(image)

    for spec, (center_x, center_y) in sorted(
        zip(hex_specs, centers, strict=True),
        key=lambda item: (item[0].coord[0] + item[0].coord[1], item[0].coord[0], item[0].coord[1]),
    ):
        shifted_x = center_x - min_x
        shifted_y = center_y - min_y
        _draw_hex(draw, shifted_x, shifted_y, color=spec.color, selected=spec.selected, metrics=metrics)

    return image


def _draw_hex(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    center_y: float,
    *,
    color: str,
    selected: bool,
    metrics: HexRasterMetrics,
) -> None:
    fill_side = max(metrics.cell_side - metrics.fill_inset, 2)
    if selected:
        border_side = max(metrics.cell_side - metrics.fill_inset / 2, fill_side)
        inner_side = max(border_side - metrics.selection_width, 2)
        draw.polygon(hex_polygon(center_x, center_y, side=border_side), fill=rgba(SELECTED_BORDER_COLOR))
        draw.polygon(hex_polygon(center_x, center_y, side=inner_side), fill=rgba(color))
        return
    draw.polygon(hex_polygon(center_x, center_y, side=fill_side), fill=rgba(color))


def render_hex(color: str, *, selected: bool = False, compact: bool = False) -> RenderableType:
    """Render a single flat-top hex block using the legacy text fallback."""
    if compact:
        return Group(*_compact_hex_lines(color))
    if selected:
        return Group(*_selected_hex_lines(color))
    return Group(*_map_hex_lines(color))


def _compact_hex_lines(color: str) -> list[Text]:
    lines = [
        _line("  ", color, 4, "  "),
        _line(" ", color, 6, " "),
        _line("  ", color, 4, "  "),
    ]
    return lines


def _map_hex_lines(color: str) -> list[Text]:
    lines = [
        _line("  ", color, 4, "  "),
        _line(" ", color, 6, " "),
        _line(" ", color, 6, " "),
        _line("  ", color, 4, "  "),
    ]
    return lines


def _selected_hex_lines(color: str) -> list[Text]:
    top = Text("  ____  ", style=SELECTED_BORDER_COLOR)

    upper = Text(" /", style=SELECTED_BORDER_COLOR)
    upper.append("    ", style=f"on {color}")
    upper.append("\\ ", style=SELECTED_BORDER_COLOR)

    lower = Text("|", style=SELECTED_BORDER_COLOR)
    lower.append("      ", style=f"on {color}")
    lower.append("|", style=SELECTED_BORDER_COLOR)

    bottom = Text(" \\____/ ", style=SELECTED_BORDER_COLOR)
    return [top, upper, lower, bottom]


def _line(left: str, color: str, fill_width: int, right: str) -> Text:
    line = Text(left, style=EMPTY_STYLE)
    line.append(" " * fill_width, style=f"on {color}")
    line.append(right, style=EMPTY_STYLE)
    return line
