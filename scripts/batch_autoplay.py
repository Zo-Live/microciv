"""Batch autoplay runner for AI data collection."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from microciv.game.enums import MapDifficulty, PlaybackMode, PolicyType  # noqa: E402
from microciv.game.models import GameConfig  # noqa: E402
from microciv.records.export import export_records_json  # noqa: E402
from microciv.records.models import CSV_FIELD_ORDER, RecordDatabase, RecordEntry  # noqa: E402
from microciv.session import create_game_session  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AI autoplay games in batch.")
    parser.add_argument(
        "-n", "--games", type=int, default=100, help="Number of games to run (default: 100)."
    )
    parser.add_argument(
        "--policy",
        type=str,
        default="greedy",
        choices=["greedy", "random"],
        help="AI policy to use (default: greedy).",
    )
    parser.add_argument(
        "--map-size", type=int, default=16, help="Map size (default: 16)."
    )
    parser.add_argument(
        "--turn-limit", type=int, default=80, help="Turn limit (default: 80)."
    )
    parser.add_argument(
        "--map-difficulty",
        type=str,
        default="normal",
        choices=["normal", "hard"],
        help="Map difficulty (default: normal).",
    )
    parser.add_argument(
        "--seed-start", type=int, default=1, help="Starting seed value (default: 1)."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "exports" / "batch",
        help="Output directory for results.",
    )
    parser.add_argument(
        "--export-json",
        action="store_true",
        default=True,
        help="Export full results as JSON (default: True).",
    )
    parser.add_argument(
        "--export-csv",
        action="store_true",
        default=True,
        help="Export summary as CSV (default: True).",
    )
    return parser.parse_args()


def _policy_type_from_str(value: str) -> PolicyType:
    if value == "greedy":
        return PolicyType.GREEDY
    if value == "random":
        return PolicyType.RANDOM
    raise ValueError(f"Unknown policy: {value}")


def _map_difficulty_from_str(value: str) -> MapDifficulty:
    if value == "normal":
        return MapDifficulty.NORMAL
    if value == "hard":
        return MapDifficulty.HARD
    raise ValueError(f"Unknown difficulty: {value}")


def run_single_game(
    *,
    seed: int,
    policy_type: PolicyType,
    map_size: int,
    turn_limit: int,
    map_difficulty: MapDifficulty,
) -> RecordEntry:
    config = GameConfig.for_autoplay(
        map_size=map_size,
        turn_limit=turn_limit,
        map_difficulty=map_difficulty,
        policy_type=policy_type,
        playback_mode=PlaybackMode.SPEED,
        seed=seed,
    )
    session = create_game_session(config)

    while not session.state.is_game_over:
        session.step_autoplay()

    timestamp = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    return RecordEntry.from_game_state(
        record_id=seed,
        timestamp=timestamp,
        state=session.state,
    )


def main() -> int:
    args = _parse_args()
    policy_type = _policy_type_from_str(args.policy)
    map_difficulty = _map_difficulty_from_str(args.map_difficulty)
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    records: list[RecordEntry] = []
    total_start = time.perf_counter()

    for i in range(args.games):
        seed = args.seed_start + i
        game_start = time.perf_counter()
        record = run_single_game(
            seed=seed,
            policy_type=policy_type,
            map_size=args.map_size,
            turn_limit=args.turn_limit,
            map_difficulty=map_difficulty,
        )
        game_elapsed = time.perf_counter() - game_start
        records.append(record)
        print(
            f"[{i + 1}/{args.games}] seed={seed} score={record.final_score} "
            f"turns={record.actual_turns} cities={record.city_count} "
            f"time={game_elapsed:.2f}s",
            file=sys.stderr,
        )

    total_elapsed = time.perf_counter() - total_start
    print(
        f"Batch complete: {args.games} games in {total_elapsed:.2f}s "
        f"({total_elapsed / args.games:.2f}s per game)",
        file=sys.stderr,
    )

    database = RecordDatabase(records=records)

    if args.export_json:
        json_path = export_records_json(database, output_dir)
        print(f"JSON exported: {json_path}", file=sys.stderr)

    if args.export_csv:
        csv_path = output_dir / "records_export.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(CSV_FIELD_ORDER))
            writer.writeheader()
            for record in records:
                writer.writerow(record.to_csv_row())
        print(f"CSV exported: {csv_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
