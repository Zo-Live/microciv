"""Logo metadata and raster rendering helpers."""

from __future__ import annotations

from PIL import Image

from microciv.tui.renderers.assets import APP_BACKGROUND, LOGO_HEX_METRICS
from microciv.tui.renderers.hexes import (
    CITY_COLOR,
    FOREST_COLOR,
    MOUNTAIN_COLOR,
    PLAIN_COLOR,
    RIVER_COLOR,
    ROAD_COLOR,
    WASTELAND_COLOR,
    RasterHexSpec,
    render_hex_cluster_image,
)

LOGO_TAGLINE = "Grow roads. Balance networks. Reach the final turn."

LOGO_HEXES: tuple[RasterHexSpec, ...] = (
    RasterHexSpec((0, -1), RIVER_COLOR),
    RasterHexSpec((-1, 0), WASTELAND_COLOR),
    RasterHexSpec((1, -1), ROAD_COLOR),
    RasterHexSpec((0, 0), CITY_COLOR),
    RasterHexSpec((-1, 1), MOUNTAIN_COLOR),
    RasterHexSpec((1, 0), FOREST_COLOR),
    RasterHexSpec((0, 1), PLAIN_COLOR),
)


def render_logo_rows() -> tuple[tuple[str, ...], ...]:
    """Return the simplified row grouping used in documentation and tests."""
    return (
        (RIVER_COLOR,),
        (WASTELAND_COLOR, ROAD_COLOR),
        (CITY_COLOR,),
        (MOUNTAIN_COLOR, FOREST_COLOR),
        (PLAIN_COLOR,),
    )


def render_logo_specs() -> tuple[RasterHexSpec, ...]:
    """Return the frozen seven-hex cluster used for the logo image."""
    return LOGO_HEXES


def render_logo_image(*, background: str = APP_BACKGROUND) -> Image.Image:
    """Render the seven-hex logo as one raster image."""
    return render_hex_cluster_image(LOGO_HEXES, metrics=LOGO_HEX_METRICS, background=background)


def render_logo_text() -> str:
    """Return a plain-text approximation of the logo layout."""
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
