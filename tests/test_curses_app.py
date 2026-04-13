from __future__ import annotations

from pathlib import Path

from microciv.config import build_app_paths
from microciv.curses_app import CursesMicroCivApp, MicroCivController, Rect, ScreenRoute
from microciv.game.actions import Action, validate_action
from microciv.game.enums import Mode, PlaybackMode, PolicyType


def test_controller_can_open_setup_and_toggle_random_autoplay(tmp_path: Path) -> None:
    controller = MicroCivController(paths=build_app_paths(tmp_path))

    controller.click("menu-autoplay")
    assert controller.current_route is ScreenRoute.SETUP_AUTOPLAY
    assert controller.setup_state.config.policy_type is PolicyType.BASELINE

    controller.click("setup-ai-type")
    assert controller.setup_state.config.policy_type is PolicyType.RANDOM

    controller.click("setup-playback")
    assert controller.setup_state.config.playback_mode is PlaybackMode.SPEED


def test_controller_can_start_manual_session_and_build_city(tmp_path: Path) -> None:
    controller = MicroCivController(paths=build_app_paths(tmp_path))

    controller.click("menu-play")
    controller.click("setup-start")

    assert controller.current_route is ScreenRoute.GAME
    assert controller.active_session is not None
    assert controller.active_session.state.config.mode is Mode.PLAY

    buildable = next(
        coord
        for coord in controller.active_session.state.board
        if validate_action(controller.active_session.state, Action.build_city(coord)).is_valid
    )

    controller.select_coord(buildable)
    assert "game-build-city" in controller.available_game_actions()
    controller.click("game-build-city")

    assert len(controller.active_session.state.cities) == 1


def test_controller_keyboard_shortcuts_cover_menu_and_records_navigation(tmp_path: Path) -> None:
    controller = MicroCivController(paths=build_app_paths(tmp_path))
    controller.click("menu-play")
    controller.click("setup-start")

    controller.press_key("m")
    assert controller.current_route is ScreenRoute.GAME_MENU

    controller.press_key("q")
    assert controller.current_route is ScreenRoute.GAME

    controller.return_to_menu()
    controller.click("menu-records")
    assert controller.current_route is ScreenRoute.RECORDS_LIST


def test_autoplay_reaches_final_and_saves_record(tmp_path: Path) -> None:
    controller = MicroCivController(paths=build_app_paths(tmp_path))
    controller.click("menu-autoplay")
    controller.click("setup-ai-type")
    controller.click("setup-start")

    controller.advance_autoplay()

    assert controller.current_route is ScreenRoute.FINAL
    assert controller.active_session is not None
    assert controller.active_session.saved_record is not None
    assert controller.active_session.saved_record.ai_type == "Random"
    assert len(controller.reload_records().records) == 1


def test_app_mouse_dispatch_uses_rendered_hitboxes(tmp_path: Path) -> None:
    app = CursesMicroCivApp(paths=build_app_paths(tmp_path))
    app.render_state.button_regions["menu-play"] = Rect(10, 5, 8)

    app._handle_mouse(11, 5, 1)

    assert app.controller.current_route is ScreenRoute.SETUP_PLAY
