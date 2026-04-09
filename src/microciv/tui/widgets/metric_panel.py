"""Score, turn, and status information panel."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text
from textual.widgets import Static

from microciv.tui.renderers.digits import render_large_number, render_small_number


class MetricPanel(Static):
    """Right-side score and status display."""

    DEFAULT_CSS = """
    MetricPanel {
        width: 1fr;
        height: auto;
        padding: 0;
        margin: 0;
    }
    """

    def __init__(
        self,
        *,
        score: int,
        turn: int,
        turn_limit: int,
        info_lines: list[str] | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.update_render(score=score, turn=turn, turn_limit=turn_limit, info_lines=info_lines or [])

    def update_render(
        self,
        *,
        score: int,
        turn: int,
        turn_limit: int,
        info_lines: list[str],
    ) -> None:
        self.update(
            Group(
                Text("SCORE", style="#f2dfb4 bold"),
                render_large_number(score),
                Text(""),
                Text("STEP", style="#f2dfb4 bold"),
                render_small_number(f"{turn:02d}"),
                Text(f"/ {turn_limit}", style="#b3c0c5"),
                Text(""),
                *[Text(line, style="#a9b7be") for line in info_lines],
            )
        )
