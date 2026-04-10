"""Score, turn, and status information panel."""

from __future__ import annotations

from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from microciv.tui.renderers.digits import (
    render_large_number_image,
    render_small_number_image,
    scale_number_image,
)
from microciv.tui.widgets.image_surface import ImageSurface


class MetricPanel(Widget):
    """Right-side score, step, and small status text."""

    DEFAULT_CSS = """
    MetricPanel {
        width: 1fr;
        height: auto;
        padding: 0;
        margin: 0;
    }

    MetricPanel.-autoplay {
        height: 1fr;
    }

    MetricPanel .metric-root {
        width: 1fr;
        height: auto;
    }

    MetricPanel.-autoplay .metric-root {
        height: 1fr;
    }

    MetricPanel .metric-label {
        width: 1fr;
        height: auto;
        color: #f2dfb4;
        text-style: bold;
    }

    MetricPanel .metric-score-image {
        margin-bottom: 1;
    }

    MetricPanel .metric-step-row {
        width: 1fr;
        height: auto;
        align: left middle;
    }

    MetricPanel .metric-step-limit {
        color: #b3c0c5;
        margin-left: 1;
    }

    MetricPanel .metric-spacer {
        height: 1fr;
    }

    MetricPanel .metric-info {
        width: 1fr;
        height: auto;
        color: #a9b7be;
    }
    """

    def __init__(
        self,
        *,
        score: int,
        turn: int,
        turn_limit: int,
        info_lines: list[str] | None = None,
        autoplay: bool = False,
        id: str | None = None,
    ) -> None:
        classes = "-autoplay" if autoplay else None
        super().__init__(id=id, classes=classes)
        self._score = score
        self._turn = turn
        self._turn_limit = turn_limit
        self._info_lines = info_lines or []
        self._autoplay = autoplay

    def compose(self):
        with Vertical(classes="metric-root"):
            yield Static("SCORE", classes="metric-label", id=f"{self.id}-score-label" if self.id else None)
            yield ImageSurface(
                self._score_image(),
                classes="metric-score-image",
                id=f"{self.id}-score" if self.id else None,
            )
            yield Static("STEP", classes="metric-label", id=f"{self.id}-step-label" if self.id else None)
            with Horizontal(classes="metric-step-row"):
                yield ImageSurface(
                    self._step_image(),
                    classes="metric-step-image",
                    id=f"{self.id}-step" if self.id else None,
                )
                yield Static(f"/ {self._turn_limit}", classes="metric-step-limit", id=f"{self.id}-turn-limit" if self.id else None)
            if self._autoplay:
                yield Static("", classes="metric-spacer")
            yield Static(self._info_text(), classes="metric-info", id=f"{self.id}-info" if self.id else None)

    def update_render(
        self,
        *,
        score: int,
        turn: int,
        turn_limit: int,
        info_lines: list[str],
    ) -> None:
        self._score = score
        self._turn = turn
        self._turn_limit = turn_limit
        self._info_lines = info_lines
        self.query_one(".metric-score-image", ImageSurface).set_image(self._score_image())
        self.query_one(".metric-step-image", ImageSurface).set_image(self._step_image())
        turn_limit_selector = f"#{self.id}-turn-limit" if self.id else ".metric-step-limit"
        self.query_one(turn_limit_selector, Static).update(f"/ {self._turn_limit}")
        self.query_one(".metric-info", Static).update(self._info_text())

    def _score_image(self):
        return scale_number_image(render_large_number_image(self._score), 0.48)

    def _step_image(self):
        return scale_number_image(render_small_number_image(f"{self._turn:02d}"), 0.9)

    def _info_text(self) -> str:
        return "\n".join(self._info_lines)
