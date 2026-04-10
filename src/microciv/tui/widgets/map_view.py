"""Interactive raster map widget for the main game screen."""

from __future__ import annotations

from textual import events
from textual.containers import Container
from textual.geometry import Offset
from textual.message import Message

from microciv.game.models import GameState
from microciv.tui.renderers.assets import MAP_HEX_METRICS
from microciv.tui.renderers.map import MapRasterLayout, build_map_layout, render_map_image
from microciv.tui.widgets.image_surface import ImageSurface


class MapView(Container):
    """Display the board as one raster image with click hit testing."""

    class TileSelected(Message):
        """Posted when a map coordinate is selected."""

        def __init__(self, sender: MapView, coord: tuple[int, int]) -> None:
            super().__init__()
            self.sender = sender
            self.coord = coord

    DEFAULT_CSS = """
    MapView {
        width: auto;
        height: auto;
        background: transparent;
        border: none;
        padding: 0;
        margin: 0;
    }
    """

    def __init__(
        self,
        state: GameState,
        *,
        selected_coord: tuple[int, int] | None = None,
        interactive: bool = True,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._state = state
        self._selected_coord = selected_coord
        self._interactive = interactive
        self._layout = build_map_layout(state, metrics=MAP_HEX_METRICS)

    def compose(self):
        yield ImageSurface(
            render_map_image(self._state, selected_coord=self._selected_coord, metrics=MAP_HEX_METRICS),
            id=f"{self.id}-image" if self.id else None,
        )

    def set_state(self, state: GameState, selected_coord: tuple[int, int] | None, *, interactive: bool | None = None) -> None:
        """Update the displayed state and selection."""
        self._state = state
        self._selected_coord = selected_coord
        if interactive is not None:
            self._interactive = interactive
        self._layout = build_map_layout(state, metrics=MAP_HEX_METRICS)
        self.query_one(ImageSurface).set_image(
            render_map_image(state, selected_coord=selected_coord, metrics=MAP_HEX_METRICS)
        )

    def local_offset_for_coord(self, coord: tuple[int, int]) -> tuple[int, int]:
        """Return a stable local click offset for automated tests."""
        pixel_x, pixel_y = self._layout.pixel_center_for_coord(coord)
        return self._cell_offset_from_pixel(pixel_x, pixel_y)

    def on_click(self, event: events.Click) -> None:
        if not self._interactive:
            return
        content_offset = event.get_content_offset(self)
        if content_offset is None:
            return
        coord = self._coord_from_cell_offset(content_offset)
        if coord is None:
            return
        event.stop()
        self.post_message(self.TileSelected(self, coord))

    def _coord_from_cell_offset(self, offset: Offset) -> tuple[int, int] | None:
        width = max(self.content_region.width, 1)
        height = max(self.content_region.height, 1)
        pixel_x = ((offset.x + 0.5) / width) * self._layout.image_width
        pixel_y = ((offset.y + 0.5) / height) * self._layout.image_height
        return self._layout.coord_at_pixel(pixel_x, pixel_y)

    def _cell_offset_from_pixel(self, pixel_x: float, pixel_y: float) -> tuple[int, int]:
        width = max(self.content_region.width, 1)
        height = max(self.content_region.height, 1)
        cell_x = min(max(round((pixel_x / self._layout.image_width) * max(width - 1, 0)), 0), max(width - 1, 0))
        cell_y = min(max(round((pixel_y / self._layout.image_height) * max(height - 1, 0)), 0), max(height - 1, 0))
        return (cell_x, cell_y)
