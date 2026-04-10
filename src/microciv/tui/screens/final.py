"""Final result screen."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from microciv.tui.presenters.game_session import GameSession
from microciv.tui.presenters.state_machine import ScreenRoute
from microciv.tui.renderers.assets import FINAL_MAP_HEX_METRICS
from microciv.tui.renderers.digits import render_large_number_image, scale_number_image
from microciv.tui.widgets.image_surface import ImageSurface
from microciv.tui.widgets.map_preview import MapPreview


class FinalScreen(Screen[None]):
    """Display the final map and high-level result."""

    route = ScreenRoute.FINAL

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
        padding-right: 1;
        align: center middle;
    }

    #final-side-shell {
        width: 32;
        height: 1fr;
        padding-left: 1;
    }

    #final-score-label {
        color: #f2dfb4;
        text-style: bold;
        margin-bottom: 1;
    }

    #final-score-value {
        margin-bottom: 2;
    }

    #final-side-shell Button {
        width: 1fr;
        min-height: 3;
        margin-bottom: 1;
        border: none;
        background: #1d1c18;
        color: #f7efdd;
    }

    #final-side-shell #final-exit {
        color: #f3c0b5;
    }
    """

    def __init__(self, session: GameSession) -> None:
        super().__init__()
        self.session = session

    def compose(self):
        with Horizontal(id="final-root"):
            with Vertical(id="final-map-shell"):
                yield MapPreview(self.session.state, metrics=FINAL_MAP_HEX_METRICS, id="final-map")
            with Vertical(id="final-side-shell"):
                yield Static("SCORE", id="final-score-label")
                yield ImageSurface(_scaled_score_image(self.session.state.score), id="final-score-value")
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

def _scaled_score_image(score: int):
    return scale_number_image(render_large_number_image(score), 0.68)
