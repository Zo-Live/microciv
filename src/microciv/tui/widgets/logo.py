"""Shared dot-matrix logo widget using the same style as score digits."""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import Static

from microciv.tui.renderers.dotmatrix_logo import (
    LOGO_TAGLINE,
    render_menu_logo_mark,
    render_menu_logo_title,
)
from microciv.tui.widgets.image_surface import ImageSurface


class LogoWidget(Vertical):
    """Dot-matrix logo and title widget using the same style as game score digits."""

    DEFAULT_CSS = """
    LogoWidget {
        width: auto;
        height: auto;
        align: center middle;
    }

    LogoWidget .logo-block {
        width: auto;
        height: auto;
    }

    LogoWidget .logo-mark {
        margin-bottom: 2;
    }

    LogoWidget .logo-title {
        margin-top: 1;
    }

    LogoWidget .logo-tagline {
        width: auto;
        height: auto;
        margin-top: 1;
        color: #a9b7be;
        content-align: center middle;
    }
    """

    def __init__(
        self,
        *,
        show_title: bool = True,
        show_tagline: bool = False,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.show_title = show_title
        self.show_tagline = show_tagline
        self._mark_widget: ImageSurface | None = None
        self._title_widget: ImageSurface | None = None
        self._tagline_widget: Static | None = None

    def compose(self):
        self._mark_widget = ImageSurface(
            render_menu_logo_mark(),
            id="logo-mark",
            classes="logo-block logo-mark",
        )
        yield self._mark_widget
        if self.show_title:
            self._title_widget = ImageSurface(
                render_menu_logo_title(),
                id="logo-title",
                classes="logo-block logo-title",
            )
            yield self._title_widget
        if self.show_tagline:
            self._tagline_widget = Static(
                LOGO_TAGLINE,
                id="logo-tagline",
                classes="logo-tagline",
            )
            yield self._tagline_widget

    def _refresh_logo_image(self) -> None:
        """Compatibility shim for older tests and callbacks."""
        if self._mark_widget is not None and self._mark_widget.is_mounted:
            self._mark_widget.set_image(render_menu_logo_mark())
        if self.show_title and self._title_widget is not None and self._title_widget.is_mounted:
            self._title_widget.set_image(render_menu_logo_title())
        if self.show_tagline and self._tagline_widget is not None and self._tagline_widget.is_mounted:
            self._tagline_widget.update(LOGO_TAGLINE)
