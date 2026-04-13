from __future__ import annotations

from microciv.constants import DEFAULT_MAP_SIZE, DEFAULT_TURN_LIMIT
from microciv.game.enums import ActionType, Mode, PlaybackMode, PolicyType
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
