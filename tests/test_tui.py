from __future__ import annotations

import asyncio

from textual.app import App
from textual.widgets import Button

from microciv.config import build_app_paths
from microciv.game.actions import Action, validate_action
from microciv.game.engine import GameEngine
from microciv.game.enums import OccupantType, TechType, TerrainType
from microciv.game.models import BuildingCounts, City, GameConfig, GameState, Network, ResourcePool, Tile
from microciv.records.store import RecordStore
from microciv.tui.app import MicroCivApp
from microciv.tui.presenters.game_session import GameSession
from microciv.tui.presenters.state_machine import ScreenRoute
from microciv.tui.screens.final import FinalScreen
from microciv.tui.widgets.action_panel import ResourceButton
from microciv.tui.widgets.image_surface import ImageSurface
from microciv.tui.widgets.map_preview import MapPreview
from microciv.tui.widgets.map_view import MapView
from microciv.tui.widgets.panel_button import PanelButton


async def click_map_coord(pilot, app: MicroCivApp, coord: tuple[int, int]) -> None:
    map_view = app.screen.query_one("#game-map", MapView)
    await pilot.click("#game-map", offset=map_view.local_offset_for_coord(coord))
    await pilot.pause()


def assert_inside(container, widget) -> None:
    assert widget.region.x >= container.region.x
    assert widget.region.y >= container.region.y
    assert widget.region.right <= container.region.right
    assert widget.region.bottom <= container.region.bottom


def assert_roughly_centered(container, widget, *, tolerance: int = 3) -> None:
    assert abs(container.region.center[0] - widget.region.center[0]) <= tolerance


def assert_widget_hidden(screen, selector: str) -> None:
    if not screen.query(selector):
        return
    widget = screen.query_one(selector)
    if not widget.display or widget.region.width == 0 or widget.region.height == 0:
        return
    if isinstance(widget, PanelButton):
        assert widget.label.strip() == "" or "-muted" in widget.classes
        return
    content = ""
    if hasattr(widget, "renderable"):
        renderable = widget.renderable
        content = getattr(renderable, "plain", str(renderable)).strip()
    assert content == "" or "-muted" in widget.classes


def assert_widget_visible(screen, selector: str) -> None:
    widget = screen.query_one(selector)
    assert widget.display
    assert widget.region.width > 0
    assert widget.region.height > 0


def test_tui_can_open_setup_and_start_play_game(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-play")
            await pilot.pause()
            assert app.current_route is ScreenRoute.SETUP_PLAY

            await pilot.click("#setup-start")
            await pilot.pause()
            assert app.current_route is ScreenRoute.GAME
            assert app.active_session is not None
            assert app.active_session.state.config.mode.value == "play"
            assert len(app.active_session.state.board) > 0

    asyncio.run(runner())


def test_tui_menu_and_setup_keep_top_level_entry_structure(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            assert app.screen.query("#menu-play")
            assert app.screen.query("#menu-autoplay")
            assert app.screen.query("#menu-records")
            assert app.screen.query("#menu-exit")
            assert app.screen.query("#logo-mark")
            assert app.screen.query("#logo-title")
            assert app.screen.query_one("#logo-mark").region.width > 0
            assert app.screen.query_one("#logo-mark").region.height > 0
            assert app.screen.query_one("#logo-title").region.width > 0
            assert app.screen.query_one("#logo-title").region.height > 0
            assert not app.screen.query("#logo-image")
            assert not app.screen.query("#setup-ai-type")

            await pilot.click("#menu-play")
            await pilot.pause()

            assert app.current_route is ScreenRoute.SETUP_PLAY
            assert app.screen.query("#setup-map-preview")
            assert app.screen.query("#setup-map-preview-image")
            assert not app.screen.query("#setup-ai-type")

            await pilot.click("#setup-menu")
            await pilot.pause()

            assert app.current_route is ScreenRoute.MAIN_MENU

            await pilot.click("#menu-autoplay")
            await pilot.pause()

            assert app.current_route is ScreenRoute.SETUP_AUTOPLAY
            assert app.screen.query("#setup-ai-type")
            assert app.screen.query("#setup-playback")

    asyncio.run(runner())


def test_tui_game_menu_uses_static_dot_logo(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-play")
            await pilot.pause()
            await pilot.click("#setup-start")
            await pilot.pause()

            await pilot.press("m")
            await pilot.pause()

            assert app.current_route is ScreenRoute.GAME_MENU
            assert app.screen.query("#logo-mark")
            assert app.screen.query("#logo-title")
            assert app.screen.query_one("#logo-mark").region.width > 0
            assert app.screen.query_one("#logo-title").region.width > 0
            assert not app.screen.query("#logo-image")

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
            assert app.current_route is ScreenRoute.FINAL
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
            assert app.current_route is ScreenRoute.RECORDS_LIST

            await pilot.click("#records-export")
            await pilot.pause()
            exported = sorted(paths.exports_dir.glob("records-*.csv"))
            assert exported

    asyncio.run(runner())


def test_tui_records_empty_state_hides_export_and_centers_back(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-records")
            await pilot.pause()

            assert app.current_route is ScreenRoute.RECORDS_LIST
            assert app.screen.query("#records-empty")
            assert not app.screen.query("#records-export")
            assert_roughly_centered(
                app.screen.query_one("#records-actions"),
                app.screen.query_one("#records-back"),
            )

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

            await click_map_coord(pilot, app, buildable)
            await pilot.click("#action-build")
            await pilot.pause()

            city_coord = next(city.coord for city in app.active_session.state.cities.values())
            await click_map_coord(pilot, app, city_coord)
            assert app.active_session.state.selection.selected_city_id is not None
            assert app.screen.query("#resource-food")

    asyncio.run(runner())


def test_tui_restart_returns_to_setup_without_duplicate_ids(tmp_path) -> None:
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

            assert app.current_route is ScreenRoute.FINAL

            await pilot.click("#final-restart")
            await pilot.pause()

            assert app.current_route is ScreenRoute.SETUP_AUTOPLAY

    asyncio.run(runner())


def test_tui_final_screen_uses_raster_map_and_controls_fit(tmp_path) -> None:
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

            assert app.current_route is ScreenRoute.FINAL
            final_map = app.screen.query_one("#final-map", MapPreview)
            assert final_map.query_one(ImageSurface).image is not None

            side_shell = app.screen.query_one("#final-side-shell")
            for selector in ["#final-score-value", "#final-restart", "#final-menu", "#final-exit"]:
                assert_inside(side_shell, app.screen.query_one(selector))

    asyncio.run(runner())


def test_tui_setup_preview_uses_raster_image_and_recreate_keeps_controls(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-autoplay")
            await pilot.pause()

            preview = app.screen.query_one("#setup-map-preview", MapPreview)
            image_surface = preview.query_one(ImageSurface)
            first_image = image_surface.image
            assert first_image is not None

            await pilot.click("#setup-recreate")
            await pilot.pause()

            updated_preview = app.screen.query_one("#setup-map-preview", MapPreview)
            updated_surface = updated_preview.query_one(ImageSurface)
            second_image = updated_surface.image
            assert second_image is not None
            assert second_image is not first_image
            assert app.screen.query("#setup-ai-type")
            assert app.screen.query("#setup-playback")
            assert app.screen.query("#setup-start")

    asyncio.run(runner())


def test_tui_setup_recreate_survives_repeated_hard_large_map_regeneration(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-autoplay")
            await pilot.pause()

            await pilot.click("#setup-difficulty")
            await pilot.pause()
            for _ in range(4):
                await pilot.click("#setup-map-size")
                await pilot.pause()
            for _ in range(2):
                await pilot.click("#setup-turn-limit")
                await pilot.pause()

            for _ in range(6):
                await pilot.click("#setup-recreate")
                await pilot.pause()

            assert app.current_route is ScreenRoute.SETUP_AUTOPLAY
            assert app.screen.query("#setup-map-preview")
            assert app.screen.query("#setup-start")
            assert "Hard" in app.screen.query_one("#setup-difficulty").label.plain
            assert "10" in app.screen.query_one("#setup-map-size").label.plain
            assert "150" in app.screen.query_one("#setup-turn-limit").label.plain

    asyncio.run(runner())


def test_tui_setup_play_refreshes_labels_for_difficulty_and_map_size(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-play")
            await pilot.pause()

            assert "Normal" in app.screen.query_one("#setup-difficulty").label.plain
            assert "6" in app.screen.query_one("#setup-map-size").label.plain

            await pilot.click("#setup-difficulty")
            await pilot.pause()
            await pilot.click("#setup-map-size")
            await pilot.pause()

            assert "Hard" in app.screen.query_one("#setup-difficulty").label.plain
            assert "7" in app.screen.query_one("#setup-map-size").label.plain

    asyncio.run(runner())


def test_tui_records_detail_uses_raster_map_and_back_returns_to_list(tmp_path) -> None:
    paths = build_app_paths(tmp_path)
    store = RecordStore(paths.records_file)
    store.append_completed_game(build_completed_state(), timestamp="2026-04-09T10:00:00+08:00")

    async def runner() -> None:
        app = MicroCivApp(paths=paths)
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-records")
            await pilot.pause()
            await pilot.click("#record-card-1")
            await pilot.pause()

            assert app.current_route is ScreenRoute.RECORD_DETAIL
            detail_map = app.screen.query_one("#record-detail-map", MapPreview)
            assert detail_map.query_one(ImageSurface).image is not None

            await pilot.click("#record-detail-back")
            await pilot.pause()
            assert app.current_route is ScreenRoute.RECORDS_LIST

    asyncio.run(runner())


def test_tui_game_uses_raster_map_and_map_clicks_select_tiles(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-play")
            await pilot.pause()
            await pilot.click("#setup-start")
            await pilot.pause()

            map_view = app.screen.query_one("#game-map", MapView)
            assert map_view.query_one(ImageSurface).image is not None

            coord = next(iter(app.active_session.state.board))
            await click_map_coord(pilot, app, coord)

            assert app.active_session.state.selection.selected_coord == coord
            assert app.screen.query_one("#game-metric-panel-score", ImageSurface).image is not None
            assert app.screen.query_one("#game-metric-panel-step", ImageSurface).image is not None

    asyncio.run(runner())


def test_tui_manual_actions_keep_map_and_metric_widgets_stable(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-play")
            await pilot.pause()
            await pilot.click("#setup-start")
            await pilot.pause()

            map_view = app.screen.query_one("#game-map", MapView)
            initial_map_cell_side = map_view._layout.metrics.cell_side

            state = app.active_session.state
            buildable = next(
                coord
                for coord in state.board
                if validate_action(state, Action.build_city(coord)).is_valid
            )

            await click_map_coord(pilot, app, buildable)
            await pilot.pause()
            assert app.screen.query_one("#game-map", MapView) is map_view
            assert len(list(app.screen.query("#game-metric-panel"))) == 1
            assert len(list(app.screen.query("#game-context-shell"))) == 1
            assert app.screen.query_one("#game-map", MapView)._layout.metrics.cell_side == initial_map_cell_side

            await pilot.click("#action-build")
            await pilot.pause()
            assert app.screen.query_one("#game-map", MapView) is map_view
            assert len(list(app.screen.query("#game-metric-panel"))) == 1
            assert len(list(app.screen.query("#game-context-shell"))) == 1
            assert app.screen.query_one("#game-map", MapView)._layout.metrics.cell_side == initial_map_cell_side

    asyncio.run(runner())


def test_tui_manual_context_refresh_rebuilds_children_without_duplicates(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-play")
            await pilot.pause()
            await pilot.click("#setup-start")
            await pilot.pause()

            assert len(list(app.screen.query("#action-skip"))) == 1

            state = app.active_session.state
            buildable = next(
                coord
                for coord in state.board
                if validate_action(state, Action.build_city(coord)).is_valid
            )

            await click_map_coord(pilot, app, buildable)
            await pilot.pause()
            assert len(list(app.screen.query("#game-context-shell"))) == 1
            assert_widget_visible(app.screen, "#action-choice-city")
            assert_widget_visible(app.screen, "#action-build")
            assert_widget_visible(app.screen, "#action-cancel")
            assert_widget_hidden(app.screen, "#action-skip")

            await pilot.click("#action-build")
            await pilot.pause()
            assert len(list(app.screen.query("#game-context-shell"))) == 1
            assert_widget_visible(app.screen, "#action-skip")
            assert_widget_hidden(app.screen, "#action-build")
            assert_widget_hidden(app.screen, "#action-cancel")

            city_coord = next(city.coord for city in app.active_session.state.cities.values())
            await click_map_coord(pilot, app, city_coord)
            await pilot.pause()

            assert_widget_visible(app.screen, "#resource-food")
            await pilot.click("#resource-food")
            await pilot.pause()
            assert len(list(app.screen.query("#game-context-shell"))) == 1
            assert_widget_visible(app.screen, "#build-confirm-resource")
            assert_widget_visible(app.screen, "#action-build")
            assert_widget_visible(app.screen, "#action-cancel")
            assert_widget_hidden(app.screen, "#resource-food")

            await pilot.click("#action-cancel")
            await pilot.pause()
            assert len(list(app.screen.query("#game-context-shell"))) == 1
            assert_widget_visible(app.screen, "#resource-food")
            assert_widget_visible(app.screen, "#action-cancel")
            assert_widget_hidden(app.screen, "#build-confirm-resource")

    asyncio.run(runner())


def test_tui_autoplay_tick_keeps_map_and_metric_widgets_stable(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-autoplay")
            await pilot.pause()
            await pilot.click("#setup-start")
            await pilot.pause()

            map_view = app.screen.query_one("#game-map", MapView)
            initial_map_cell_side = map_view._layout.metrics.cell_side
            turn_before = app.active_session.state.turn

            await pilot.pause(0.45)

            assert app.current_route is ScreenRoute.GAME
            assert app.active_session.state.turn > turn_before
            assert app.screen.query_one("#game-map", MapView) is map_view
            assert len(list(app.screen.query("#game-metric-panel"))) == 1
            assert app.screen.query_one("#game-map", MapView)._layout.metrics.cell_side == initial_map_cell_side

    asyncio.run(runner())


def test_tui_city_context_and_confirm_panels_fit_inside_side_shell(tmp_path) -> None:
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

            await click_map_coord(pilot, app, buildable)
            await pilot.click("#action-build")
            await pilot.pause()

            city_coord = next(city.coord for city in app.active_session.state.cities.values())
            await click_map_coord(pilot, app, city_coord)

            ids = [
                "#resource-food",
                "#resource-wood",
                "#resource-ore",
                "#resource-science",
                "#tech-agriculture",
                "#tech-logging",
                "#tech-mining",
                "#tech-education",
                "#action-cancel",
            ]
            for selector in ids:
                assert_inside(app.screen.query_one("#game-side-shell"), app.screen.query_one(selector))

            await pilot.click("#resource-food")
            await pilot.pause()

            for selector in ["#build-confirm-resource", "#action-build", "#action-cancel"]:
                assert_inside(app.screen.query_one("#game-side-shell"), app.screen.query_one(selector))

            await pilot.click("#action-cancel")
            await pilot.pause()
            assert app.screen.query("#resource-food")

            await pilot.click("#tech-agriculture")
            await pilot.pause()

            for selector in ["#action-build", "#action-cancel"]:
                assert_inside(app.screen.query_one("#game-side-shell"), app.screen.query_one(selector))

            await pilot.click("#action-cancel")
            await pilot.pause()
            assert app.screen.query("#resource-food")

    asyncio.run(runner())


def test_tui_terrain_choice_row_fits_and_road_choice_builds_road(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-play")
            await pilot.pause()
            await pilot.click("#setup-start")
            await pilot.pause()

            state = app.active_session.state
            city_seed = next(
                coord
                for coord in state.board
                if validate_action(state, Action.build_city(coord)).is_valid
            )
            await click_map_coord(pilot, app, city_seed)
            await pilot.click("#action-build")
            await pilot.pause()

            state = app.active_session.state
            dual_choice = next(
                coord
                for coord in state.board
                if validate_action(state, Action.build_city(coord)).is_valid
                and validate_action(state, Action.build_road(coord)).is_valid
            )
            await click_map_coord(pilot, app, dual_choice)
            assert_inside(app.screen.query_one("#game-side-shell"), app.screen.query_one("#action-choice-city"))
            assert_inside(app.screen.query_one("#game-side-shell"), app.screen.query_one("#action-choice-road"))

            await pilot.click("#action-choice-road")
            await pilot.pause()
            await pilot.click("#action-build")
            await pilot.pause()

            assert any(road.coord == dual_choice for road in app.active_session.state.roads.values())
            assert not any(city.coord == dual_choice for city in app.active_session.state.cities.values())

    asyncio.run(runner())


def test_tui_single_terrain_choice_uses_square_button(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-play")
            await pilot.pause()
            await pilot.click("#setup-start")
            await pilot.pause()

            state = app.active_session.state
            city_only = next(
                coord
                for coord in state.board
                if validate_action(state, Action.build_city(coord)).is_valid
                and not validate_action(state, Action.build_road(coord)).is_valid
            )

            await click_map_coord(pilot, app, city_only)
            await pilot.pause()

            choice_widget = app.screen.query_one("#action-choice-city", PanelButton)
            assert choice_widget is not None
            assert app.screen.query("#action-build")

    asyncio.run(runner())


def test_tui_manual_mode_places_tip_bottom_right_and_feedbacks_on_researched_tech(tmp_path) -> None:
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

            await click_map_coord(pilot, app, buildable)
            await pilot.click("#action-build")
            await pilot.pause()

            city = next(iter(app.active_session.state.cities.values()))
            app.active_session.state.networks[city.network_id].unlocked_techs.add(TechType.AGRICULTURE)

            await click_map_coord(pilot, app, city.coord)
            await pilot.pause()
            await pilot.click("#tech-agriculture")
            await pilot.pause()

            side_shell = app.screen.query_one("#game-side-shell")
            info = app.screen.query_one("#game-side-info")
            assert "already unlocked" in app.active_session.state.message.lower()
            assert info.region.bottom <= side_shell.region.bottom
            assert info.region.bottom >= side_shell.region.bottom - 1

    asyncio.run(runner())


def test_tui_autoplay_hides_manual_context_and_ignores_map_clicks(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-autoplay")
            await pilot.pause()
            await pilot.click("#setup-start")
            await pilot.pause()

            assert app.current_route is ScreenRoute.GAME
            assert not app.screen.query("#game-context-shell")
            assert not [w.id for w in app.screen.query("Button") if w.id and w.id.startswith("action-")]

            metric_panel = app.screen.query_one("#game-metric-panel")
            side_shell = app.screen.query_one("#game-side-shell")
            info_widget = app.screen.query_one("#game-metric-panel-info")
            assert metric_panel.region.height >= side_shell.region.height - 1
            assert info_widget.region.bottom <= side_shell.region.bottom

            before = app.active_session.state.selection.selected_coord
            coord = next(iter(app.active_session.state.board))
            await click_map_coord(pilot, app, coord)
            assert app.active_session.state.selection.selected_coord == before

    asyncio.run(runner())


def test_tui_small_viewport_manual_panels_and_metric_digits_fit(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-play")
            await pilot.pause()
            await pilot.click("#setup-start")
            await pilot.pause()

            assert_inside(app.screen.query_one("#game-side-shell"), app.screen.query_one("#game-metric-panel-score"))
            assert_inside(app.screen.query_one("#game-side-shell"), app.screen.query_one("#game-metric-panel-step"))

            state = app.active_session.state
            buildable = next(
                coord
                for coord in state.board
                if validate_action(state, Action.build_city(coord)).is_valid
            )

            await click_map_coord(pilot, app, buildable)
            await pilot.click("#action-build")
            await pilot.pause()

            city_coord = next(city.coord for city in app.active_session.state.cities.values())
            await click_map_coord(pilot, app, city_coord)
            for selector in ["#resource-food", "#resource-wood", "#tech-agriculture", "#action-cancel"]:
                assert_inside(app.screen.query_one("#game-side-shell"), app.screen.query_one(selector))

    asyncio.run(runner())


def test_tui_small_viewport_final_and_records_layouts_fit(tmp_path) -> None:
    paths = build_app_paths(tmp_path)
    store = RecordStore(paths.records_file)
    store.append_completed_game(build_completed_state(), timestamp="2026-04-09T10:00:00+08:00")
    store.append_completed_game(build_completed_state(), timestamp="2026-04-09T10:30:00+08:00")

    async def runner() -> None:
        app = MicroCivApp(paths=paths)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-records")
            await pilot.pause()

            scroll = app.screen.query_one("#records-scroll")
            assert_inside(scroll, app.screen.query_one("#record-card-2"))
            assert_inside(scroll, app.screen.query_one("#record-card-1"))

            await pilot.click("#records-back")
            await pilot.pause()
            await pilot.click("#menu-autoplay")
            await pilot.pause()
            await pilot.click("#setup-playback")
            await pilot.click("#setup-turn-limit")
            await pilot.click("#setup-turn-limit")
            await pilot.click("#setup-turn-limit")
            await pilot.click("#setup-start")
            await pilot.pause(1.0)

            side_shell = app.screen.query_one("#final-side-shell")
            for selector in ["#final-score-value", "#final-restart", "#final-menu", "#final-exit"]:
                assert_inside(side_shell, app.screen.query_one(selector))

    asyncio.run(runner())


def test_tui_large_map_fits_main_game_shell_and_four_digit_score_fits_final_side_shell(tmp_path) -> None:
    async def runner() -> None:
        app = MicroCivApp(paths=build_app_paths(tmp_path))
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-play")
            await pilot.pause()
            for _ in range(4):
                await pilot.click("#setup-map-size")
                await pilot.pause()
            await pilot.click("#setup-start")
            await pilot.pause()

            assert app.current_route is ScreenRoute.GAME
            assert_inside(app.screen.query_one("#game-map-shell"), app.screen.query_one("#game-map"))

        state = build_completed_state()
        state.score = 1000
        session = GameSession(state=state, engine=GameEngine(state))

        class FinalDemoApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(FinalScreen(session))

        final_app = FinalDemoApp()
        async with final_app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            side_shell = final_app.screen.query_one("#final-side-shell")
            assert_inside(side_shell, final_app.screen.query_one("#final-score-value"))
            assert final_app.screen.query_one("#final-score-value", ImageSurface).image is not None

    asyncio.run(runner())


def test_tui_records_odd_last_card_keeps_same_width_as_other_cards(tmp_path) -> None:
    paths = build_app_paths(tmp_path)
    store = RecordStore(paths.records_file)
    store.append_completed_game(build_completed_state(), timestamp="2026-04-09T10:00:00+08:00")
    store.append_completed_game(build_completed_state(), timestamp="2026-04-09T10:30:00+08:00")
    store.append_completed_game(build_completed_state(), timestamp="2026-04-09T11:00:00+08:00")

    async def runner() -> None:
        app = MicroCivApp(paths=paths)
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-records")
            await pilot.pause()

            card1 = app.screen.query_one("#record-card-3")
            card2 = app.screen.query_one("#record-card-2")
            card3 = app.screen.query_one("#record-card-1")
            assert card1.region.width == card3.region.width
            assert abs(card1.region.width - card2.region.width) <= 1

    asyncio.run(runner())


def test_tui_records_two_column_gutter_is_one_cell(tmp_path) -> None:
    paths = build_app_paths(tmp_path)
    store = RecordStore(paths.records_file)
    store.append_completed_game(build_completed_state(), timestamp="2026-04-09T10:00:00+08:00")
    store.append_completed_game(build_completed_state(), timestamp="2026-04-09T10:30:00+08:00")

    async def runner() -> None:
        app = MicroCivApp(paths=paths)
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#menu-records")
            await pilot.pause()

            left = app.screen.query_one("#record-card-2")
            right = app.screen.query_one("#record-card-1")
            gap = app.screen.query_one(".record-card-gap")
            assert gap.region.width == 1
            assert right.region.x - left.region.right == 1

    asyncio.run(runner())
