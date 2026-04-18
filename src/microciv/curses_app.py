"""curses application and controller for MicroCiv."""

from __future__ import annotations

import curses
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from microciv.config import AppPaths, build_app_paths
from microciv.game.actions import Action, validate_action
from microciv.game.enums import (
    BuildingType,
    MapDifficulty,
    Mode,
    OccupantType,
    PlaybackMode,
    PolicyType,
    TechType,
    TerrainType,
)
from microciv.game.models import GameConfig, Tile
from microciv.records import RecordDatabase, RecordEntry, RecordStore, export_records_json
from microciv.session import GameSession, create_game_session, selected_city_id_for_coord
from microciv.tui.pixel_font import (
    GLYPH_HEIGHT,
    GLYPH_STRIDE,
)
from microciv.tui.pixel_font import (
    render_number as pixel_render_number,
)
from microciv.tui.pixel_font import (
    render_text as pixel_render_text,
)
from microciv.utils.grid import Coord, coord_sort_key

if TYPE_CHECKING:
    from _curses import window as CursesWindow


BLOCK_FULL = "█"
BLOCK_DARK = "▓"
BLOCK_LIGHT = "░"

TILE_WIDTH_COLS = 4
TILE_HEIGHT_ROWS = 2

PANEL_WIDTH = 34
SCORE_LABEL_Y = 2
SCORE_VALUE_Y = 3
TURN_LABEL_Y = 9
TURN_VALUE_Y = 10
SUBPANEL_START_Y = 16

RECORDS_COLS = 2
RECORDS_ROWS = 6
RECORDS_PAGE_SIZE = RECORDS_COLS * RECORDS_ROWS
MAP_SIZE_OPTIONS = (12, 16, 20, 24)
TURN_LIMIT_OPTIONS = (30, 50, 80, 100, 150)


class ScreenRoute(StrEnum):
    MAIN_MENU = "main_menu"
    SETUP_PLAY = "setup_play"
    SETUP_AUTOPLAY = "setup_autoplay"
    MANUAL_GAME = "manual_game"
    AUTOPLAY_GAME = "autoplay_game"
    CITY_PANEL = "city_panel"
    BUILD_SUBPANEL = "build_subpanel"
    TECH_SUBPANEL = "tech_subpanel"
    GAME_MENU = "game_menu"
    MANUAL_FINAL = "manual_final"
    AUTO_FINAL = "auto_final"
    RECORDS_GRID = "records_grid"
    RECORD_DETAIL_MAP = "record_detail_map"
    NO_RECORDS = "no_records"


class SettlementType(StrEnum):
    CITY = "city"
    ROAD = "road"


@dataclass(slots=True)
class Rect:
    x: int
    y: int
    width: int
    height: int = 1

    def contains(self, point_x: int, point_y: int) -> bool:
        return self.x <= point_x < self.x + self.width and self.y <= point_y < self.y + self.height


@dataclass(slots=True)
class SetupState:
    autoplay: bool
    config: GameConfig


@dataclass(slots=True)
class RenderState:
    button_regions: dict[str, Rect] = field(default_factory=dict)
    map_regions: dict[Coord, Rect] = field(default_factory=dict)

    def clear(self) -> None:
        self.button_regions.clear()
        self.map_regions.clear()


class MicroCivController:
    """UI-agnostic controller that drives the curses presentation."""

    def __init__(self, *, paths: AppPaths | None = None) -> None:
        self.paths = paths or build_app_paths()
        self.record_store = RecordStore(self.paths.records_file)
        self.records = RecordDatabase()
        self.active_session: GameSession | None = None
        self.current_route = ScreenRoute.MAIN_MENU
        self._resume_route = ScreenRoute.MANUAL_GAME
        self.setup_state = SetupState(autoplay=False, config=GameConfig.for_play())
        self.message = ""
        self.selected_record: RecordEntry | None = None
        self.records_scroll = 0
        self.detail_scroll = 0
        self.should_exit = False
        self.selected_settlement_type = SettlementType.CITY
        self.selected_building_type = BuildingType.FARM
        self.selected_tech_type = TechType.AGRICULTURE
        self.reload_records()

    def reload_records(self) -> RecordDatabase:
        self.records = self.record_store.load()
        return self.records

    def sorted_records(self) -> list[RecordEntry]:
        return sorted(
            self.records.records,
            key=lambda record: (record.timestamp, record.record_id),
            reverse=True,
        )

    def visible_records(self) -> list[RecordEntry]:
        start = self.records_scroll * RECORDS_COLS
        return self.sorted_records()[start : start + RECORDS_PAGE_SIZE]

    def max_records_scroll(self) -> int:
        total_rows = (len(self.sorted_records()) + RECORDS_COLS - 1) // RECORDS_COLS
        return max(total_rows - RECORDS_ROWS, 0)

    def scroll_records(self, delta_rows: int) -> None:
        if self.current_route is not ScreenRoute.RECORDS_GRID:
            return
        self.records_scroll = max(
            0,
            min(self.records_scroll + delta_rows, self.max_records_scroll()),
        )

    def jump_records_top(self) -> None:
        if self.current_route is ScreenRoute.RECORDS_GRID:
            self.records_scroll = 0

    def jump_records_bottom(self) -> None:
        if self.current_route is ScreenRoute.RECORDS_GRID:
            self.records_scroll = self.max_records_scroll()

    def open_setup_for_play(self) -> None:
        self.setup_state = SetupState(autoplay=False, config=GameConfig.for_play())
        self.current_route = ScreenRoute.SETUP_PLAY
        self.message = ""

    def open_setup_for_autoplay(self) -> None:
        self.setup_state = SetupState(autoplay=True, config=GameConfig.for_autoplay())
        self.current_route = ScreenRoute.SETUP_AUTOPLAY
        self.message = ""

    def open_records(self) -> None:
        self.reload_records()
        self.selected_record = None
        self.records_scroll = 0
        self.detail_scroll = 0
        self.message = ""
        if not self.records.records:
            self.current_route = ScreenRoute.NO_RECORDS
            return
        self.current_route = ScreenRoute.RECORDS_GRID

    def open_record_detail(self, record: RecordEntry) -> None:
        self.selected_record = record
        self.detail_scroll = 0
        self.current_route = ScreenRoute.RECORD_DETAIL_MAP
        self.message = ""

    def export_records(self) -> None:
        if not self.records.records:
            self.message = "No records to export."
            return
        exported = RecordDatabase(
            schema_version=self.records.schema_version,
            next_record_id=self.records.next_record_id,
            records=self.sorted_records(),
        )
        path = export_records_json(exported, self.paths.exports_dir)
        self.message = f"Exported {path.name}"

    def delete_all_records(self) -> None:
        self.record_store.clear()
        self.reload_records()
        self.selected_record = None
        self.records_scroll = 0
        self.current_route = ScreenRoute.NO_RECORDS
        self.message = "Deleted all records."

    def delete_selected_record(self) -> None:
        if self.selected_record is None:
            return
        deleted = self.record_store.delete_record(self.selected_record.record_id)
        self.reload_records()
        self.selected_record = None
        if not deleted:
            self.message = "Record not found."
            self.open_records()
            return
        self.message = "Deleted record."
        if not self.records.records:
            self.current_route = ScreenRoute.NO_RECORDS
        else:
            self.current_route = ScreenRoute.RECORDS_GRID
            self.records_scroll = min(self.records_scroll, self.max_records_scroll())

    def start_session(self, config: GameConfig) -> None:
        self.active_session = create_game_session(config)
        self._reset_subpanel_selections()
        self.message = ""
        if config.mode is Mode.PLAY:
            self.current_route = ScreenRoute.MANUAL_GAME
            self._resume_route = ScreenRoute.MANUAL_GAME
        else:
            self.current_route = ScreenRoute.AUTOPLAY_GAME
            self._resume_route = ScreenRoute.AUTOPLAY_GAME

    def open_game_menu(self) -> None:
        if self.active_session is None:
            return
        if self.current_route in {
            ScreenRoute.MANUAL_GAME,
            ScreenRoute.AUTOPLAY_GAME,
            ScreenRoute.CITY_PANEL,
            ScreenRoute.BUILD_SUBPANEL,
            ScreenRoute.TECH_SUBPANEL,
        }:
            self._resume_route = self.current_route
            self.current_route = ScreenRoute.GAME_MENU

    def resume_game(self) -> None:
        if self.active_session is None:
            return
        self.current_route = self._resume_route

    def restart_current_config(self) -> None:
        if self.active_session is None:
            return
        config = self.active_session.state.config
        self.active_session = None
        self.message = ""
        if config.mode is Mode.PLAY:
            self.setup_state = SetupState(
                autoplay=False,
                config=GameConfig.for_play(
                    map_size=config.map_size,
                    turn_limit=config.turn_limit,
                    map_difficulty=config.map_difficulty,
                    seed=config.seed,
                ),
            )
            self.current_route = ScreenRoute.SETUP_PLAY
        else:
            self.setup_state = SetupState(
                autoplay=True,
                config=GameConfig.for_autoplay(
                    map_size=config.map_size,
                    turn_limit=config.turn_limit,
                    map_difficulty=config.map_difficulty,
                    policy_type=config.policy_type,
                    playback_mode=config.playback_mode,
                    seed=config.seed,
                ),
            )
            self.current_route = ScreenRoute.SETUP_AUTOPLAY

    def return_to_menu(self) -> None:
        self.active_session = None
        self.selected_record = None
        self.current_route = ScreenRoute.MAIN_MENU
        self.message = ""

    def advance_autoplay(self, *, max_steps: int | None = None) -> None:
        if (
            self.active_session is None
            or self.active_session.state.config.mode is not Mode.AUTOPLAY
            or self.current_route is not ScreenRoute.AUTOPLAY_GAME
        ):
            return
        steps = 0
        while (
            self.current_route is ScreenRoute.AUTOPLAY_GAME
            and not self.active_session.state.is_game_over
        ):
            self.active_session.step_autoplay()
            self._complete_session_if_needed()
            steps += 1
            if max_steps is not None and steps >= max_steps:
                break

    def select_coord(self, coord: Coord) -> None:
        if self.active_session is None or self.active_session.state.config.mode is not Mode.PLAY:
            return
        selection = self.active_session.state.selection
        if selection.selected_coord == coord:
            selection.clear()
            self.current_route = ScreenRoute.MANUAL_GAME
            return
        selection.selected_coord = coord
        selection.selected_city_id = selected_city_id_for_coord(self.active_session.state, coord)
        self.message = ""
        if selection.selected_city_id is not None:
            self.current_route = ScreenRoute.CITY_PANEL
            self._reset_subpanel_selections()
            return
        self.current_route = ScreenRoute.MANUAL_GAME
        self.selected_settlement_type = SettlementType.CITY

    def click(self, element_id: str) -> None:
        if element_id == "menu-play":
            self.open_setup_for_play()
            return
        if element_id == "menu-autoplay":
            self.open_setup_for_autoplay()
            return
        if element_id == "menu-records":
            self.open_records()
            return
        if element_id == "menu-exit":
            self.should_exit = True
            return

        if element_id.startswith("record-slot-"):
            slot_index = int(element_id.removeprefix("record-slot-"))
            visible = self.visible_records()
            if 0 <= slot_index < len(visible):
                self.open_record_detail(visible[slot_index])
            return

        if self.current_route in {ScreenRoute.SETUP_PLAY, ScreenRoute.SETUP_AUTOPLAY}:
            self._click_setup(element_id)
            return
        if self.current_route is ScreenRoute.MANUAL_GAME:
            self._click_manual_game(element_id)
            return
        if self.current_route is ScreenRoute.CITY_PANEL:
            self._click_city_panel(element_id)
            return
        if self.current_route is ScreenRoute.BUILD_SUBPANEL:
            self._click_build_subpanel(element_id)
            return
        if self.current_route is ScreenRoute.TECH_SUBPANEL:
            self._click_tech_subpanel(element_id)
            return
        if self.current_route is ScreenRoute.GAME_MENU:
            self._click_game_menu(element_id)
            return
        if self.current_route in {ScreenRoute.MANUAL_FINAL, ScreenRoute.AUTO_FINAL}:
            self._click_final(element_id)
            return
        if self.current_route is ScreenRoute.RECORDS_GRID:
            if element_id == "records-export":
                self.export_records()
            elif element_id == "records-delete-all":
                self.delete_all_records()
            elif element_id == "records-back":
                self.return_to_menu()
            return
        if self.current_route is ScreenRoute.RECORD_DETAIL_MAP:
            if element_id == "record-detail-back":
                self.open_records()
            elif element_id == "record-detail-menu":
                self.return_to_menu()
            elif element_id == "record-detail-delete":
                self.delete_selected_record()
            return
        if self.current_route is ScreenRoute.NO_RECORDS and element_id == "no-records-back":
            self.return_to_menu()

    def press_key(self, key: str) -> None:
        normalized = key.lower()
        if normalized == "q":
            self.should_exit = True
            return
        if normalized == "m":
            if self.current_route is ScreenRoute.GAME_MENU:
                self.resume_game()
            else:
                self.open_game_menu()
            return
        if normalized == "b":
            self._go_back()
            return
        if normalized == "t":
            self.jump_records_top()
            return
        if normalized == "d":
            self.jump_records_bottom()
            return
        if key in ("KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT"):
            self._navigate_options(key)

    def preview_board(self) -> dict[Coord, Tile]:
        preview_session = create_game_session(self.setup_state.config)
        return preview_session.state.board

    def visible_record_ids(self) -> list[int]:
        return [record.record_id for record in self.visible_records()]

    def _go_back(self) -> None:
        self.message = ""
        if self.current_route is ScreenRoute.RECORD_DETAIL_MAP:
            self.open_records()
        elif self.current_route in {ScreenRoute.RECORDS_GRID, ScreenRoute.NO_RECORDS}:
            self.return_to_menu()
        elif self.current_route is ScreenRoute.BUILD_SUBPANEL:
            self.current_route = ScreenRoute.CITY_PANEL
        elif self.current_route is ScreenRoute.TECH_SUBPANEL:
            self.current_route = ScreenRoute.CITY_PANEL
        elif self.current_route is ScreenRoute.CITY_PANEL and self.active_session is not None:
            self.active_session.state.selection.clear()
            self.current_route = ScreenRoute.MANUAL_GAME

    def _navigate_options(self, key: str) -> None:
        if self.current_route is ScreenRoute.RECORDS_GRID:
            if key == "KEY_UP":
                self.scroll_records(-1)
            elif key == "KEY_DOWN":
                self.scroll_records(1)
            return

        if self.current_route in {
            ScreenRoute.MANUAL_GAME,
            ScreenRoute.CITY_PANEL,
            ScreenRoute.BUILD_SUBPANEL,
            ScreenRoute.TECH_SUBPANEL,
        } and self.active_session is not None:
            if self.current_route in {ScreenRoute.MANUAL_GAME, ScreenRoute.CITY_PANEL}:
                self._navigate_map_selection(key)
                return
            if self.current_route is ScreenRoute.BUILD_SUBPANEL:
                buildings = list(BuildingType)
                idx = buildings.index(self.selected_building_type)
                if key in ("KEY_DOWN", "KEY_RIGHT"):
                    idx = (idx + 1) % len(buildings)
                elif key in ("KEY_UP", "KEY_LEFT"):
                    idx = (idx - 1) % len(buildings)
                self.selected_building_type = buildings[idx]
                return
            if self.current_route is ScreenRoute.TECH_SUBPANEL:
                techs = list(TechType)
                idx = techs.index(self.selected_tech_type)
                if key in ("KEY_DOWN", "KEY_RIGHT"):
                    idx = (idx + 1) % len(techs)
                elif key in ("KEY_UP", "KEY_LEFT"):
                    idx = (idx - 1) % len(techs)
                city_id = self.active_session.state.selection.selected_city_id
                if city_id is None:
                    return
                unlocked = self.active_session.state.networks[
                    self.active_session.state.cities[city_id].network_id
                ].unlocked_techs
                for _ in range(len(techs)):
                    if techs[idx] not in unlocked:
                        self.selected_tech_type = techs[idx]
                        break
                    idx = (idx + (1 if key in ("KEY_DOWN", "KEY_RIGHT") else -1)) % len(techs)

    def _navigate_map_selection(self, key: str) -> None:
        if self.active_session is None:
            return
        coords = sorted(self.active_session.state.board, key=coord_sort_key)
        if not coords:
            return
        selection = self.active_session.state.selection
        selected = selection.selected_coord or coords[0]
        dx, dy = 0, 0
        if key == "KEY_UP":
            dy = -1
        elif key == "KEY_DOWN":
            dy = 1
        elif key == "KEY_LEFT":
            dx = -1
        elif key == "KEY_RIGHT":
            dx = 1
        candidate = (selected[0] + dx, selected[1] + dy)
        if candidate in self.active_session.state.board:
            self.select_coord(candidate)

    def _click_setup(self, element_id: str) -> None:
        config = self.setup_state.config
        if element_id == "setup-difficulty":
            difficulty = (
                MapDifficulty.HARD
                if config.map_difficulty is MapDifficulty.NORMAL
                else MapDifficulty.NORMAL
            )
            self._replace_setup_config(map_difficulty=difficulty)
        elif element_id == "setup-ai-type" and self.setup_state.autoplay:
            policies = [PolicyType.GREEDY, PolicyType.RANDOM]
            next_policy = policies[(policies.index(config.policy_type) + 1) % len(policies)]
            self._replace_setup_config(policy_type=next_policy)
        elif element_id == "setup-playback" and self.setup_state.autoplay:
            next_playback = (
                PlaybackMode.SPEED
                if config.playback_mode is PlaybackMode.NORMAL
                else PlaybackMode.NORMAL
            )
            self._replace_setup_config(playback_mode=next_playback)
        elif element_id == "setup-map-size":
            next_map_size = _cycle_option(config.map_size, MAP_SIZE_OPTIONS)
            self._replace_setup_config(map_size=next_map_size)
        elif element_id == "setup-turn-limit":
            next_turn_limit = _cycle_option(config.turn_limit, TURN_LIMIT_OPTIONS)
            self._replace_setup_config(turn_limit=next_turn_limit)
        elif element_id == "setup-recreate":
            self._replace_setup_config(seed=config.seed + 1)
        elif element_id == "setup-start":
            self.start_session(self.setup_state.config)
        elif element_id == "setup-menu":
            self.return_to_menu()

    def _replace_setup_config(self, **changes: object) -> None:
        config = self.setup_state.config
        map_size = cast(int, changes.get("map_size", config.map_size))
        turn_limit = cast(int, changes.get("turn_limit", config.turn_limit))
        map_difficulty = cast(
            MapDifficulty,
            changes.get("map_difficulty", config.map_difficulty),
        )
        seed = cast(int, changes.get("seed", config.seed))
        if self.setup_state.autoplay:
            policy_type = cast(
                PolicyType,
                changes.get("policy_type", config.policy_type),
            )
            playback_mode = cast(
                PlaybackMode,
                changes.get("playback_mode", config.playback_mode),
            )
            self.setup_state.config = GameConfig.for_autoplay(
                map_size=map_size,
                turn_limit=turn_limit,
                map_difficulty=map_difficulty,
                policy_type=policy_type,
                playback_mode=playback_mode,
                seed=seed,
            )
        else:
            self.setup_state.config = GameConfig.for_play(
                map_size=map_size,
                turn_limit=turn_limit,
                map_difficulty=map_difficulty,
                seed=seed,
            )

    def _click_manual_game(self, element_id: str) -> None:
        if self.active_session is None:
            return
        state = self.active_session.state
        selected_coord = state.selection.selected_coord
        if element_id == "game-skip":
            self._apply_action(Action.skip())
            return
        if element_id == "settle-city":
            self.selected_settlement_type = SettlementType.CITY
            return
        if element_id == "settle-road":
            self.selected_settlement_type = SettlementType.ROAD
            return
        if element_id == "settle-build" and selected_coord is not None:
            action = (
                Action.build_city(selected_coord)
                if self.selected_settlement_type is SettlementType.CITY
                else Action.build_road(selected_coord)
            )
            validation = validate_action(state, action)
            if not validation.is_valid:
                self.message = validation.message
                return
            self._apply_action(action)
            return
        if element_id == "settle-cancel":
            state.selection.clear()
            self.message = ""
            self.current_route = ScreenRoute.MANUAL_GAME

    def _click_city_panel(self, element_id: str) -> None:
        self.message = ""
        if element_id == "city-buildings":
            self.selected_building_type = BuildingType.FARM
            self.current_route = ScreenRoute.BUILD_SUBPANEL
        elif element_id == "city-technologies":
            self.selected_tech_type = TechType.AGRICULTURE
            self.current_route = ScreenRoute.TECH_SUBPANEL

    def _click_build_subpanel(self, element_id: str) -> None:
        if self.active_session is None:
            return
        for building_type in BuildingType:
            if element_id == f"build-opt-{building_type.value}":
                self.selected_building_type = building_type
                return
        if element_id == "build-build":
            city_id = self.active_session.state.selection.selected_city_id
            if city_id is None:
                self.current_route = ScreenRoute.MANUAL_GAME
                return
            action = Action.build_building(city_id, self.selected_building_type)
            validation = validate_action(self.active_session.state, action)
            if validation.is_valid:
                self._apply_action(action)
            else:
                self.message = validation.message
                self.current_route = ScreenRoute.CITY_PANEL
            return
        if element_id == "build-cancel":
            self.message = ""
            self.current_route = ScreenRoute.CITY_PANEL

    def _click_tech_subpanel(self, element_id: str) -> None:
        if self.active_session is None:
            return
        city_id = self.active_session.state.selection.selected_city_id
        if city_id is None:
            self.current_route = ScreenRoute.MANUAL_GAME
            return
        network_id = self.active_session.state.cities[city_id].network_id
        unlocked = self.active_session.state.networks[network_id].unlocked_techs
        for tech_type in TechType:
            if element_id == f"tech-opt-{tech_type.value}":
                if tech_type not in unlocked:
                    self.selected_tech_type = tech_type
                return
        if element_id == "tech-research":
            action = Action.research_tech(city_id, self.selected_tech_type)
            validation = validate_action(self.active_session.state, action)
            if validation.is_valid:
                self._apply_action(action)
            else:
                self.message = validation.message
                self.current_route = ScreenRoute.CITY_PANEL
            return
        if element_id == "tech-cancel":
            self.message = ""
            self.current_route = ScreenRoute.CITY_PANEL

    def _apply_action(self, action: Action) -> None:
        if self.active_session is None:
            return
        validation = validate_action(self.active_session.state, action)
        if not validation.is_valid:
            self.message = validation.message
            return
        self.active_session.apply_action(action)
        self.active_session.state.selection.clear()
        self._reset_subpanel_selections()
        self.message = ""
        self.current_route = ScreenRoute.MANUAL_GAME
        self._complete_session_if_needed()

    def _click_game_menu(self, element_id: str) -> None:
        if element_id == "game-menu-resume":
            self.resume_game()
        elif element_id == "game-menu-restart":
            self.restart_current_config()
        elif element_id == "game-menu-main":
            self.return_to_menu()
        elif element_id == "game-menu-exit":
            self.should_exit = True

    def _click_final(self, element_id: str) -> None:
        if element_id == "final-restart":
            self.restart_current_config()
        elif element_id == "final-menu":
            self.return_to_menu()
        elif element_id == "final-exit":
            self.should_exit = True

    def _complete_session_if_needed(self) -> None:
        if self.active_session is None or not self.active_session.state.is_game_over:
            return
        if self.active_session.saved_record is None:
            self.active_session.saved_record = self.record_store.append_completed_game(
                self.active_session.state
            )
            self.reload_records()
        self.current_route = (
            ScreenRoute.AUTO_FINAL
            if self.active_session.state.config.mode is Mode.AUTOPLAY
            else ScreenRoute.MANUAL_FINAL
        )

    def _reset_subpanel_selections(self) -> None:
        self.selected_settlement_type = SettlementType.CITY
        self.selected_building_type = BuildingType.FARM
        self.selected_tech_type = TechType.AGRICULTURE

    def _has_valid_settlement_actions(self, coord: Coord) -> bool:
        if self.active_session is None:
            return False
        state = self.active_session.state
        return (
            validate_action(state, Action.build_city(coord)).is_valid
            or validate_action(state, Action.build_road(coord)).is_valid
        )

    def _can_build_city_at_selection(self) -> bool:
        if self.active_session is None:
            return False
        coord = self.active_session.state.selection.selected_coord
        if coord is None:
            return False
        return validate_action(self.active_session.state, Action.build_city(coord)).is_valid

    def _can_build_road_at_selection(self) -> bool:
        if self.active_session is None:
            return False
        coord = self.active_session.state.selection.selected_coord
        if coord is None:
            return False
        return validate_action(self.active_session.state, Action.build_road(coord)).is_valid

    def available_game_actions(self) -> list[str]:
        if self.active_session is None:
            return []
        state = self.active_session.state
        selection = state.selection
        actions: list[str] = []
        if state.config.mode is Mode.PLAY:
            actions.append("game-skip")
        if (
            selection.selected_coord is not None
            and self._has_valid_settlement_actions(selection.selected_coord)
        ):
            if validate_action(state, Action.build_city(selection.selected_coord)).is_valid:
                actions.append("settle-city")
            if validate_action(state, Action.build_road(selection.selected_coord)).is_valid:
                actions.append("settle-road")
        if selection.selected_city_id is not None:
            actions.extend(["city-buildings", "city-technologies"])
        return actions


class CursesMicroCivApp:
    """Thin curses wrapper around the controller."""

    def __init__(self, *, paths: AppPaths | None = None) -> None:
        self.controller = MicroCivController(paths=paths)
        self.render_state = RenderState()
        self._color_pairs: dict[str, int] = {}
        self._blink_visible = True
        self._frame_counter = 0
        self._last_step_time = 0.0

    def run(self) -> None:
        curses.wrapper(self._main)

    def _main(self, stdscr: CursesWindow) -> None:
        curses.curs_set(0)
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        curses.start_color()
        curses.use_default_colors()
        self._init_colors()
        stdscr.timeout(100)

        while not self.controller.should_exit:
            self._frame_counter += 1
            self._blink_visible = (self._frame_counter // 3) % 2 == 0
            self._render(stdscr)
            if (
                self.controller.current_route is ScreenRoute.AUTOPLAY_GAME
                and self.controller.active_session is not None
            ):
                now = time.monotonic()
                playback = self.controller.active_session.state.config.playback_mode
                if playback is PlaybackMode.SPEED:
                    self.controller.advance_autoplay(max_steps=1)
                else:
                    if now - self._last_step_time >= 0.20:
                        self.controller.advance_autoplay(max_steps=1)
                        self._last_step_time = now
                key = stdscr.getch()
                if key != -1:
                    self._handle_input(key)
                continue
            key = stdscr.getch()
            if key == -1:
                continue
            self._handle_input(key)

    def _init_colors(self) -> None:
        pairs = {
            "plain": (curses.COLOR_GREEN, curses.COLOR_GREEN),
            "forest": (curses.COLOR_BLACK, curses.COLOR_GREEN),
            "mountain": (curses.COLOR_WHITE, curses.COLOR_BLACK),
            "river": (curses.COLOR_BLUE, curses.COLOR_BLUE),
            "wasteland": (curses.COLOR_YELLOW, curses.COLOR_YELLOW),
            "city": (curses.COLOR_RED, curses.COLOR_RED),
            "road": (curses.COLOR_BLACK, curses.COLOR_YELLOW),
            "selected": (curses.COLOR_BLACK, curses.COLOR_WHITE),
            "text": (curses.COLOR_WHITE, -1),
            "accent": (curses.COLOR_CYAN, -1),
            "dim_text": (curses.COLOR_WHITE, -1),
            "highlight_text": (curses.COLOR_YELLOW, -1),
            "button_border": (curses.COLOR_WHITE, -1),
            "pixel_red": (curses.COLOR_RED, -1),
        }
        pair_id = 1
        for name, (fg, bg) in pairs.items():
            curses.init_pair(pair_id, fg, bg)
            self._color_pairs[name] = pair_id
            pair_id += 1

    def _attr(self, color_name: str, extra: int = curses.A_NORMAL) -> int:
        return curses.color_pair(self._color_pairs[color_name]) | extra

    def _handle_input(self, key: int) -> None:
        if key == curses.KEY_MOUSE:
            try:
                _, mouse_x, mouse_y, _, bstate = curses.getmouse()
            except curses.error:
                return
            self._handle_mouse(mouse_x, mouse_y, bstate)
            return
        key_name = curses.keyname(key).decode("utf-8", errors="ignore")
        if key_name != "^M":
            self.controller.press_key(key_name)

    def _handle_mouse(self, mouse_x: int, mouse_y: int, bstate: int) -> None:
        if bstate & getattr(curses, "BUTTON4_PRESSED", 0):
            self.controller.scroll_records(-1)
            return
        if bstate & getattr(curses, "BUTTON5_PRESSED", 0):
            self.controller.scroll_records(1)
            return
        if (
            self.controller.current_route is ScreenRoute.RECORDS_GRID
            and self.controller.message
        ):
            self.controller.message = ""
        if not (bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED)):
            return
        for button_id, rect in self.render_state.button_regions.items():
            if rect.contains(mouse_x, mouse_y):
                self.controller.click(button_id)
                return
        if self.controller.current_route in {
            ScreenRoute.MANUAL_GAME,
            ScreenRoute.CITY_PANEL,
            ScreenRoute.BUILD_SUBPANEL,
            ScreenRoute.TECH_SUBPANEL,
        }:
            for coord, rect in self.render_state.map_regions.items():
                if rect.contains(mouse_x, mouse_y):
                    self.controller.select_coord(coord)
                    return

    def _render(self, stdscr: CursesWindow) -> None:
        stdscr.erase()
        self.render_state.clear()
        height, width = stdscr.getmaxyx()
        route = self.controller.current_route
        if route is ScreenRoute.MAIN_MENU:
            self._render_main_menu(stdscr, width, height)
        elif route in {ScreenRoute.SETUP_PLAY, ScreenRoute.SETUP_AUTOPLAY}:
            self._render_setup(stdscr, width, height)
        elif route is ScreenRoute.MANUAL_GAME:
            self._render_manual_game(stdscr, width, height)
        elif route is ScreenRoute.AUTOPLAY_GAME:
            self._render_autoplay_game(stdscr, width, height)
        elif route is ScreenRoute.CITY_PANEL:
            self._render_city_panel(stdscr, width, height)
        elif route is ScreenRoute.BUILD_SUBPANEL:
            self._render_build_subpanel(stdscr, width, height)
        elif route is ScreenRoute.TECH_SUBPANEL:
            self._render_tech_subpanel(stdscr, width, height)
        elif route is ScreenRoute.GAME_MENU:
            self._render_game_menu(stdscr, width, height)
        elif route is ScreenRoute.MANUAL_FINAL:
            self._render_final(stdscr, width, height, is_auto=False)
        elif route is ScreenRoute.AUTO_FINAL:
            self._render_final(stdscr, width, height, is_auto=True)
        elif route is ScreenRoute.RECORDS_GRID:
            self._render_records_grid(stdscr, width, height)
        elif route is ScreenRoute.RECORD_DETAIL_MAP:
            self._render_record_detail(stdscr, width, height)
        elif route is ScreenRoute.NO_RECORDS:
            self._render_no_records(stdscr, width, height)

        stdscr.refresh()

    def _safe_addstr(
        self,
        stdscr: CursesWindow,
        y: int,
        x: int,
        text: str,
        color_name: str,
        extra: int = curses.A_NORMAL,
    ) -> None:
        if y < 0 or x < 0 or not text:
            return
        try:
            stdscr.addstr(y, x, text, self._attr(color_name, extra))
        except curses.error:
            return

    def _draw_box(self, stdscr: CursesWindow, x: int, y: int, w: int, h: int) -> None:
        if w < 2 or h < 2:
            return
        self._safe_addstr(stdscr, y, x, "┌" + "─" * (w - 2) + "┐", "button_border")
        for row in range(y + 1, y + h - 1):
            self._safe_addstr(stdscr, row, x, "│", "button_border")
            self._safe_addstr(stdscr, row, x + w - 1, "│", "button_border")
        self._safe_addstr(stdscr, y + h - 1, x, "└" + "─" * (w - 2) + "┘", "button_border")

    def _draw_box_button(
        self, stdscr: CursesWindow, button_id: str, label: str, x: int, y: int, w: int, h: int = 3
    ) -> None:
        self._draw_box(stdscr, x, y, w, h)
        self._safe_addstr(stdscr, y + h // 2, x + max((w - len(label)) // 2, 1), label, "text")
        self.render_state.button_regions[button_id] = Rect(x, y, w, h)

    def _draw_option(
        self,
        stdscr: CursesWindow,
        option_id: str,
        label: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        selected: bool,
    ) -> None:
        if selected:
            self._draw_box(stdscr, x, y, w, h)
            color_name = "text"
            extra = curses.A_NORMAL
        else:
            color_name = "dim_text"
            extra = curses.A_DIM
        self._safe_addstr(
            stdscr,
            y + h // 2,
            x + max((w - len(label)) // 2, 0),
            label,
            color_name,
            extra,
        )
        self.render_state.button_regions[option_id] = Rect(x, y, w, h)

    def _render_main_menu(self, stdscr: CursesWindow, width: int, height: int) -> None:
        title_text = "MICROCIV"
        title_pixel_w = len(title_text) * GLYPH_STRIDE
        title_x = max((width - title_pixel_w) // 2, 2)
        title_y = 2
        pixel_render_text(stdscr, title_x, title_y, title_text, self._attr("pixel_red"))

        btn_w = 26
        btn_h = 4
        left_x = max(width // 2 - btn_w - 4, 4)
        right_x = min(width - btn_w - 4, width // 2 + 4)
        top_y = title_y + GLYPH_HEIGHT + 3
        bottom_y = top_y + btn_h + 3
        self._draw_box_button(stdscr, "menu-play", "Play", left_x, top_y, btn_w, btn_h)
        self._draw_box_button(stdscr, "menu-autoplay", "AutoPlay", right_x, top_y, btn_w, btn_h)
        self._draw_box_button(stdscr, "menu-records", "Records", left_x, bottom_y, btn_w, btn_h)
        self._draw_box_button(stdscr, "menu-exit", "Exit", right_x, bottom_y, btn_w, btn_h)

    def _render_setup(self, stdscr: CursesWindow, width: int, height: int) -> None:
        config = self.controller.setup_state.config
        is_auto = self.controller.setup_state.autoplay
        panel_x = width - PANEL_WIDTH
        panel_w = 28

        map_display_w = config.map_size * TILE_WIDTH_COLS
        map_display_h = config.map_size * TILE_HEIGHT_ROWS
        board_x = max((panel_x - map_display_w) // 2, 1)
        board_y = max((height - map_display_h) // 2, 1)
        board = self.controller.preview_board()
        self._render_board(stdscr, board, board_x, board_y, None)

        panel_y = 2
        panel_h = 3
        gap = 1
        params: list[tuple[str, str]] = [
            ("setup-difficulty", f"Map Difficulty : {config.map_difficulty.value.title()}"),
            ("setup-map-size", f"Map Size : {config.map_size}"),
            ("setup-turn-limit", f"Turn Limit : {config.turn_limit}"),
        ]
        if is_auto:
            params.append(("setup-playback", f"Playback : {config.playback_mode.value.title()}"))
            params.append(("setup-ai-type", f"AI Type : {_policy_label(config.policy_type)}"))
        for idx, (button_id, label) in enumerate(params):
            btn_y = panel_y + idx * (panel_h + gap)
            self._draw_box_button(
                stdscr, button_id, label, panel_x, btn_y, panel_w, panel_h,
            )

        self._draw_box_button(stdscr, "setup-menu", "Menu", panel_x, height - 12, panel_w, 3)
        self._draw_box_button(stdscr, "setup-recreate", "Recreate", panel_x, height - 8, panel_w, 3)
        self._draw_box_button(stdscr, "setup-start", "Start", panel_x, height - 4, panel_w, 3)

    def _render_manual_game(self, stdscr: CursesWindow, width: int, height: int) -> None:
        self._render_game_shell(stdscr, width, height)
        if self.controller.active_session is None:
            return
        state = self.controller.active_session.state
        selection = state.selection
        panel_x = width - PANEL_WIDTH
        has_settlement = (
            selection.selected_coord is not None
            and selection.selected_city_id is None
            and self.controller._has_valid_settlement_actions(selection.selected_coord)
        )
        if has_settlement:
            self._render_settlement_panel(stdscr, width, height)
        else:
            self._draw_box_button(stdscr, "game-skip", "Skip", panel_x, height - 7, 30, 3)
        if self.controller.message:
            self._safe_addstr(stdscr, height - 3, panel_x, self.controller.message[:30], "accent")

    def _render_autoplay_game(self, stdscr: CursesWindow, width: int, height: int) -> None:
        self._render_game_shell(stdscr, width, height)
        if self.controller.active_session is None:
            return
        state = self.controller.active_session.state
        panel_x = width - PANEL_WIDTH
        self._safe_addstr(
            stdscr, height - 4, panel_x,
            f"AI Type : {_policy_label(state.config.policy_type)}", "accent",
        )
        self._safe_addstr(
            stdscr, height - 3, panel_x,
            f"Playback : {state.config.playback_mode.value.title()}", "accent",
        )

    def _render_game_map_only(self, stdscr: CursesWindow, width: int, height: int) -> None:
        """Render only the map, without Score/Turn."""
        if self.controller.active_session is None:
            return
        state = self.controller.active_session.state
        panel_x = width - PANEL_WIDTH
        map_display_w = state.config.map_size * TILE_WIDTH_COLS
        map_display_h = state.config.map_size * TILE_HEIGHT_ROWS
        board_x = max((panel_x - map_display_w) // 2, 1)
        board_y = max((height - map_display_h) // 2, 1)
        self._render_board(stdscr, state.board, board_x, board_y, state.selection.selected_coord)

    def _render_game_shell(self, stdscr: CursesWindow, width: int, height: int) -> None:
        if self.controller.active_session is None:
            return
        state = self.controller.active_session.state
        panel_x = width - PANEL_WIDTH
        map_display_w = state.config.map_size * TILE_WIDTH_COLS
        map_display_h = state.config.map_size * TILE_HEIGHT_ROWS
        board_x = max((panel_x - map_display_w) // 2, 1)
        board_y = max((height - map_display_h) // 2, 1)
        self._render_board(stdscr, state.board, board_x, board_y, state.selection.selected_coord)
        self._safe_addstr(stdscr, SCORE_LABEL_Y, panel_x, "Score", "text")
        pixel_render_number(
            stdscr, panel_x, SCORE_VALUE_Y, state.score, 4,
            color_pair=self._attr("pixel_red"),
        )
        self._safe_addstr(stdscr, TURN_LABEL_Y, panel_x, "Turn", "text")
        pixel_render_number(
            stdscr, panel_x, TURN_VALUE_Y, state.turn, 3,
            color_pair=self._attr("pixel_red"),
        )

    def _render_settlement_panel(self, stdscr: CursesWindow, width: int, height: int) -> None:
        panel_x = width - PANEL_WIDTH
        panel_y = SUBPANEL_START_Y
        option_w = 14
        can_city = self.controller._can_build_city_at_selection()
        can_road = self.controller._can_build_road_at_selection()
        if can_city and can_road:
            self._draw_option(
                stdscr, "settle-city", "City", panel_x, panel_y, option_w, 3,
                selected=self.controller.selected_settlement_type is SettlementType.CITY,
            )
            self._draw_option(
                stdscr, "settle-road", "Road", panel_x + option_w + 2, panel_y, option_w, 3,
                selected=self.controller.selected_settlement_type is SettlementType.ROAD,
            )
        elif can_city:
            self.controller.selected_settlement_type = SettlementType.CITY
            self._draw_option(
                stdscr, "settle-city", "City", panel_x, panel_y, option_w, 3, selected=True,
            )
        elif can_road:
            self.controller.selected_settlement_type = SettlementType.ROAD
            self._draw_option(
                stdscr, "settle-road", "Road", panel_x, panel_y, option_w, 3, selected=True,
            )
        self._draw_box_button(stdscr, "settle-build", "Build", panel_x, panel_y + 5, 30, 3)
        self._draw_box_button(stdscr, "settle-cancel", "Cancel", panel_x, panel_y + 9, 30, 3)

    def _render_city_panel(self, stdscr: CursesWindow, width: int, height: int) -> None:
        self._render_game_shell(stdscr, width, height)
        if self.controller.active_session is None:
            return
        state = self.controller.active_session.state
        city_id = state.selection.selected_city_id
        if city_id is None:
            self.controller.current_route = ScreenRoute.MANUAL_GAME
            return
        network = state.networks[state.cities[city_id].network_id]
        panel_x = width - PANEL_WIDTH
        resources = [
            ("Food", network.resources.food),
            ("Wood", network.resources.wood),
            ("Ore", network.resources.ore),
            ("Sci", network.resources.science),
        ]
        for idx, (label, amount) in enumerate(resources):
            row = idx // 2
            col = idx % 2
            x = panel_x + col * 16
            y = SUBPANEL_START_Y + row * 3
            self._safe_addstr(stdscr, y, x, f"{label} : {amount}", "text")
        bld_y = SUBPANEL_START_Y + 8
        self._draw_box_button(stdscr, "city-buildings", "Buildings", panel_x, bld_y, 30, 3)
        tech_y = SUBPANEL_START_Y + 12
        self._draw_box_button(
            stdscr, "city-technologies", "Technologies", panel_x, tech_y, 30, 3,
        )
        if self.controller.message:
            self._safe_addstr(stdscr, height - 3, panel_x, self.controller.message[:30], "accent")

    def _render_build_subpanel(self, stdscr: CursesWindow, width: int, height: int) -> None:
        self._render_game_map_only(stdscr, width, height)
        if self.controller.active_session is None:
            return
        state = self.controller.active_session.state
        city_id = state.selection.selected_city_id
        if city_id is None:
            self.controller.current_route = ScreenRoute.MANUAL_GAME
            return
        city = state.cities[city_id]
        panel_x = width - PANEL_WIDTH
        labels = [
            (BuildingType.FARM, f"Farm : {city.buildings.farm}"),
            (BuildingType.LUMBER_MILL, f"Lumberyard : {city.buildings.lumber_mill}"),
            (BuildingType.MINE, f"Mine : {city.buildings.mine}"),
            (BuildingType.LIBRARY, f"Library : {city.buildings.library}"),
        ]
        for idx, (building_type, label) in enumerate(labels):
            self._draw_option(
                stdscr,
                f"build-opt-{building_type.value}",
                label,
                panel_x,
                4 + idx * 4,
                30,
                3,
                selected=self.controller.selected_building_type is building_type,
            )
        self._draw_box_button(stdscr, "build-build", "Build", panel_x, 21, 30, 3)
        self._draw_box_button(stdscr, "build-cancel", "Cancel", panel_x, 25, 30, 3)
        if self.controller.message:
            self._safe_addstr(
                stdscr, height - 3, panel_x,
                self.controller.message[:30], "accent",
            )

    def _render_tech_subpanel(self, stdscr: CursesWindow, width: int, height: int) -> None:
        self._render_game_map_only(stdscr, width, height)
        if self.controller.active_session is None:
            return
        state = self.controller.active_session.state
        city_id = state.selection.selected_city_id
        if city_id is None:
            self.controller.current_route = ScreenRoute.MANUAL_GAME
            return
        unlocked = state.networks[state.cities[city_id].network_id].unlocked_techs
        panel_x = width - PANEL_WIDTH
        items = [
            (TechType.AGRICULTURE, "Agriculture"),
            (TechType.LOGGING, "Logging"),
            (TechType.MINING, "Mining"),
            (TechType.EDUCATION, "Education"),
        ]
        for idx, (tech_type, label) in enumerate(items):
            row = idx // 2
            col = idx % 2
            x = panel_x + col * 16
            y = 4 + row * 4
            if tech_type in unlocked:
                self._safe_addstr(
                    stdscr, y + 1, x + 1, label,
                    "highlight_text", curses.A_BOLD | curses.A_STANDOUT,
                )
            else:
                self._draw_option(
                    stdscr,
                    f"tech-opt-{tech_type.value}",
                    label,
                    x,
                    y,
                    14,
                    3,
                    selected=self.controller.selected_tech_type is tech_type,
                )
        self._draw_box_button(stdscr, "tech-research", "Research", panel_x, 13, 30, 3)
        self._draw_box_button(stdscr, "tech-cancel", "Cancel", panel_x, 17, 30, 3)
        if self.controller.message:
            self._safe_addstr(
                stdscr, height - 3, panel_x,
                self.controller.message[:30], "accent",
            )

    def _render_game_menu(self, stdscr: CursesWindow, width: int, height: int) -> None:
        title_text = "MICROCIV"
        title_pixel_w = len(title_text) * GLYPH_STRIDE
        title_x = max((width - title_pixel_w) // 2, 2)
        title_y = 2
        pixel_render_text(stdscr, title_x, title_y, title_text, self._attr("pixel_red"))
        btn_w = 26
        btn_h = 4
        left_x = max(width // 2 - btn_w - 4, 4)
        right_x = min(width - btn_w - 4, width // 2 + 4)
        top_y = title_y + GLYPH_HEIGHT + 3
        bottom_y = top_y + btn_h + 3
        self._draw_box_button(
            stdscr, "game-menu-main", "Menu", left_x, top_y, btn_w, btn_h
        )
        self._draw_box_button(
            stdscr, "game-menu-resume", "Resume", right_x, top_y, btn_w, btn_h
        )
        self._draw_box_button(
            stdscr, "game-menu-restart", "Restart", left_x, bottom_y, btn_w, btn_h
        )
        self._draw_box_button(stdscr, "game-menu-exit", "Exit", right_x, bottom_y, btn_w, btn_h)

    def _render_final(
        self,
        stdscr: CursesWindow,
        width: int,
        height: int,
        *,
        is_auto: bool,
    ) -> None:
        if self.controller.active_session is None:
            return
        state = self.controller.active_session.state
        record = self.controller.active_session.saved_record
        panel_x = width - PANEL_WIDTH
        map_display_w = state.config.map_size * TILE_WIDTH_COLS
        map_display_h = state.config.map_size * TILE_HEIGHT_ROWS
        board_x = max((panel_x - map_display_w) // 2, 1)
        board_y = max((height - map_display_h) // 2, 1)
        self._render_board(stdscr, state.board, board_x, board_y, None)
        final_score = record.final_score if record is not None else state.score
        self._safe_addstr(stdscr, 2, panel_x, "Score", "text")
        pixel_render_number(
            stdscr, panel_x, 3, final_score, 4,
            color_pair=self._attr("pixel_red"),
        )
        y = 3 + GLYPH_HEIGHT + 2
        if is_auto and record is not None:
            self._safe_addstr(stdscr, height - 4, panel_x, f"AI Type : {record.ai_type}", "accent")
            playback_label = record.playback_mode.title() if record.playback_mode else "Normal"
            self._safe_addstr(stdscr, height - 3, panel_x, f"Playback : {playback_label}", "accent")
        self._draw_box_button(stdscr, "final-restart", "Restart", panel_x, y, 30, 3)
        self._draw_box_button(stdscr, "final-menu", "Menu", panel_x, y + 4, 30, 3)
        self._draw_box_button(stdscr, "final-exit", "Exit", panel_x, y + 8, 30, 3)

    def _render_records_grid(self, stdscr: CursesWindow, width: int, height: int) -> None:
        visible = self.controller.visible_records()
        slot_w = max((width - 10) // 2 - 2, 24)
        slot_h = 5
        left_x = 3
        right_x = left_x + slot_w + 3
        start_y = 3
        for idx in range(RECORDS_PAGE_SIZE):
            row = idx // RECORDS_COLS
            col = idx % RECORDS_COLS
            x = left_x if col == 0 else right_x
            y = start_y + row * (slot_h + 1)
            if idx >= len(visible):
                continue
            record = visible[idx]
            self._draw_box(stdscr, x, y, slot_w, slot_h)
            rank = self.controller.records_scroll * RECORDS_COLS + idx + 1
            label = _record_list_label(record, rank)
            self._safe_addstr(stdscr, y + 2, x + 1, label[: slot_w - 2], "text")
            self.render_state.button_regions[f"record-slot-{idx}"] = Rect(x, y, slot_w, slot_h)
        bottom_y = height - 5
        self._draw_box_button(stdscr, "records-delete-all", "Delete All", 6, bottom_y, 14, 3)
        export_x = max((width - 14) // 2, 22)
        self._draw_box_button(stdscr, "records-export", "Export", export_x, bottom_y, 14, 3)
        self._draw_box_button(stdscr, "records-back", "Back", max(width - 20, 24), bottom_y, 14, 3)
        if self.controller.message:
            msg = self.controller.message[:40]
            msg_x = max((width - len(msg)) // 2, 0)
            self._safe_addstr(stdscr, bottom_y - 2, msg_x, msg, "accent")

    def _render_record_detail(self, stdscr: CursesWindow, width: int, height: int) -> None:
        record = self.controller.selected_record
        if record is None:
            self.controller.open_records()
            return
        board = _board_from_record(record)
        panel_x = width - 38
        map_size = record.map_size
        map_display_w = map_size * TILE_WIDTH_COLS
        map_display_h = map_size * TILE_HEIGHT_ROWS
        board_x = max((panel_x - map_display_w) // 2, 1)
        board_y = max((height - map_display_h) // 2, 1)
        self._render_board(stdscr, board, board_x, board_y, None)
        lines = _record_detail_lines(record)
        for idx, line in enumerate(lines):
            self._safe_addstr(stdscr, 4 + idx, panel_x, line, "text")
        btn_w = min(16, width - panel_x - 1)
        self._draw_box_button(
            stdscr, "record-detail-back", "Back", panel_x, height - 12, btn_w, 3,
        )
        self._draw_box_button(
            stdscr, "record-detail-menu", "Menu", panel_x, height - 8, btn_w, 3,
        )
        self._draw_box_button(
            stdscr, "record-detail-delete", "Delete", panel_x, height - 4, btn_w, 3,
        )

    def _render_no_records(self, stdscr: CursesWindow, width: int, height: int) -> None:
        text = "No records"
        self._safe_addstr(
            stdscr,
            height // 2 - 2,
            max((width - len(text)) // 2, 0),
            text,
            "text",
        )
        self._draw_box_button(
            stdscr,
            "no-records-back",
            "Back",
            max((width - 14) // 2, 2),
            height // 2 + 1,
            14,
            3,
        )

    def _render_board(
        self,
        stdscr: CursesWindow,
        board: dict[Coord, Tile],
        origin_x: int,
        origin_y: int,
        selected_coord: Coord | None,
    ) -> None:
        for coord in sorted(board, key=coord_sort_key):
            screen_x = origin_x + coord[0] * TILE_WIDTH_COLS
            screen_y = origin_y + coord[1] * TILE_HEIGHT_ROWS
            selected = coord == selected_coord and self._blink_visible
            glyph, color_name = _style_for_tile(board[coord], selected=selected)
            for dy in range(TILE_HEIGHT_ROWS):
                self._safe_addstr(stdscr, screen_y + dy, screen_x, glyph, color_name)
            self.render_state.map_regions[coord] = Rect(
                screen_x, screen_y, TILE_WIDTH_COLS, TILE_HEIGHT_ROWS,
            )


def _style_for_tile(tile: Tile, *, selected: bool) -> tuple[str, str]:
    if tile.occupant is OccupantType.CITY:
        return BLOCK_FULL * TILE_WIDTH_COLS, "selected" if selected else "city"
    if tile.occupant is OccupantType.ROAD:
        return BLOCK_DARK * TILE_WIDTH_COLS, "selected" if selected else "road"
    if tile.base_terrain is TerrainType.PLAIN:
        return BLOCK_FULL * TILE_WIDTH_COLS, "selected" if selected else "plain"
    if tile.base_terrain is TerrainType.FOREST:
        return BLOCK_DARK * TILE_WIDTH_COLS, "selected" if selected else "forest"
    if tile.base_terrain is TerrainType.MOUNTAIN:
        return BLOCK_LIGHT * TILE_WIDTH_COLS, "selected" if selected else "mountain"
    if tile.base_terrain is TerrainType.RIVER:
        return BLOCK_FULL * TILE_WIDTH_COLS, "selected" if selected else "river"
    return BLOCK_FULL * TILE_WIDTH_COLS, "selected" if selected else "wasteland"


def _cycle_option(current: int, options: tuple[int, ...]) -> int:
    try:
        idx = options.index(current)
    except ValueError:
        idx = 0
    return options[(idx + 1) % len(options)]


def _policy_label(policy_type: PolicyType) -> str:
    if policy_type is PolicyType.GREEDY:
        return "Greedy"
    if policy_type is PolicyType.RANDOM:
        return "Random"
    return policy_type.value.title()


def _record_list_label(record: RecordEntry, display_rank: int) -> str:
    actor = record.ai_type if record.mode == "autoplay" else "Human"
    timestamp = record.timestamp.replace("T", " ")[:16]
    return f"#{display_rank}  {timestamp}  {actor}  score={record.final_score}"


def _board_from_record(record: RecordEntry) -> dict[Coord, Tile]:
    board: dict[Coord, Tile] = {}
    for snap in record.final_map:
        board[(snap.x, snap.y)] = Tile(
            base_terrain=TerrainType(snap.base_terrain),
            occupant=OccupantType(snap.occupant),
        )
    return board


def _record_detail_lines(record: RecordEntry) -> list[str]:
    lines = [
        f"Score: {record.final_score}",
        f"Mode: {record.mode}",
        f"Time: {record.timestamp.replace('T', ' ')}",
        f"Difficulty: {record.map_difficulty}",
        f"Map Size: {record.map_size}",
        f"Turn Limit: {record.turn_limit}",
        f"Actual Turns: {record.actual_turns}",
        f"Cities: {record.city_count}",
        f"Buildings: {record.building_count}",
        f"Techs: {record.tech_count}",
        f"Food: {record.food}",
        f"Wood: {record.wood}",
        f"Ore: {record.ore}",
        f"Sci: {record.science}",
    ]
    if record.mode == "autoplay":
        lines.extend(
            [
                f"AI Type: {record.ai_type}",
                f"Playback: {record.playback_mode or 'normal'}",
                f"Turn Time Total: {_fmt_sig3(float(record.turn_elapsed_ms_total))} ms",
                (
                    "Step Avg: "
                    f"{_fmt_sig3(record.turn_elapsed_ms_total / max(record.actual_turns, 1))} ms"
                ),
            ]
        )
    return lines


def _fmt_sig3(value: float) -> str:
    """Format a value with at least 3 significant digits."""
    if value == 0:
        return "0"
    return f"{value:.3g}"
