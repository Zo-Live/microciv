"""Hex-map widget for play, autoplay, preview, and final screens."""

from __future__ import annotations

from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from microciv.game.models import GameState
from microciv.tui.renderers.hexes import tile_color
from microciv.tui.renderers.map import grouped_map_rows
from microciv.tui.widgets.hexes import HexButton


class MapGrid(Widget):
    """Render the board as a centered field of clickable colored hexes."""

    class TileSelected(Message):
        """Posted when a tile is clicked."""

        def __init__(self, sender: MapGrid, coord: tuple[int, int]) -> None:
            super().__init__()
            self.sender = sender
            self.coord = coord

    DEFAULT_CSS = """
    MapGrid {
        width: auto;
        height: auto;
    }

    MapGrid .map-stack {
        width: auto;
        height: auto;
    }

    MapGrid .map-row {
        width: auto;
        height: auto;
    }

    MapGrid .row-indent {
        width: auto;
        height: 4;
    }
    """

    def __init__(
        self,
        state: GameState,
        *,
        selected_coord: tuple[int, int] | None = None,
        interactive: bool = True,
        compact: bool = False,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._state = state
        self._selected_coord = selected_coord
        self._interactive = interactive
        self._compact = compact

    def set_state(self, state: GameState, selected_coord: tuple[int, int] | None, *, interactive: bool | None = None) -> None:
        """Update the displayed state."""
        self._state = state
        self._selected_coord = selected_coord
        if interactive is not None:
            self._interactive = interactive
        self.refresh(layout=True, recompose=True)

    def compose(self):
        with Vertical(classes="map-stack"):
            for _row_r, coords, indent in grouped_map_rows(self._state):
                with Horizontal(classes="map-row"):
                    if indent > 0:
                        yield Static(" " * indent, classes="row-indent")
                    for coord in coords:
                        tile = self._state.board[coord]
                        yield HexButton(
                            f"{coord[0]},{coord[1]}",
                            color=tile_color(tile),
                            selected=coord == self._selected_coord,
                            compact=self._compact,
                            disabled=not self._interactive,
                            id=f"tile-{coord[0]}-{coord[1]}",
                        )

    def on_hex_button_pressed(self, message: HexButton.Pressed) -> None:
        if not self._interactive:
            return
        q_str, r_str = message.value.split(",", maxsplit=1)
        self.post_message(self.TileSelected(self, (int(q_str), int(r_str))))
