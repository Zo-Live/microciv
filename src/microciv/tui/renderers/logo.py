"""Logo metadata and color layout helpers."""

from __future__ import annotations

from microciv.tui.renderers.hexes import (
    CITY_COLOR,
    FOREST_COLOR,
    MOUNTAIN_COLOR,
    PLAIN_COLOR,
    RIVER_COLOR,
    ROAD_COLOR,
    WASTELAND_COLOR,
)

LOGO_TAGLINE = "Grow roads. Balance networks. Reach the final turn."

LOGO_ROWS: tuple[tuple[str, ...], ...] = (
    (RIVER_COLOR,),
    (PLAIN_COLOR, FOREST_COLOR, MOUNTAIN_COLOR),
    (WASTELAND_COLOR, CITY_COLOR),
    (ROAD_COLOR,),
)


def render_logo_rows() -> tuple[tuple[str, ...], ...]:
    """Return the frozen 7-hex layout colors."""
    return LOGO_ROWS


def render_logo_text() -> str:
    """Return a plain-text approximation of the seven-hex logo layout."""
    return "\n".join(
        [
            "                   __",
            "                __/  \\__",
            "               /  \\__/  \\",
            "               \\__/  \\__/",
            "               /  \\__/  \\",
            "               \\__/  \\__/",
            "                  \\__/",
        ]
    )
