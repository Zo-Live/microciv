"""Shared page-route names for the Textual application."""

from __future__ import annotations

from enum import StrEnum

from textual.screen import Screen


class ScreenRoute(StrEnum):
    MAIN_MENU = "main-menu-screen"
    SETUP_PLAY = "setup-play-screen"
    SETUP_AUTOPLAY = "setup-autoplay-screen"
    GAME = "game-screen"
    GAME_MENU = "game-menu-screen"
    FINAL = "final-screen"
    RECORDS_LIST = "records-list-screen"
    RECORD_DETAIL = "record-detail-screen"


def route_for_screen(screen: Screen[object] | object) -> ScreenRoute | None:
    """Return the canonical route for a screen-like object."""
    route = getattr(screen, "route", None)
    if isinstance(route, ScreenRoute):
        return route
    if isinstance(route, str):
        try:
            return ScreenRoute(route)
        except ValueError:
            pass

    screen_id = getattr(screen, "id", None)
    if isinstance(screen_id, str):
        try:
            return ScreenRoute(screen_id)
        except ValueError:
            return None
    return None
