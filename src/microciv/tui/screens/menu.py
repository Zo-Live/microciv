"""Initial menu screen."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from microciv.tui.presenters.state_machine import ScreenRoute
from microciv.tui.widgets.logo import LogoWidget


class MainMenuScreen(Screen[None]):
    """Top-level entry screen."""

    BINDINGS = [Binding("q", "quit", "Quit")]

    DEFAULT_CSS = """
    MainMenuScreen {
        background: #111111;
        color: #f3ead7;
    }

    #menu-root {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
        align: center middle;
    }

    #menu-left {
        width: 1fr;
        height: 1fr;
        align: center middle;
    }

    #menu-right {
        width: 36;
        height: auto;
        align: center middle;
    }

    #menu-right Button {
        width: 1fr;
        min-height: 3;
        margin: 1 0;
        border: none;
        background: #1f1d19;
        color: #f7efdd;
        text-style: bold;
    }

    #menu-right Button:hover {
        background: #2b2822;
    }

    #menu-right #menu-exit {
        color: #f3c0b5;
    }

    #menu-title {
        margin-top: 1;
        color: #f2dfb4;
        text-style: bold;
    }
    """

    def __init__(self) -> None:
        super().__init__(id=ScreenRoute.MAIN_MENU.value)

    def compose(self):
        with Horizontal(id="menu-root"):
            with Vertical(id="menu-left"):
                yield LogoWidget(show_title=False)
                yield Static("MicroCiv", id="menu-title")
            with Vertical(id="menu-right"):
                yield Button("Play", id="menu-play")
                yield Button("Autoplay", id="menu-autoplay")
                yield Button("Records", id="menu-records")
                yield Button("Exit", id="menu-exit")

    def action_quit(self) -> None:
        self.app.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        assert button_id is not None
        if button_id == "menu-play":
            self.app.open_setup_for_play()
        elif button_id == "menu-autoplay":
            self.app.open_setup_for_autoplay()
        elif button_id == "menu-records":
            self.app.open_records()
        elif button_id == "menu-exit":
            self.app.exit()
