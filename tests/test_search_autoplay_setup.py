from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from microciv.game.enums import MapDifficulty, Mode, PlaybackMode, PolicyType

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "search_autoplay_setup.py"
SPEC = importlib.util.spec_from_file_location("search_autoplay_setup", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
search_autoplay_setup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = search_autoplay_setup
SPEC.loader.exec_module(search_autoplay_setup)


def test_build_search_autoplay_config_uses_fixed_search_speed() -> None:
    args = search_autoplay_setup._parse_args(
        [
            "--difficulty",
            "hard",
            "--map-size",
            "20",
            "--turns",
            "150",
            "--seed",
            "397",
        ]
    )

    config = search_autoplay_setup.build_search_autoplay_config(args)

    assert config.mode is Mode.AUTOPLAY
    assert config.map_size == 20
    assert config.turn_limit == 150
    assert config.map_difficulty is MapDifficulty.HARD
    assert config.policy_type is PolicyType.SEARCH
    assert config.playback_mode is PlaybackMode.SPEED
    assert config.seed == 397


def test_search_autoplay_config_accepts_parameter_aliases() -> None:
    args = search_autoplay_setup._parse_args(
        [
            "--map-difficulty",
            "normal",
            "--map-size",
            "12",
            "--turn-limit",
            "30",
            "--seed",
            "84",
        ]
    )

    config = search_autoplay_setup.build_search_autoplay_config(args)

    assert config.map_difficulty is MapDifficulty.NORMAL
    assert config.map_size == 12
    assert config.turn_limit == 30
    assert config.seed == 84
