"""Shared page-route names for the Textual application."""

from __future__ import annotations

from enum import StrEnum


class ScreenRoute(StrEnum):
    MAIN_MENU = "main-menu-screen"
    SETUP_PLAY = "setup-play-screen"
    SETUP_AUTOPLAY = "setup-autoplay-screen"
    GAME = "game-screen"
    GAME_MENU = "game-menu-screen"
    FINAL = "final-screen"
    RECORDS_LIST = "records-list-screen"
    RECORD_DETAIL = "record-detail-screen"
