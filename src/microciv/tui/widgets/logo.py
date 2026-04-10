"""Shared MicroCiv logo widget."""

from __future__ import annotations

from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from microciv.tui.renderers.logo import LOGO_TAGLINE, render_logo_image
from microciv.tui.widgets.image_surface import ImageSurface


class LogoWidget(Widget):
    """Seven-hex logo plus title text."""

    DEFAULT_CSS = """
    LogoWidget {
        width: auto;
        height: auto;
    }

    LogoWidget .logo-row {
        width: auto;
        height: auto;
        align: center middle;
    }

    LogoWidget .logo-indent-small {
        width: 4;
    }

    LogoWidget .logo-indent-large {
        width: 8;
    }

    LogoWidget .logo-title {
        margin-top: 1;
        color: #f2dfb4;
        text-style: bold;
    }

    LogoWidget .logo-tagline {
        color: #a9b7be;
    }
    """

    def __init__(self, *, show_title: bool = True, show_tagline: bool = False, id: str | None = None) -> None:
        super().__init__(id=id)
        self.show_title = show_title
        self.show_tagline = show_tagline

    def compose(self):
        with Vertical():
            with Horizontal(classes="logo-row"):
                yield ImageSurface(render_logo_image(), id="logo-image")
            if self.show_title:
                yield Static("MicroCiv", classes="logo-title")
            if self.show_tagline:
                yield Static(LOGO_TAGLINE, classes="logo-tagline")
