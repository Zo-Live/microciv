"""Reusable hex-based widgets."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text
from textual.message import Message
from textual.widgets import Button, Static

from microciv.tui.renderers.hexes import render_hex


class HexButton(Button):
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
    }
    """

    def __init__(
        self,
        value: str,
        *,
        color: str,
        selected: bool = False,
        compact: bool = False,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__("", id=id, classes=classes, disabled=disabled)
        self.value = value
        self.color = color
        self.selected = selected
        self.compact = compact

    def set_visuals(self, *, color: str, selected: bool) -> None:
        """Update color and selection state."""
        self.color = color
        self.selected = selected
        self.refresh()

    def render(self):
        return render_hex(self.color, selected=self.selected, compact=self.compact)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is self and not self.disabled:
            event.stop()
            self.post_message(self.Pressed(self, self.value))


class HexStat(Static):
    """Compact hex icon with a numeric value next to it."""

    DEFAULT_CSS = """
    HexStat {
        width: auto;
        height: auto;
        padding: 0;
        margin: 0 2 0 0;
    }
    """

    def __init__(self, *, color: str, value: int, id: str | None = None) -> None:
        super().__init__(id=id)
        self.color = color
        self.value = value
        self.update(self._build_renderable())

    def _build_renderable(self) -> Group:
        hex_renderable = render_hex(self.color, compact=True)
        value_text = Text(f"{self.value}", style="#f3ead7 bold")
        return Group(hex_renderable, value_text)
