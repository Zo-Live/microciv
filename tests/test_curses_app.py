from __future__ import annotations

import curses
import json
from pathlib import Path

from microciv.config import build_app_paths
from microciv.curses_app import (
    MAP_SIZE_OPTIONS,
    CursesMicroCivApp,
    MicroCivController,
    Rect,
    ScreenRoute,
    SettlementType,
)
from microciv.game.actions import Action, validate_action
from microciv.game.enums import Mode, OccupantType, PlaybackMode, PolicyType, TerrainType
from microciv.game.models import City, Network, ResourcePool, Tile
from microciv.records.models import RecordDatabase, RecordEntry


def test_controller_can_open_setup_and_cycle_autoplay_options(tmp_path: Path) -> None:
    controller = build_controller(tmp_path)

    controller.click("menu-autoplay")
    assert controller.current_route is ScreenRoute.SETUP_AUTOPLAY
    assert controller.setup_state.config.policy_type is PolicyType.GREEDY

    controller.click("setup-ai-type")
    assert controller.setup_state.config.policy_type is PolicyType.RANDOM

    controller.click("setup-ai-type")
    assert controller.setup_state.config.policy_type is PolicyType.GREEDY

    initial_map_size = controller.setup_state.config.map_size
    controller.click("setup-map-size")
    assert controller.setup_state.config.map_size in MAP_SIZE_OPTIONS
    assert controller.setup_state.config.map_size != initial_map_size

    controller.click("setup-playback")
    assert controller.setup_state.config.playback_mode is PlaybackMode.SPEED


def test_controller_can_start_manual_session_and_build_city(tmp_path: Path) -> None:
    controller = build_controller(tmp_path)

    controller.click("menu-play")
    controller.click("setup-start")

    assert controller.current_route is ScreenRoute.MANUAL_GAME
    assert controller.active_session is not None
    assert controller.active_session.state.config.mode is Mode.PLAY

    buildable = next(
        coord
        for coord in controller.active_session.state.board
        if validate_action(controller.active_session.state, Action.build_city(coord)).is_valid
    )

    controller.select_coord(buildable)
    assert controller.current_route is ScreenRoute.MANUAL_GAME
    assert controller.selected_settlement_type.value == "city"
    controller.click("settle-build")

    assert len(controller.active_session.state.cities) == 1


def test_controller_shows_river_road_option_even_when_resources_are_insufficient(
    tmp_path: Path,
) -> None:
    controller = build_controller(tmp_path)
    controller.click("menu-play")
    controller.click("setup-start")

    assert controller.active_session is not None
    state = controller.active_session.state
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.RIVER),
    }
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.networks = {1: Network(network_id=1, city_ids={1}, resources=ResourcePool())}
    state.roads = {}

    controller.select_coord((1, 0))

    assert controller.current_route is ScreenRoute.MANUAL_GAME
    assert controller._has_settlement_options((1, 0))
    assert not controller._can_build_city_at_selection()
    assert controller._can_show_build_road_at_selection()
    assert "settle-road" in controller.available_game_actions()
    assert "settle-city" not in controller.available_game_actions()

    controller.selected_settlement_type = SettlementType.ROAD
    controller.click("settle-build")

    assert controller.message == "Not enough resources"
    assert state.selection.selected_coord == (1, 0)
    assert state.board[(1, 0)].occupant is OccupantType.NONE


def test_controller_shows_wasteland_road_option(tmp_path: Path) -> None:
    controller = build_controller(tmp_path)
    controller.click("menu-play")
    controller.click("setup-start")

    assert controller.active_session is not None
    state = controller.active_session.state
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.WASTELAND),
    }
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.networks = {1: Network(network_id=1, city_ids={1}, resources=ResourcePool())}
    state.roads = {}

    controller.select_coord((1, 0))

    assert controller._has_settlement_options((1, 0))
    assert not controller._can_build_city_at_selection()
    assert controller._can_show_build_road_at_selection()


def test_controller_keyboard_shortcuts_follow_new_semantics(tmp_path: Path) -> None:
    controller = build_controller(tmp_path)
    controller.click("menu-play")
    controller.click("setup-start")

    controller.press_key("m")
    assert controller.current_route is ScreenRoute.GAME_MENU

    controller.press_key("m")
    assert controller.current_route is ScreenRoute.MANUAL_GAME

    controller.press_key("q")
    assert controller.should_exit is True


def test_autoplay_reaches_final_and_saves_record(tmp_path: Path) -> None:
    controller = build_controller(tmp_path)
    controller.click("menu-autoplay")
    controller.click("setup-ai-type")
    controller.click("setup-start")

    assert controller.current_route is ScreenRoute.AUTOPLAY_GAME

    controller.advance_autoplay()

    assert controller.current_route is ScreenRoute.AUTO_FINAL
    assert controller.active_session is not None
    assert controller.active_session.saved_record is not None
    assert controller.active_session.saved_record.ai_type == "Random"
    assert len(controller.reload_records().records) == 1


def test_records_are_sorted_and_jump_shortcuts_move_scroll(tmp_path: Path) -> None:
    controller = build_controller(tmp_path)
    controller.records = RecordDatabase(
        records=[
            make_record(1, "2026-04-09T10:00:00+08:00"),
            make_record(3, "2026-04-09T12:00:00+08:00"),
            make_record(2, "2026-04-09T12:00:00+08:00"),
            make_record(4, "2026-04-09T13:00:00+08:00"),
            make_record(5, "2026-04-09T14:00:00+08:00"),
            make_record(6, "2026-04-09T15:00:00+08:00"),
            make_record(7, "2026-04-09T16:00:00+08:00"),
            make_record(8, "2026-04-09T17:00:00+08:00"),
            make_record(9, "2026-04-09T18:00:00+08:00"),
        ]
    )
    controller.current_route = ScreenRoute.RECORDS_GRID

    assert controller.visible_record_ids()[:4] == [9, 8, 7, 6]

    controller.press_key("d")
    assert controller.records_scroll == controller.max_records_scroll()

    controller.press_key("t")
    assert controller.records_scroll == 0


def test_app_mouse_dispatch_uses_rendered_hitboxes_and_wheel(tmp_path: Path) -> None:
    app = CursesMicroCivApp(paths=build_app_paths(tmp_path))
    app.render_state.button_regions["menu-play"] = Rect(10, 5, 8)

    app._handle_mouse(11, 5, curses.BUTTON1_PRESSED)

    assert app.controller.current_route is ScreenRoute.SETUP_PLAY

    app.controller.current_route = ScreenRoute.RECORDS_GRID
    app.controller.records = RecordDatabase(
        records=[
            make_record(idx, f"2026-04-09T{idx:02d}:00:00+08:00")
            for idx in range(1, 14)
        ]
    )
    app._handle_mouse(0, 0, getattr(curses, "BUTTON5_PRESSED", 0))
    assert app.controller.records_scroll == 1


def test_export_records_writes_fixed_json_file(tmp_path: Path) -> None:
    controller = build_controller(tmp_path)
    controller.records = RecordDatabase(records=[make_record(1, "2026-04-09T12:00:00+08:00")])

    controller.export_records()

    export_path = tmp_path / "exports" / "records_export.json"
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert export_path.exists()
    assert payload["records"][0]["record_id"] == 1


def build_controller(tmp_path: Path):
    return MicroCivController(paths=build_app_paths(tmp_path))


def make_record(record_id: int, timestamp: str) -> RecordEntry:
    return RecordEntry(
        record_id=record_id,
        timestamp=timestamp,
        game_version="0.1.0-test",
        mode="play",
        ai_type="Human",
        custom_goal="",
        playback_mode="",
        seed=record_id,
        map_size=16,
        map_difficulty="normal",
        turn_limit=30,
        actual_turns=30,
        final_score=record_id * 10,
        city_count=1,
        building_count=0,
        tech_count=0,
        food=0,
        wood=0,
        ore=0,
        science=0,
        build_city_count=1,
        build_road_count=0,
        build_farm_count=0,
        build_lumber_mill_count=0,
        build_mine_count=0,
        build_library_count=0,
        research_agriculture_count=0,
        research_logging_count=0,
        research_mining_count=0,
        research_education_count=0,
        skip_count=0,
        decision_count=0,
        decision_time_ms_total=0.0,
        decision_time_ms_avg=0.0,
        decision_time_ms_max=0.0,
        turn_elapsed_ms_total=0.0,
        turn_elapsed_ms_avg=0.0,
        turn_elapsed_ms_max=0.0,
        session_elapsed_ms=0.0,
    )
