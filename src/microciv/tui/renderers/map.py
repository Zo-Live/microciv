"""Map layout helpers for both fallback text and raster rendering."""

from __future__ import annotations

from dataclasses import dataclass
from math import dist

from PIL import Image

from microciv.game.models import GameState
from microciv.tui.renderers.assets import APP_BACKGROUND, HexRasterMetrics, MAP_HEX_METRICS
from microciv.tui.renderers.hexes import (
    RasterHexSpec,
    axial_center,
    hex_polygon,
    render_hex_cluster_image,
    tile_color,
)
from microciv.utils.hexgrid import coord_sort_key


def grouped_map_rows(state: GameState) -> list[tuple[int, list[tuple[int, int]], int]]:
    """Return rows grouped by axial r coordinate with a simple text indent."""
    row_map: dict[int, list[tuple[int, int]]] = {}
    for coord in sorted(state.board, key=coord_sort_key):
        row_map.setdefault(coord[1], []).append(coord)

    rows: list[tuple[int, list[tuple[int, int]], int]] = []
    radius = state.config.map_size - 1
    for r in range(-radius, radius + 1):
        coords = row_map.get(r, [])
        if not coords:
            continue
        indent = abs(r) * 4
        rows.append((r, coords, indent))
    return rows


@dataclass(frozen=True)
class MapRasterLayout:
    """Precomputed geometry for a rendered map image."""

    metrics: HexRasterMetrics
    image_width: int
    image_height: int
    pixel_centers: dict[tuple[int, int], tuple[float, float]]
    polygons: dict[tuple[int, int], tuple[tuple[float, float], ...]]

    def pixel_center_for_coord(self, coord: tuple[int, int]) -> tuple[float, float]:
        """Return the raster-space center of a coordinate."""
        return self.pixel_centers[coord]

    def coord_at_pixel(self, pixel_x: float, pixel_y: float) -> tuple[int, int] | None:
        """Return the map coord hit by a pixel position."""
        point = (pixel_x, pixel_y)
        for coord, polygon in self.polygons.items():
            if _point_in_polygon(point, polygon):
                return coord

        nearest_coord: tuple[int, int] | None = None
        nearest_distance: float | None = None
        for coord, center in self.pixel_centers.items():
            current_distance = dist(point, center)
            if nearest_distance is None or current_distance < nearest_distance:
                nearest_coord = coord
                nearest_distance = current_distance
        if nearest_coord is not None and nearest_distance is not None and nearest_distance <= self.metrics.cell_side * 0.95:
            return nearest_coord
        return None


def build_map_layout(
    state: GameState,
    *,
    metrics: HexRasterMetrics = MAP_HEX_METRICS,
) -> MapRasterLayout:
    """Return the raster geometry used to render a map image."""
    sorted_coords = sorted(state.board, key=coord_sort_key)
    centers = {coord: axial_center(coord, cell_side=metrics.cell_side) for coord in sorted_coords}
    half_height = (3**0.5) * metrics.cell_side / 2
    min_x = min(center_x - metrics.cell_side for center_x, _ in centers.values()) - metrics.margin
    max_x = max(center_x + metrics.cell_side for center_x, _ in centers.values()) + metrics.margin
    min_y = min(center_y - half_height for _, center_y in centers.values()) - metrics.margin
    max_y = max(center_y + half_height for _, center_y in centers.values()) + metrics.margin

    pixel_centers = {
        coord: (center_x - min_x, center_y - min_y)
        for coord, (center_x, center_y) in centers.items()
    }
    polygons = {
        coord: tuple(hex_polygon(center_x, center_y, side=max(metrics.cell_side - metrics.fill_inset, 2)))
        for coord, (center_x, center_y) in pixel_centers.items()
    }

    return MapRasterLayout(
        metrics=metrics,
        image_width=int(max_x - min_x),
        image_height=int(max_y - min_y),
        pixel_centers=pixel_centers,
        polygons=polygons,
    )


def render_map_image(
    state: GameState,
    *,
    selected_coord: tuple[int, int] | None = None,
    metrics: HexRasterMetrics = MAP_HEX_METRICS,
    background: str = APP_BACKGROUND,
) -> Image.Image:
    """Render the full map board as a single raster image."""
    specs = [
        RasterHexSpec(coord, color=tile_color(state.board[coord]), selected=coord == selected_coord)
        for coord in sorted(state.board, key=coord_sort_key)
    ]
    return render_hex_cluster_image(specs, metrics=metrics, background=background)


def render_map_image_for_cells(
    state: GameState,
    *,
    template_metrics: HexRasterMetrics = MAP_HEX_METRICS,
    max_width_cells: int | None = None,
    max_height_cells: int | None = None,
    background: str = APP_BACKGROUND,
) -> tuple[Image.Image, MapRasterLayout]:
    """Render the map using fixed metrics (simplified version)."""
    # For simplicity, we just use the template metrics directly
    # This ensures stable rendering without dynamic scaling
    image = render_map_image(state, metrics=template_metrics, background=background)
    layout = build_map_layout(state, metrics=template_metrics)
    return (image, layout)


def _point_in_polygon(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    """Return True when the point lies inside the polygon."""
    point_x, point_y = point
    inside = False
    previous_x, previous_y = polygon[-1]
    for current_x, current_y in polygon:
        if ((current_y > point_y) != (previous_y > point_y)) and (
            point_x < (previous_x - current_x) * (point_y - current_y) / (previous_y - current_y + 1e-9) + current_x
        ):
            inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside
