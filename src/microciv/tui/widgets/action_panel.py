"""Widgets used inside contextual action panels."""

from __future__ import annotations

from textual import events
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from microciv.game.enums import ResourceType
from microciv.tui.renderers.assets import RESOURCE_HEX_METRICS
from microciv.tui.renderers.hexes import render_hex_image, resource_color
from microciv.tui.widgets.image_surface import ImageSurface


class ResourceButton(Widget):
    """Compact clickable resource icon with a numeric value."""

    class Pressed(Message):
        """Posted when the resource icon is selected."""

        def __init__(self, sender: ResourceButton, resource_type: ResourceType) -> None:
            super().__init__()
            self.sender = sender
            self.resource_type = resource_type

    DEFAULT_CSS = """
    ResourceButton {
        width: 1fr;
        height: auto;
        padding: 0;
        margin: 0 1 0 0;
    }

    ResourceButton .resource-row {
        width: 1fr;
        height: auto;
        align: left middle;
    }

    ResourceButton .resource-value {
        width: auto;
        height: auto;
        content-align: left middle;
        color: #f3ead7;
        text-style: bold;
        margin-left: 1;
    }
    """

    def __init__(
        self,
        resource_type: ResourceType,
        value: int,
        *,
        id: str | None = None,
        interactive: bool = True,
    ) -> None:
        super().__init__(id=id)
        self.resource_type = resource_type
        self.value = value
        self._interactive = interactive

    def compose(self):
        with Horizontal(classes="resource-row"):
            yield ImageSurface(
                render_hex_image(resource_color(self.resource_type), metrics=RESOURCE_HEX_METRICS),
                id=f"{self.id}-icon" if self.id else None,
            )
            yield Static(str(self.value), classes="resource-value")

    def on_click(self, event: events.Click) -> None:
        if not self._interactive:
            return
        event.stop()
        self.post_message(self.Pressed(self, self.resource_type))
