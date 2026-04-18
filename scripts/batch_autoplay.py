"""Batch autoplay runner for AI data collection."""

from __future__ import annotations

import argparse
import csv
import json
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
        "--label",
        type=str,
        default="",
        help="Optional label appended to output filenames.",
    )
    parser.add_argument(
        "--no-export-json",
        action="store_true",
        help="Disable JSON export.",
    )
    parser.add_argument(
        "--no-export-csv",
        action="store_true",
        help="Disable CSV export.",
    )
    parser.add_argument(
        "--no-write-summary",
        action="store_true",
        help="Disable summary JSON export.",
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
    run_tag = args.label.strip().replace(" ", "_")
    base_name = (
        f"{args.policy}_{args.map_size}_{args.turn_limit}_{args.map_difficulty}_"
        f"{args.seed_start}_{args.seed_start + args.games - 1}"
    )
    if run_tag:
        base_name = f"{base_name}_{run_tag}"

    if not args.no_export_json:
        json_path = output_dir / f"{base_name}.json"
        json_path.write_text(
            json.dumps(database.to_dict(), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"JSON exported: {json_path}", file=sys.stderr)

    if not args.no_export_csv:
        csv_path = output_dir / f"{base_name}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(CSV_FIELD_ORDER))
            writer.writeheader()
            for record in records:
                writer.writerow(record.to_csv_row())
        print(f"CSV exported: {csv_path}", file=sys.stderr)

    if not args.no_write_summary:
        summary_path = output_dir / f"{base_name}_summary.json"
        summary = {
            "games": args.games,
            "policy": args.policy,
            "map_size": args.map_size,
            "turn_limit": args.turn_limit,
            "map_difficulty": args.map_difficulty,
            "seed_start": args.seed_start,
            "seed_end": args.seed_start + args.games - 1,
            "total_elapsed_seconds": round(total_elapsed, 3),
            "avg_elapsed_seconds": round(total_elapsed / args.games, 3),
            "avg_score": round(sum(record.final_score for record in records) / len(records), 2),
            "max_score": max(record.final_score for record in records),
            "min_score": min(record.final_score for record in records),
            "avg_city_count": round(sum(record.city_count for record in records) / len(records), 2),
            "avg_building_count": round(
                sum(record.building_count for record in records) / len(records), 2
            ),
            "avg_network_count": round(
                sum(len(record.networks) for record in records) / len(records), 2
            ),
        }
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Summary exported: {summary_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
