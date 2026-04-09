"""Widgets used inside contextual action panels."""

from __future__ import annotations

from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from microciv.game.enums import ResourceType
from microciv.tui.renderers.hexes import resource_color
from microciv.tui.widgets.hexes import HexButton


class ResourceButton(Widget):
    """Clickable resource icon with a numeric value."""

    class Pressed(Message):
        """Posted when the resource icon is selected."""

        def __init__(self, sender: ResourceButton, resource_type: ResourceType) -> None:
            super().__init__()
            self.sender = sender
            self.resource_type = resource_type

    DEFAULT_CSS = """
    ResourceButton {
        width: auto;
        height: auto;
        padding: 0;
        margin: 0 3 0 0;
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

    def __init__(self, resource_type: ResourceType, value: int, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.resource_type = resource_type
        self.value = value

    def compose(self):
        with Horizontal():
            yield HexButton(
                self.resource_type.value,
                color=resource_color(self.resource_type),
                compact=True,
                id=f"{self.id}-hex" if self.id else None,
            )
            yield Static(str(self.value), classes="resource-value")

    def on_hex_button_pressed(self, message: HexButton.Pressed) -> None:
        message.stop()
        self.post_message(self.Pressed(self, self.resource_type))
