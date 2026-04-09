"""Final result screen."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from microciv.tui.presenters.game_session import GameSession
from microciv.tui.presenters.state_machine import ScreenRoute
from microciv.tui.renderers.digits import render_large_number
from microciv.tui.widgets.map_grid import MapGrid


class FinalScreen(Screen[None]):
    """Display the final map and high-level result."""

    BINDINGS = [Binding("q", "quit", "Quit")]

    DEFAULT_CSS = """
    FinalScreen {
        background: #111111;
        color: #f3ead7;
    }

    #final-root {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
    }

    #final-map-shell {
        width: 1fr;
        height: 1fr;
        align: center middle;
    }

    #final-side-shell {
        width: 34;
        height: 1fr;
        padding-left: 2;
    }

    #final-side-shell Button {
        width: 1fr;
        min-height: 3;
        margin-bottom: 1;
        border: none;
        background: #1d1c18;
        color: #f7efdd;
    }
    """

    def __init__(self, session: GameSession) -> None:
        super().__init__(id=ScreenRoute.FINAL.value)
        self.session = session

    def compose(self):
        with Horizontal(id="final-root"):
            with Vertical(id="final-map-shell"):
                yield MapGrid(self.session.state, interactive=False, id="final-map")
            with Vertical(id="final-side-shell"):
                yield Static(self._final_renderable(), id="final-score")
                yield Button("Restart", id="final-restart")
                yield Button("Menu", id="final-menu")
                yield Button("Exit", id="final-exit")

    def action_quit(self) -> None:
        self.app.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        assert button_id is not None
        if button_id == "final-restart":
            self.app.restart_from_session(self.session)
        elif button_id == "final-menu":
            self.app.return_to_menu()
        elif button_id == "final-exit":
            self.app.exit()

    def _final_renderable(self) -> Group:
        return Group(
            Text("SCORE", style="#f2dfb4 bold"),
            render_large_number(self.session.state.score),
            Text(""),
            Text(f"cities: {len(self.session.state.cities)}", style="#a9b7be"),
            Text(f"roads: {len(self.session.state.roads)}", style="#a9b7be"),
        )
