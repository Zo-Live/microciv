"""Shared hex rendering helpers for the TUI."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text

from microciv.game.enums import OccupantType, ResourceType, TerrainType
from microciv.game.models import Tile

HEX_WIDTH = 8
HEX_HEIGHT = 4
COMPACT_HEX_WIDTH = 8
COMPACT_HEX_HEIGHT = 3

PLAIN_COLOR = "#7fa44d"
FOREST_COLOR = "#2f7d44"
MOUNTAIN_COLOR = "#8e8d90"
RIVER_COLOR = "#4ea9d8"
WASTELAND_COLOR = "#d0a35d"
CITY_COLOR = "#d9775f"
ROAD_COLOR = "#b98b57"
SELECTED_BORDER_COLOR = "#f8f7f2"
EMPTY_STYLE = "#111111"


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


def render_hex(color: str, *, selected: bool = False, compact: bool = False) -> RenderableType:
    """Render a single flat-top hex block."""
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
