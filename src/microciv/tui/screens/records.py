"""Records list and detail screens."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static

from microciv.game.enums import MapDifficulty, OccupantType, TerrainType
from microciv.game.models import GameConfig, GameState, Tile
from microciv.records.models import RecordEntry
from microciv.tui.presenters.state_machine import ScreenRoute
from microciv.tui.widgets.map_grid import MapGrid
from microciv.tui.widgets.record_cards import RecordCardButton


class RecordsListScreen(Screen[None]):
    """Two-column records list screen."""

    BINDINGS = [
        Binding("b", "back", "Back"),
        Binding("d", "scroll_bottom", "Bottom"),
        Binding("t", "scroll_top", "Top"),
        Binding("q", "quit", "Quit"),
    ]

    DEFAULT_CSS = """
    RecordsListScreen {
        background: #111111;
        color: #f3ead7;
    }

    #records-root {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
    }

    #records-scroll {
        width: 1fr;
        height: 1fr;
        padding-right: 1;
    }

    .records-row {
        width: 1fr;
        height: auto;
        margin-bottom: 1;
    }

    .records-row RecordCardButton {
        width: 1fr;
        min-height: 8;
        margin-right: 1;
        border: none;
        background: #1d1c18;
        color: #f7efdd;
        text-align: left;
    }

    #records-empty {
        width: 1fr;
        height: 1fr;
        content-align: center middle;
        color: #a9b7be;
    }

    #records-actions {
        width: 1fr;
        height: auto;
        margin-top: 1;
    }

    #records-actions Button {
        width: 24;
        min-height: 3;
        border: none;
        background: #1d1c18;
        color: #f7efdd;
        margin-right: 1;
    }

    #records-actions.-centered {
        align: center middle;
    }

    #records-message {
        color: #a9b7be;
        margin-top: 1;
        height: auto;
    }
    """

    def __init__(self) -> None:
        super().__init__(id=ScreenRoute.RECORDS_LIST.value)
        self._message = ""

    def compose(self):
        records = list(reversed(self.app.reload_records().records))
        with Vertical(id="records-root"):
            if not records:
                yield Static("No Records", id="records-empty")
            else:
                with VerticalScroll(id="records-scroll"):
                    for left, right in _pairwise(records):
                        with Horizontal(classes="records-row"):
                            yield RecordCardButton(left, id=f"record-card-{left.record_id}")
                            if right is not None:
                                yield RecordCardButton(right, id=f"record-card-{right.record_id}")
                            else:
                                yield Static("")
            action_classes = "-centered" if not records else ""
            with Horizontal(id="records-actions", classes=action_classes):
                if records:
                    yield Button("Export", id="records-export")
                yield Button("Back", id="records-back")
            yield Static(self._message, id="records-message")

    def action_back(self) -> None:
        self.dismiss()

    def action_scroll_bottom(self) -> None:
        if self.query("#records-scroll"):
            self.query_one("#records-scroll", VerticalScroll).scroll_end(animate=False)

    def action_scroll_top(self) -> None:
        if self.query("#records-scroll"):
            self.query_one("#records-scroll", VerticalScroll).scroll_home(animate=False)

    def action_quit(self) -> None:
        self.app.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        assert button_id is not None
        if button_id == "records-back":
            self.dismiss()
        elif button_id == "records-export":
            export_path = self.app.export_records()
            self._message = "No records to export." if export_path is None else f"Exported: {export_path.name}"
            self.refresh(layout=True, recompose=True)
        elif button_id.startswith("record-card-"):
            record_id = int(button_id.removeprefix("record-card-"))
            record = next(record for record in self.app.records.records if record.record_id == record_id)
            self.app.open_record_detail(record)


class RecordDetailScreen(Screen[None]):
    """Single record detail view."""

    BINDINGS = [
        Binding("b", "back", "Back"),
        Binding("d", "scroll_bottom", "Bottom"),
        Binding("t", "scroll_top", "Top"),
        Binding("q", "quit", "Quit"),
    ]

    DEFAULT_CSS = """
    RecordDetailScreen {
        background: #111111;
        color: #f3ead7;
    }

    #record-detail-scroll {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
    }

    #record-detail-top {
        width: 1fr;
        height: auto;
        margin-bottom: 1;
    }

    #record-detail-map {
        width: 1fr;
        height: auto;
        align: center middle;
    }

    #record-detail-side {
        width: 30;
        height: auto;
        padding-left: 2;
    }

    #record-detail-side Button {
        width: 1fr;
        min-height: 3;
        margin-top: 1;
        border: none;
        background: #1d1c18;
        color: #f7efdd;
    }

    .record-stat {
        color: #a9b7be;
        margin-bottom: 1;
        height: auto;
    }
    """

    def __init__(self, record: RecordEntry) -> None:
        super().__init__(id=ScreenRoute.RECORD_DETAIL.value)
        self.record = record

    def compose(self):
        with VerticalScroll(id="record-detail-scroll"):
            with Horizontal(id="record-detail-top"):
                with Vertical(id="record-detail-map"):
                    yield MapGrid(_record_state(self.record), interactive=False, compact=True, id="record-detail-map-grid")
                with Vertical(id="record-detail-side"):
                    yield Static(f"Mode: {self.record.mode}", classes="record-stat")
                    yield Static(f"AI: {self.record.ai_type}", classes="record-stat")
                    yield Static(f"Diff: {self.record.map_difficulty}", classes="record-stat")
                    yield Button("Back", id="record-detail-back")
            yield Static(f"Final Score      {self.record.final_score}", classes="record-stat")
            yield Static(f"City Count       {self.record.city_count}", classes="record-stat")
            yield Static(f"Building Count   {self.record.building_count}", classes="record-stat")
            yield Static(f"Tech Count       {self.record.tech_count}", classes="record-stat")
            yield Static(f"Food             {self.record.food}", classes="record-stat")
            yield Static(f"Wood             {self.record.wood}", classes="record-stat")
            yield Static(f"Ore              {self.record.ore}", classes="record-stat")
            yield Static(f"Science          {self.record.science}", classes="record-stat")

    def action_back(self) -> None:
        self.dismiss()

    def action_scroll_bottom(self) -> None:
        self.query_one("#record-detail-scroll", VerticalScroll).scroll_end(animate=False)

    def action_scroll_top(self) -> None:
        self.query_one("#record-detail-scroll", VerticalScroll).scroll_home(animate=False)

    def action_quit(self) -> None:
        self.app.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "record-detail-back":
            self.dismiss()


def _pairwise(records: list[RecordEntry]) -> list[tuple[RecordEntry, RecordEntry | None]]:
    pairs: list[tuple[RecordEntry, RecordEntry | None]] = []
    for index in range(0, len(records), 2):
        left = records[index]
        right = records[index + 1] if index + 1 < len(records) else None
        pairs.append((left, right))
    return pairs


def _record_state(record: RecordEntry) -> GameState:
    state = GameState.empty(
        GameConfig.for_play(
            map_size=record.map_size,
            turn_limit=record.turn_limit,
            map_difficulty=MapDifficulty(record.map_difficulty),
            seed=record.seed,
        )
    )
    state.board = {
        (tile.q, tile.r): Tile(
            base_terrain=TerrainType(tile.base_terrain),
            occupant=OccupantType(tile.occupant),
        )
        for tile in record.final_map
    }
    return state
