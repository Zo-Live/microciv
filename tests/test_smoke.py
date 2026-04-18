from __future__ import annotations

import runpy

import pytest

from microciv.constants import DEFAULT_MAP_SIZE, DEFAULT_TURN_LIMIT
from microciv.game.enums import (
    ActionType,
    Mode,
    PlaybackMode,
    PolicyType,
)
from microciv.game.models import GameConfig


def test_default_game_config_matches_new_defaults() -> None:
    config = GameConfig()

    assert config.mode is Mode.PLAY
    assert config.policy_type is PolicyType.NONE
    assert config.playback_mode is PlaybackMode.NONE
    assert config.map_size == DEFAULT_MAP_SIZE
    assert config.turn_limit == DEFAULT_TURN_LIMIT


def test_action_enum_contains_skip() -> None:
    assert ActionType.SKIP == "skip"


def test_package_main_module_calls_app_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_main() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("microciv.app.main", fake_main)

    runpy.run_module("microciv.__main__", run_name="__main__")

    assert called is True


def test_game_config_rejects_non_enum_map_difficulty() -> None:
    with pytest.raises(ValueError, match="map_difficulty"):
        GameConfig.for_autoplay(
            map_difficulty=None,  # type: ignore[arg-type]
            policy_type=PolicyType.GREEDY,
            playback_mode=PlaybackMode.NORMAL,
        )
