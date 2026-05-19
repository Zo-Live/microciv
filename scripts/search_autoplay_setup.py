"""Open the Autoplay setup screen with a fixed-seed AI configuration."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from microciv.constants import DEFAULT_MAP_SIZE, DEFAULT_TURN_LIMIT  # noqa: E402
from microciv.curses_app import CursesMicroCivApp  # noqa: E402
from microciv.game.enums import MapDifficulty, PlaybackMode, PolicyType  # noqa: E402
from microciv.game.models import GameConfig  # noqa: E402


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = _build_parser()
    return parser.parse_args(argv)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open MicroCiv Autoplay setup for a fixed-seed AI run."
    )
    parser.add_argument(
        "--policy",
        choices=[
            PolicyType.GREEDY.value,
            PolicyType.RANDOM.value,
            PolicyType.SEARCH.value,
        ],
        default=PolicyType.SEARCH.value,
        help="AI policy to use (default: search).",
    )
    parser.add_argument(
        "--difficulty",
        "--map-difficulty",
        dest="difficulty",
        choices=[MapDifficulty.NORMAL.value, MapDifficulty.HARD.value],
        default=MapDifficulty.NORMAL.value,
        help="Map difficulty (default: normal).",
    )
    parser.add_argument(
        "--map-size",
        type=int,
        default=DEFAULT_MAP_SIZE,
        help=f"Map size (default: {DEFAULT_MAP_SIZE}).",
    )
    parser.add_argument(
        "--turns",
        "--turn-limit",
        dest="turn_limit",
        type=int,
        default=DEFAULT_TURN_LIMIT,
        help=f"Turn limit (default: {DEFAULT_TURN_LIMIT}).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        required=True,
        help="Map seed to preview and run.",
    )
    return parser


def build_search_autoplay_config(args: argparse.Namespace) -> GameConfig:
    return GameConfig.for_autoplay(
        map_size=args.map_size,
        turn_limit=args.turn_limit,
        map_difficulty=MapDifficulty(args.difficulty),
        policy_type=PolicyType(args.policy),
        playback_mode=PlaybackMode.SPEED,
        seed=args.seed,
    )


def open_search_autoplay_setup(config: GameConfig) -> None:
    app = CursesMicroCivApp()
    app.controller.open_setup_for_autoplay(config=config)
    app.run()


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        config = build_search_autoplay_config(args)
    except ValueError as exc:
        parser.error(str(exc))
    open_search_autoplay_setup(config)


if __name__ == "__main__":
    main()
