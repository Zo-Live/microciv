"""In-game menu screen."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button

from microciv.tui.presenters.state_machine import ScreenRoute
from microciv.tui.widgets.logo import LogoWidget


class GameMenuScreen(Screen[None]):
    """Pause-style menu shown over the game screen."""

    route = ScreenRoute.GAME_MENU

    BINDINGS = [
        Binding("m", "continue_game", "Continue"),
        Binding("q", "quit", "Quit"),
    ]

    DEFAULT_CSS = """
    GameMenuScreen {
        background: #111111;
        color: #f3ead7;
    }

    #game-menu-root {
        width: 1fr;
        height: 1fr;
        padding: 1 3;
        align: center middle;
    }

    #game-menu-left {
        width: 1fr;
        height: 1fr;
        align: center middle;
        padding-right: 3;
    }

    #game-menu-right {
        width: 30;
        height: auto;
    }

    #game-menu-right Button {
        width: 1fr;
        min-height: 4;
        margin-bottom: 1;
        border: none;
        background: #1d1c18;
        color: #f7efdd;
    }
    """

    def __init__(self) -> None:
        super().__init__()

    def compose(self):
        with Horizontal(id="game-menu-root"):
            with Vertical(id="game-menu-left"):
                yield LogoWidget(show_title=True, show_tagline=False)
            with Vertical(id="game-menu-right"):
                yield Button("Continue", id="game-menu-continue")
                yield Button("Menu", id="game-menu-main")
                yield Button("Exit", id="game-menu-exit")

    def action_continue_game(self) -> None:
        self.dismiss()

    def action_quit(self) -> None:
        self.app.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        assert button_id is not None
        if button_id == "game-menu-continue":
            self.dismiss()
        elif button_id == "game-menu-main":
            self.app.return_to_menu()
        elif button_id == "game-menu-exit":
            self.app.exit()
