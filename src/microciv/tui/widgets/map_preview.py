"""Non-interactive raster map preview widget for setup-like screens."""

from __future__ import annotations

from textual.containers import Container

from microciv.game.models import GameState
from microciv.tui.renderers.assets import HexRasterMetrics, PREVIEW_MAP_HEX_METRICS
from microciv.tui.renderers.map import render_map_image
from microciv.tui.widgets.image_surface import ImageSurface


class MapPreview(Container):
    """Display a game state as a single raster map image."""

    DEFAULT_CSS = """
    MapPreview {
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
        metrics: HexRasterMetrics = PREVIEW_MAP_HEX_METRICS,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._state = state
        self._metrics = metrics

    def compose(self):
        yield ImageSurface(
            render_map_image(self._state, metrics=self._metrics),
            id=f"{self.id}-image" if self.id else None,
        )

    def set_state(self, state: GameState) -> None:
        """Update the previewed state."""
        self._state = state
        self.query_one(ImageSurface).set_image(render_map_image(state, metrics=self._metrics))
