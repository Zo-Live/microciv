"""Reusable hex-based widgets."""

from __future__ import annotations

from textual import events
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from microciv.tui.renderers.assets import HexRasterMetrics, RESOURCE_HEX_METRICS
from microciv.tui.renderers.hexes import render_hex_image
from microciv.tui.widgets.image_surface import ImageSurface


class HexButton(Widget):
    """Clickable hex display with no default border."""

    class Pressed(Message):
        """Posted when the hex is clicked."""

        def __init__(self, sender: HexButton, value: str) -> None:
            super().__init__()
            self.sender = sender
            self.value = value

    DEFAULT_CSS = """
    HexButton {
        width: auto;
        height: auto;
        padding: 0;
        margin: 0;
        border: none;
        background: transparent;
        align: center top;
    }

    HexButton > Vertical {
        width: auto;
        height: auto;
        align: center top;
    }

    HexButton .hex-button-label {
        width: auto;
        height: auto;
        content-align: center top;
        color: #f3ead7;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        value: str,
        *,
        color: str,
        selected: bool = False,
        compact: bool = False,
        label: str | None = None,
        show_label: bool = False,
        metrics: HexRasterMetrics | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(id=id, classes=classes, disabled=disabled)
        self.value = value
        self.color = color
        self.selected = selected
        self.compact = compact
        self.label = label
        self.show_label = show_label
        self.metrics = metrics or RESOURCE_HEX_METRICS
        self._image_surface: ImageSurface | None = None

    def set_visuals(self, *, color: str, selected: bool) -> None:
        """Update color and selection state."""
        self.color = color
        self.selected = selected
        if self._image_surface is not None and self._image_surface.is_mounted:
            self._image_surface.set_image(self._render_image())
        self.refresh(layout=True)

    def compose(self):
        with Vertical():
            self._image_surface = ImageSurface(self._render_image(), id=f"{self.id}-image" if self.id else None)
            yield self._image_surface
            if self.show_label and self.label:
                yield Static(self.label, classes="hex-button-label", id=f"{self.id}-label" if self.id else None)

    def on_click(self, event: events.Click) -> None:
        if self.disabled:
            return
        event.stop()
        self.post_message(self.Pressed(self, self.value))

    def _render_image(self):
        return render_hex_image(
            self.color,
            selected=self.selected,
            metrics=self.metrics,
        )


class HexStat(Static):
    """Legacy placeholder for compact hex stats."""

    DEFAULT_CSS = """
    HexStat {
        display: none;
    }
    """
