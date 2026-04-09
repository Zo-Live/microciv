from __future__ import annotations

import asyncio

from microciv.config import build_app_paths
from microciv.game.actions import Action, validate_action
from microciv.game.enums import OccupantType, TerrainType
from microciv.game.models import BuildingCounts, City, GameConfig, GameState, Network, ResourcePool, Tile
from microciv.records.store import RecordStore
from microciv.tui.app import MicroCivApp


def test_tui_can_open_setup_and_start_play_game(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-play")
            await pilot.pause()
            assert app.screen.id == "setup-play-screen"

            await pilot.click("#setup-start")
            await pilot.pause()
            assert app.screen.id == "game-screen"
            assert app.active_session is not None
            assert app.active_session.state.config.mode.value == "play"
            assert len(app.active_session.state.board) > 0

    asyncio.run(runner())


def test_tui_speed_autoplay_reaches_final_and_saves_record(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-autoplay")
            await pilot.pause()
            await pilot.click("#setup-playback")
            await pilot.click("#setup-turn-limit")
            await pilot.click("#setup-turn-limit")
            await pilot.click("#setup-turn-limit")
            await pilot.click("#setup-start")
            await pilot.pause(1.0)
            assert app.screen.id == "final-screen"
            assert app.active_session is not None
            assert app.active_session.saved_record is not None
            assert len(app.reload_records().records) == 1

    asyncio.run(runner())


def test_tui_records_screen_exports_csv(tmp_path) -> None:
    paths = build_app_paths(tmp_path)
    store = RecordStore(paths.records_file)
    store.append_completed_game(build_completed_state(), timestamp="2026-04-09T10:00:00+08:00")

    async def runner() -> None:
        app = MicroCivApp(paths=paths)
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-records")
            await pilot.pause()
            assert app.screen.id == "records-list-screen"

            await pilot.click("#records-export")
            await pilot.pause()
            exported = sorted(paths.exports_dir.glob("records-*.csv"))
            assert exported

    asyncio.run(runner())


def build_completed_state() -> GameState:
    state = GameState.empty(GameConfig.for_play(turn_limit=30, seed=1))
    state.board = {(0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY)}
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(farm=1),
        )
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=12, wood=2, ore=0, science=0))
    }
    state.turn = 30
    state.is_game_over = True
    state.stats.build_city_count = 1
    state.stats.build_farm_count = 1
    return state


def test_tui_clicking_city_opens_city_context_panel(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-play")
            await pilot.pause()
            await pilot.click("#setup-start")
            await pilot.pause()

            state = app.active_session.state
            buildable = next(
                coord
                for coord in state.board
                if validate_action(state, Action.build_city(coord)).is_valid
            )

            await pilot.click(f"#tile-{buildable[0]}-{buildable[1]}")
            await pilot.pause()
            await pilot.click("#action-build")
            await pilot.pause()

            city_coord = next(city.coord for city in app.active_session.state.cities.values())
            await pilot.click(f"#tile-{city_coord[0]}-{city_coord[1]}")
            await pilot.pause()
            assert app.active_session.state.selection.selected_city_id is not None
            assert app.screen.query("#resource-food")

    asyncio.run(runner())
