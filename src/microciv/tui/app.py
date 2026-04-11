"""Textual application entrypoint for MicroCiv."""

from __future__ import annotations

from pathlib import Path

from textual.app import App
from textual.screen import Screen

from microciv.config import AppPaths, build_app_paths
from microciv.game.models import GameConfig
from microciv.records import RecordDatabase, RecordEntry, RecordStore, export_records_csv
from microciv.tui.presenters.game_session import GameSession, create_game_session
from microciv.tui.presenters.state_machine import ScreenRoute, route_for_screen
from microciv.tui.screens.final import FinalScreen
from microciv.tui.screens.game import GameScreen
from microciv.tui.screens.menu import MainMenuScreen
from microciv.tui.screens.records import RecordDetailScreen, RecordsListScreen
from microciv.tui.screens.setup import SetupScreen


class MicroCivApp(App[None]):
    """Full-screen Textual application."""

    CSS = """
    Screen {
        background: #111111;
        color: #f3ead7;
    }

    Button {
        border: none;
        background: #1d1c18;
        color: #f7efdd;
    }

    Button:hover {
        background: #2b2822;
    }
    """

    def __init__(self, *, paths: AppPaths | None = None) -> None:
        super().__init__()
        self.paths = paths or build_app_paths()
        self.record_store = RecordStore(self.paths.records_file)
        self.records = RecordDatabase()
        self.active_session: GameSession | None = None

    @property
    def current_route(self) -> ScreenRoute | None:
        """Return the current top-of-stack route."""
        return route_for_screen(self.screen)

    def on_mount(self) -> None:
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.paths.exports_dir.mkdir(parents=True, exist_ok=True)
        self.reload_records()
        self.push_screen(MainMenuScreen())

    def open_setup_for_play(self) -> None:
        self._clear_active_message()
        self._show_primary_screen(SetupScreen(autoplay=False))

    def open_setup_for_autoplay(self) -> None:
        self._clear_active_message()
        self._show_primary_screen(SetupScreen(autoplay=True))

    def open_setup_for_config(self, config: GameConfig) -> None:
        self._clear_active_message()
        self._show_primary_screen(SetupScreen(autoplay=config.mode.value == "autoplay", initial_config=config))

    def open_records(self) -> None:
        self.reload_records()
        self._show_primary_screen(RecordsListScreen())

    def open_record_detail(self, record: RecordEntry) -> None:
        self._show_primary_screen(RecordDetailScreen(record))

    def start_session(self, config: GameConfig) -> None:
        self.active_session = create_game_session(config)
        self._show_primary_screen(GameScreen(self.active_session))

    def complete_session(self, session: GameSession) -> None:
        if session.saved_record is None:
            session.saved_record = self.record_store.append_completed_game(session.state)
            self.reload_records()
        self._show_primary_screen(FinalScreen(session))

    def restart_from_session(self, session: GameSession) -> None:
        self.active_session = None
        self.open_setup_for_config(session.state.config)

    def reload_records(self) -> RecordDatabase:
        self.records = self.record_store.load()
        return self.records

    def export_records(self) -> Path | None:
        if not self.records.records:
            return None
        return export_records_csv(self.records.records, self.paths.exports_dir)

    def return_to_menu(self) -> None:
        self.active_session = None
        self._show_primary_screen(MainMenuScreen())

    def _clear_active_message(self) -> None:
        if self.active_session is None:
            return
        self.active_session.state.message = ""
        self.active_session.state.selection.clear()

    def _show_primary_screen(self, screen: Screen[object]) -> None:
        # Keep only the implicit root screen at the bottom of the stack.
        # Primary navigation then always pushes a fresh top-level screen,
        # while overlays like the in-game menu can still use push/dismiss.
        if len(self.screen_stack) <= 1:
            self.push_screen(screen)
            return
        self.pop_screen()
        self.call_next(self._show_primary_screen, screen)
