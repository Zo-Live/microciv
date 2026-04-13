"""curses application and controller for MicroCiv."""

from __future__ import annotations

import curses
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

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
from microciv.records import RecordDatabase, RecordEntry, RecordStore, export_records_csv
from microciv.session import GameSession, create_game_session, selected_city_id_for_coord
from microciv.utils.grid import Coord, coord_sort_key

if TYPE_CHECKING:
    from _curses import window as CursesWindow


BLOCK_FULL = "█"
BLOCK_DARK = "▓"
BLOCK_LIGHT = "░"


class ScreenRoute(StrEnum):
    MAIN_MENU = "main_menu"
    SETUP_PLAY = "setup_play"
    SETUP_AUTOPLAY = "setup_autoplay"
    GAME = "game"
    GAME_MENU = "game_menu"
    FINAL = "final"
    RECORDS_LIST = "records_list"
    RECORD_DETAIL = "record_detail"


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
        self.setup_state = SetupState(autoplay=False, config=GameConfig.for_play())
        self.message = ""
        self.selected_record_index = 0
        self.selected_record: RecordEntry | None = None
        self.records_scroll = 0
        self.detail_scroll = 0
        self.should_exit = False
        self.reload_records()

    def reload_records(self) -> RecordDatabase:
        self.records = self.record_store.load()
        return self.records

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
        self.current_route = ScreenRoute.RECORDS_LIST
        self.selected_record_index = min(
            self.selected_record_index, max(len(self.records.records) - 1, 0)
        )
        self.selected_record = None
        self.records_scroll = 0
        self.detail_scroll = 0
        self.message = ""

    def open_record_detail(self, record: RecordEntry) -> None:
        self.selected_record = record
        self.detail_scroll = 0
        self.current_route = ScreenRoute.RECORD_DETAIL

    def export_records(self) -> None:
        if not self.records.records:
            self.message = "No records to export."
            return
        path = export_records_csv(self.records.records, self.paths.exports_dir)
        self.message = f"Exported {path.name}"

    def start_session(self, config: GameConfig) -> None:
        self.active_session = create_game_session(config)
        self.current_route = ScreenRoute.GAME
        self.message = ""

    def open_game_menu(self) -> None:
        if self.active_session is not None:
            self.current_route = ScreenRoute.GAME_MENU

    def resume_game(self) -> None:
        if self.active_session is not None:
            self.current_route = ScreenRoute.GAME

    def restart_current_config(self) -> None:
        if self.active_session is None:
            return
        config = self.active_session.state.config
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
        self.active_session = None
        self.message = ""

    def return_to_menu(self) -> None:
        self.active_session = None
        self.current_route = ScreenRoute.MAIN_MENU
        self.message = ""

    def advance_autoplay(self, *, max_steps: int | None = None) -> None:
        if (
            self.active_session is None
            or self.active_session.state.config.mode is not Mode.AUTOPLAY
        ):
            return
        steps = 0
        while self.current_route is ScreenRoute.GAME and not self.active_session.state.is_game_over:
            self.active_session.step_autoplay()
            self._complete_session_if_needed()
            steps += 1
            if max_steps is not None and steps >= max_steps:
                break

    def select_coord(self, coord: Coord) -> None:
        if self.active_session is None:
            return
        selection = self.active_session.state.selection
        if selection.selected_coord == coord:
            selection.clear()
            return
        selection.selected_coord = coord
        selection.selected_city_id = selected_city_id_for_coord(self.active_session.state, coord)
        self.message = ""

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

        if element_id.startswith("record-item-"):
            record_id = int(element_id.removeprefix("record-item-"))
            record = next(
                (entry for entry in self.records.records if entry.record_id == record_id), None
            )
            if record is not None:
                self.open_record_detail(record)
            return

        if self.current_route in {ScreenRoute.SETUP_PLAY, ScreenRoute.SETUP_AUTOPLAY}:
            self._click_setup(element_id)
            return
        if self.current_route is ScreenRoute.GAME:
            self._click_game(element_id)
            return
        if self.current_route is ScreenRoute.GAME_MENU:
            self._click_game_menu(element_id)
            return
        if self.current_route is ScreenRoute.FINAL:
            self._click_final(element_id)
            return
        if self.current_route is ScreenRoute.RECORDS_LIST:
            if element_id == "records-export":
                self.export_records()
            elif element_id == "records-back":
                self.return_to_menu()
            return
        if self.current_route is ScreenRoute.RECORD_DETAIL and element_id == "record-detail-back":
            self.current_route = ScreenRoute.RECORDS_LIST

    def press_key(self, key: str) -> None:
        normalized = key.lower()
        if normalized == "q":
            if self.current_route is ScreenRoute.GAME_MENU:
                self.resume_game()
            elif self.current_route is ScreenRoute.RECORD_DETAIL:
                self.current_route = ScreenRoute.RECORDS_LIST
            elif self.current_route in {
                ScreenRoute.SETUP_PLAY,
                ScreenRoute.SETUP_AUTOPLAY,
                ScreenRoute.RECORDS_LIST,
                ScreenRoute.FINAL,
            }:
                self.return_to_menu()
            elif self.current_route is ScreenRoute.GAME:
                self.return_to_menu()
            return
        if normalized == "m" and self.current_route is ScreenRoute.GAME:
            self.open_game_menu()
            return
        if normalized == "b" and self.current_route is ScreenRoute.GAME:
            self._execute_first_available_game_action("build")
            return
        if normalized == "t" and self.current_route is ScreenRoute.GAME:
            self._execute_first_available_game_action("research")
            return
        if normalized == "d" and self.current_route is ScreenRoute.GAME:
            self.message = self._selection_detail()
            return
        if key == "KEY_UP":
            self._scroll(-1)
            return
        if key == "KEY_DOWN":
            self._scroll(1)
            return
        if key == "KEY_LEFT":
            self._move_selection(-1, 0)
            return
        if key == "KEY_RIGHT":
            self._move_selection(1, 0)

    def preview_board(self) -> dict[Coord, Tile]:
        preview_session = create_game_session(self.setup_state.config)
        return preview_session.state.board

    def visible_record_ids(self) -> list[int]:
        return [record.record_id for record in self.records.records]

    def available_game_actions(self) -> list[str]:
        if self.active_session is None:
            return []
        state = self.active_session.state
        selection = state.selection
        actions: list[str] = ["game-skip", "game-menu"]
        if selection.selected_coord is not None:
            if validate_action(state, Action.build_city(selection.selected_coord)).is_valid:
                actions.append("game-build-city")
            if validate_action(state, Action.build_road(selection.selected_coord)).is_valid:
                actions.append("game-build-road")
        if selection.selected_city_id is not None:
            for building_type in BuildingType:
                action = Action.build_building(selection.selected_city_id, building_type)
                if validate_action(state, action).is_valid:
                    actions.append(f"game-build-{building_type.value}")
            for tech_type in TechType:
                action = Action.research_tech(selection.selected_city_id, tech_type)
                if validate_action(state, action).is_valid:
                    actions.append(f"game-research-{tech_type.value}")
        return actions

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
            next_policy = (
                PolicyType.RANDOM
                if config.policy_type is PolicyType.BASELINE
                else PolicyType.BASELINE
            )
            self._replace_setup_config(policy_type=next_policy)
        elif element_id == "setup-playback" and self.setup_state.autoplay:
            next_playback = (
                PlaybackMode.SPEED
                if config.playback_mode is PlaybackMode.NORMAL
                else PlaybackMode.NORMAL
            )
            self._replace_setup_config(playback_mode=next_playback)
        elif element_id == "setup-map-size-inc":
            self._replace_setup_config(map_size=min(config.map_size + 2, 24))
        elif element_id == "setup-map-size-dec":
            self._replace_setup_config(map_size=max(config.map_size - 2, 12))
        elif element_id == "setup-turn-limit-inc":
            self._replace_setup_config(turn_limit=min(config.turn_limit + 10, 150))
        elif element_id == "setup-turn-limit-dec":
            self._replace_setup_config(turn_limit=max(config.turn_limit - 10, 30))
        elif element_id == "setup-recreate":
            self._replace_setup_config(seed=config.seed + 1)
        elif element_id == "setup-start":
            self.start_session(self.setup_state.config)
        elif element_id == "setup-menu":
            self.return_to_menu()

    def _replace_setup_config(self, **changes: object) -> None:
        config = self.setup_state.config
        data = {
            "map_size": config.map_size,
            "turn_limit": config.turn_limit,
            "map_difficulty": config.map_difficulty,
            "seed": config.seed,
        }
        data.update(changes)
        if self.setup_state.autoplay:
            self.setup_state.config = GameConfig.for_autoplay(
                map_size=int(data["map_size"]),
                turn_limit=int(data["turn_limit"]),
                map_difficulty=data["map_difficulty"],  # type: ignore[arg-type]
                policy_type=data.get("policy_type", config.policy_type),  # type: ignore[arg-type]
                playback_mode=data.get("playback_mode", config.playback_mode),  # type: ignore[arg-type]
                seed=int(data["seed"]),
            )
        else:
            self.setup_state.config = GameConfig.for_play(
                map_size=int(data["map_size"]),
                turn_limit=int(data["turn_limit"]),
                map_difficulty=data["map_difficulty"],  # type: ignore[arg-type]
                seed=int(data["seed"]),
            )

    def _click_game(self, element_id: str) -> None:
        if self.active_session is None:
            return
        state = self.active_session.state
        selection = state.selection
        action: Action | None = None
        if element_id == "game-menu":
            self.open_game_menu()
            return
        if element_id == "game-skip":
            action = Action.skip()
        elif element_id == "game-build-city" and selection.selected_coord is not None:
            action = Action.build_city(selection.selected_coord)
        elif element_id == "game-build-road" and selection.selected_coord is not None:
            action = Action.build_road(selection.selected_coord)
        elif element_id.startswith("game-build-") and selection.selected_city_id is not None:
            suffix = element_id.removeprefix("game-build-")
            action = Action.build_building(selection.selected_city_id, BuildingType(suffix))
        elif element_id.startswith("game-research-") and selection.selected_city_id is not None:
            suffix = element_id.removeprefix("game-research-")
            action = Action.research_tech(selection.selected_city_id, TechType(suffix))

        if action is None:
            return
        validation = validate_action(state, action)
        if not validation.is_valid:
            self.message = validation.message
            return
        self.active_session.apply_action(action)
        state.selection.clear()
        self._complete_session_if_needed()

    def _click_game_menu(self, element_id: str) -> None:
        if element_id == "game-menu-resume":
            self.resume_game()
        elif element_id == "game-menu-restart":
            self.restart_current_config()
        elif element_id == "game-menu-main":
            self.return_to_menu()

    def _click_final(self, element_id: str) -> None:
        if element_id == "final-restart":
            self.restart_current_config()
        elif element_id == "final-menu":
            self.return_to_menu()

    def _complete_session_if_needed(self) -> None:
        if self.active_session is None or not self.active_session.state.is_game_over:
            return
        if self.active_session.saved_record is None:
            self.active_session.saved_record = self.record_store.append_completed_game(
                self.active_session.state
            )
            self.reload_records()
        self.current_route = ScreenRoute.FINAL

    def _execute_first_available_game_action(self, prefix: str) -> None:
        for action_id in self.available_game_actions():
            if action_id.startswith(f"game-{prefix}"):
                self.click(action_id)
                return

    def _selection_detail(self) -> str:
        if self.active_session is None:
            return ""
        selection = self.active_session.state.selection
        if selection.selected_coord is None:
            return "No tile selected."
        tile = self.active_session.state.board[selection.selected_coord]
        return f"Tile {selection.selected_coord} {tile.base_terrain.value}/{tile.occupant.value}"

    def _scroll(self, delta: int) -> None:
        if self.current_route is ScreenRoute.RECORDS_LIST:
            self.selected_record_index = min(
                max(self.selected_record_index + delta, 0), max(len(self.records.records) - 1, 0)
            )
            self.records_scroll = min(
                self.selected_record_index, max(len(self.records.records) - 1, 0)
            )
        elif self.current_route is ScreenRoute.RECORD_DETAIL:
            self.detail_scroll = max(self.detail_scroll + delta, 0)

    def _move_selection(self, dx: int, dy: int) -> None:
        if self.current_route is not ScreenRoute.GAME or self.active_session is None:
            return
        coords = sorted(self.active_session.state.board, key=coord_sort_key)
        if not coords:
            return
        selected = self.active_session.state.selection.selected_coord or coords[0]
        candidate = (selected[0] + dx, selected[1] + dy)
        if candidate in self.active_session.state.board:
            self.select_coord(candidate)


class CursesMicroCivApp:
    """Thin curses wrapper around the controller."""

    def __init__(self, *, paths: AppPaths | None = None) -> None:
        self.controller = MicroCivController(paths=paths)
        self.render_state = RenderState()
        self._color_pairs: dict[str, int] = {}

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
            self._render(stdscr)
            if (
                self.controller.current_route is ScreenRoute.GAME
                and self.controller.active_session is not None
                and self.controller.active_session.state.config.mode is Mode.AUTOPLAY
            ):
                max_steps = (
                    8
                    if self.controller.active_session.state.config.playback_mode
                    is PlaybackMode.SPEED
                    else 1
                )
                self.controller.advance_autoplay(max_steps=max_steps)
                continue

            key = stdscr.getch()
            if key == -1:
                continue
            self._handle_input(stdscr, key)

    def _init_colors(self) -> None:
        pairs = {
            "plain": (curses.COLOR_BLACK, curses.COLOR_GREEN),
            "forest": (curses.COLOR_BLACK, curses.COLOR_GREEN),
            "mountain": (curses.COLOR_BLACK, curses.COLOR_WHITE),
            "river": (curses.COLOR_BLACK, curses.COLOR_CYAN),
            "wasteland": (curses.COLOR_BLACK, curses.COLOR_YELLOW),
            "city": (curses.COLOR_BLACK, curses.COLOR_RED),
            "road": (curses.COLOR_BLACK, curses.COLOR_MAGENTA),
            "selected": (curses.COLOR_BLACK, curses.COLOR_WHITE),
            "text": (curses.COLOR_WHITE, -1),
            "accent": (curses.COLOR_CYAN, -1),
        }
        pair_id = 1
        for name, (fg, bg) in pairs.items():
            curses.init_pair(pair_id, fg, bg)
            self._color_pairs[name] = pair_id
            pair_id += 1

    def _handle_input(self, stdscr: CursesWindow, key: int) -> None:
        if key == curses.KEY_MOUSE:
            try:
                _, mouse_x, mouse_y, _, bstate = curses.getmouse()
            except curses.error:
                return
            self._handle_mouse(mouse_x, mouse_y, bstate)
            return
        key_name = curses.keyname(key).decode("utf-8", errors="ignore")
        if key_name == "^M":
            return
        self.controller.press_key(key_name)

    def _handle_mouse(self, mouse_x: int, mouse_y: int, bstate: int) -> None:
        if bstate & getattr(curses, "BUTTON4_PRESSED", 0):
            self.controller._scroll(-1)
            return
        if bstate & getattr(curses, "BUTTON5_PRESSED", 0):
            self.controller._scroll(1)
            return
        for button_id, rect in self.render_state.button_regions.items():
            if rect.contains(mouse_x, mouse_y):
                self.controller.click(button_id)
                return
        if self.controller.current_route is ScreenRoute.GAME:
            for coord, rect in self.render_state.map_regions.items():
                if rect.contains(mouse_x, mouse_y):
                    self.controller.select_coord(coord)
                    return

    def _render(self, stdscr: CursesWindow) -> None:
        stdscr.erase()
        self.render_state.clear()
        height, width = stdscr.getmaxyx()
        self._draw_title(stdscr, width)

        route = self.controller.current_route
        if route is ScreenRoute.MAIN_MENU:
            self._render_main_menu(stdscr, width)
        elif route in {ScreenRoute.SETUP_PLAY, ScreenRoute.SETUP_AUTOPLAY}:
            self._render_setup(stdscr, width)
        elif route is ScreenRoute.GAME:
            self._render_game(stdscr, width, height)
        elif route is ScreenRoute.GAME_MENU:
            self._render_game(stdscr, width, height)
            self._render_game_menu(stdscr, width, height)
        elif route is ScreenRoute.FINAL:
            self._render_final(stdscr, width)
        elif route is ScreenRoute.RECORDS_LIST:
            self._render_records_list(stdscr, width, height)
        elif route is ScreenRoute.RECORD_DETAIL:
            self._render_record_detail(stdscr, width, height)

        if self.controller.message:
            self._safe_addstr(
                stdscr, height - 2, 2, self.controller.message[: max(width - 4, 0)], "accent"
            )
        stdscr.refresh()

    def _draw_title(self, stdscr: CursesWindow, width: int) -> None:
        title = f"{BLOCK_FULL * 2} MicroCiv {BLOCK_FULL * 2}"
        self._safe_addstr(stdscr, 0, max((width - len(title)) // 2, 0), title, "accent")

    def _render_main_menu(self, stdscr: CursesWindow, width: int) -> None:
        buttons = [
            ("menu-play", "Play"),
            ("menu-autoplay", "Autoplay"),
            ("menu-records", "Records"),
            ("menu-exit", "Exit"),
        ]
        y = 4
        for button_id, label in buttons:
            x = max((width - len(label) - 4) // 2, 2)
            text = f"[ {label} ]"
            self._safe_addstr(stdscr, y, x, text, "text")
            self.render_state.button_regions[button_id] = Rect(x=x, y=y, width=len(text))
            y += 2

    def _render_setup(self, stdscr: CursesWindow, width: int) -> None:
        config = self.controller.setup_state.config
        y = 3
        self._safe_addstr(
            stdscr,
            y,
            2,
            f"Mode: {'Autoplay' if self.controller.setup_state.autoplay else 'Play'}",
            "text",
        )
        y += 2
        self._draw_button(
            stdscr, "setup-difficulty", f"Difficulty: {config.map_difficulty.value}", 2, y
        )
        y += 2
        if self.controller.setup_state.autoplay:
            self._draw_button(stdscr, "setup-ai-type", f"AI: {config.policy_type.value}", 2, y)
            y += 2
            self._draw_button(
                stdscr, "setup-playback", f"Playback: {config.playback_mode.value}", 2, y
            )
            y += 2
        self._draw_button(stdscr, "setup-map-size-dec", "[ - ]", 2, y)
        self._draw_button(stdscr, "setup-map-size-inc", "[ + ]", 10, y)
        self._safe_addstr(stdscr, y, 18, f"Map Size: {config.map_size}", "text")
        y += 2
        self._draw_button(stdscr, "setup-turn-limit-dec", "[ - ]", 2, y)
        self._draw_button(stdscr, "setup-turn-limit-inc", "[ + ]", 10, y)
        self._safe_addstr(stdscr, y, 18, f"Turn Limit: {config.turn_limit}", "text")
        y += 2
        self._draw_button(stdscr, "setup-recreate", f"Recreate Seed {config.seed}", 2, y)
        self._draw_button(stdscr, "setup-start", "Start", 28, y)
        self._draw_button(stdscr, "setup-menu", "Menu", 40, y)

        preview = self.controller.preview_board()
        preview_x = max(width - (config.map_size * 2) - 4, 45)
        self._render_board(stdscr, preview, preview_x, 4, None)

    def _render_game(self, stdscr: CursesWindow, width: int, height: int) -> None:
        if self.controller.active_session is None:
            return
        state = self.controller.active_session.state
        board_x = 2
        board_y = 3
        self._render_board(stdscr, state.board, board_x, board_y, state.selection.selected_coord)
        panel_x = max(board_x + (state.config.map_size * 2) + 4, 44)
        self._safe_addstr(
            stdscr, 3, panel_x, f"Turn {state.turn}/{state.config.turn_limit}", "text"
        )
        self._safe_addstr(stdscr, 4, panel_x, f"Score {state.score}", "text")
        self._safe_addstr(
            stdscr,
            6,
            panel_x,
            f"Food {sum(network.resources.food for network in state.networks.values())}",
            "text",
        )
        self._safe_addstr(
            stdscr,
            7,
            panel_x,
            f"Wood {sum(network.resources.wood for network in state.networks.values())}",
            "text",
        )
        self._safe_addstr(
            stdscr,
            8,
            panel_x,
            f"Ore {sum(network.resources.ore for network in state.networks.values())}",
            "text",
        )
        self._safe_addstr(
            stdscr,
            9,
            panel_x,
            f"Sci {sum(network.resources.science for network in state.networks.values())}",
            "text",
        )
        self._safe_addstr(stdscr, 11, panel_x, "Actions", "accent")
        y = 12
        for action_id in self.controller.available_game_actions():
            label = action_id.removeprefix("game-").replace("-", " ").title()
            self._draw_button(stdscr, action_id, label, panel_x, y)
            y += 1
            if y >= height - 4:
                break
        self._safe_addstr(
            stdscr,
            height - 3,
            2,
            "Mouse-first UI. Shortcuts: m menu, b build, t tech, d detail, q back.",
            "text",
        )

    def _render_game_menu(self, stdscr: CursesWindow, width: int, height: int) -> None:
        box_x = max((width - 24) // 2, 2)
        box_y = max((height - 8) // 2, 2)
        self._safe_addstr(stdscr, box_y, box_x, "[ Game Menu ]", "accent")
        self._draw_button(stdscr, "game-menu-resume", "Resume", box_x, box_y + 2)
        self._draw_button(stdscr, "game-menu-restart", "Restart", box_x, box_y + 3)
        self._draw_button(stdscr, "game-menu-main", "Main Menu", box_x, box_y + 4)

    def _render_final(self, stdscr: CursesWindow, width: int) -> None:
        if self.controller.active_session is None:
            return
        record = self.controller.active_session.saved_record
        score = (
            record.final_score if record is not None else self.controller.active_session.state.score
        )
        self._safe_addstr(stdscr, 4, max((width - 14) // 2, 2), f"Final Score {score}", "accent")
        if record is not None:
            self._safe_addstr(
                stdscr, 6, 2, f"AI {record.ai_type}  Session {record.session_elapsed_ms}ms", "text"
            )
            self._safe_addstr(stdscr, 7, 2, f"Decision Avg {record.decision_time_ms_avg}ms", "text")
            self._safe_addstr(stdscr, 8, 2, f"Turn Avg {record.turn_elapsed_ms_avg}ms", "text")
        self._draw_button(stdscr, "final-restart", "Restart", 2, 11)
        self._draw_button(stdscr, "final-menu", "Main Menu", 16, 11)

    def _render_records_list(self, stdscr: CursesWindow, width: int, height: int) -> None:
        self._safe_addstr(stdscr, 3, 2, "Records", "accent")
        if not self.controller.records.records:
            self._safe_addstr(stdscr, 5, 2, "No records available.", "text")
            self._draw_button(stdscr, "records-back", "Back", 2, 7)
            return

        visible_top = min(self.controller.records_scroll, len(self.controller.records.records) - 1)
        visible_records = self.controller.records.records[
            visible_top : visible_top + max(height - 10, 1)
        ]
        y = 5
        for index, record in enumerate(visible_records, start=visible_top):
            marker = ">" if index == self.controller.selected_record_index else " "
            text = (
                f"{marker} #{record.record_id} {record.ai_type:<8} "
                f"score={record.final_score:<4} time={record.session_elapsed_ms}ms"
            )
            self._safe_addstr(stdscr, y, 2, text[: max(width - 4, 0)], "text")
            self.render_state.button_regions[f"record-item-{record.record_id}"] = Rect(
                2, y, len(text)
            )
            y += 1
        self._draw_button(stdscr, "records-export", "Export", 2, height - 4)
        self._draw_button(stdscr, "records-back", "Back", 14, height - 4)

    def _render_record_detail(self, stdscr: CursesWindow, width: int, height: int) -> None:
        record = self.controller.selected_record
        if record is None:
            self.controller.current_route = ScreenRoute.RECORDS_LIST
            return
        lines = [
            f"Record #{record.record_id}",
            f"AI: {record.ai_type}",
            f"Mode: {record.mode}",
            f"Score: {record.final_score}",
            f"Turns: {record.actual_turns}",
            f"Session: {record.session_elapsed_ms} ms",
            f"Decision avg/max: {record.decision_time_ms_avg}/{record.decision_time_ms_max} ms",
            f"Turn avg/max: {record.turn_elapsed_ms_avg}/{record.turn_elapsed_ms_max} ms",
            f"Map size: {record.map_size}",
            f"Difficulty: {record.map_difficulty}",
            f"Food/Wood/Ore/Sci: {record.food}/{record.wood}/{record.ore}/{record.science}",
        ]
        start = min(self.controller.detail_scroll, max(len(lines) - 1, 0))
        for offset, line in enumerate(lines[start : start + max(height - 8, 1)]):
            self._safe_addstr(stdscr, 3 + offset, 2, line[: max(width - 4, 0)], "text")
        self._draw_button(stdscr, "record-detail-back", "Back", 2, height - 4)

    def _render_board(
        self,
        stdscr: CursesWindow,
        board: dict[Coord, Tile],
        origin_x: int,
        origin_y: int,
        selected_coord: Coord | None,
    ) -> None:
        for coord in sorted(board, key=coord_sort_key):
            x, y = coord
            screen_x = origin_x + (x * 2)
            screen_y = origin_y + y
            tile = board[coord]
            style = _style_for_tile(tile, selected=coord == selected_coord)
            self._safe_addstr(stdscr, screen_y, screen_x, style[0], style[1])
            self.render_state.map_regions[coord] = Rect(screen_x, screen_y, 2)

    def _draw_button(
        self, stdscr: CursesWindow, button_id: str, label: str, x: int, y: int
    ) -> None:
        text = f"[ {label} ]"
        self._safe_addstr(stdscr, y, x, text, "text")
        self.render_state.button_regions[button_id] = Rect(x=x, y=y, width=len(text))

    def _safe_addstr(
        self, stdscr: CursesWindow, y: int, x: int, text: str, color_name: str
    ) -> None:
        if y < 0 or x < 0 or not text:
            return
        try:
            stdscr.addstr(y, x, text, curses.color_pair(self._color_pairs[color_name]))
        except curses.error:
            return


def _style_for_tile(tile: Tile, *, selected: bool) -> tuple[str, str]:
    if tile.occupant is OccupantType.CITY:
        return (BLOCK_FULL * 2, "city" if not selected else "selected")
    if tile.occupant is OccupantType.ROAD:
        return (BLOCK_DARK * 2, "road" if not selected else "selected")
    if tile.base_terrain is TerrainType.PLAIN:
        return (BLOCK_FULL * 2, "plain" if not selected else "selected")
    if tile.base_terrain is TerrainType.FOREST:
        return (BLOCK_DARK * 2, "forest" if not selected else "selected")
    if tile.base_terrain is TerrainType.MOUNTAIN:
        return (BLOCK_LIGHT * 2, "mountain" if not selected else "selected")
    if tile.base_terrain is TerrainType.RIVER:
        return ("▄▄", "river" if not selected else "selected")
    return ("..", "wasteland" if not selected else "selected")
