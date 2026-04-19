"""Batch autoplay runner for AI data collection."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from microciv.game.enums import MapDifficulty, PlaybackMode, PolicyType  # noqa: E402
from microciv.game.models import GameConfig  # noqa: E402
from microciv.records.models import CSV_FIELD_ORDER, RecordDatabase, RecordEntry  # noqa: E402
from microciv.session import create_game_session  # noqa: E402

PROGRESS_STEPS: Final[int] = 20


@dataclass(frozen=True, slots=True)
class BatchGameTask:
    seed: int
    policy_type: PolicyType
    map_size: int
    turn_limit: int
    map_difficulty: MapDifficulty


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _default_worker_count() -> int:
    cpu_count = os.process_cpu_count() or 1
    return max(1, cpu_count - 1)


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
    parser.add_argument(
        "--workers",
        type=_positive_int,
        default=_default_worker_count(),
        help="Number of worker processes (default: CPU count minus one).",
    )
    parser.add_argument(
        "--chunksize",
        type=_positive_int,
        default=8,
        help="Process pool chunksize for task dispatch (default: 8).",
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


def run_single_game_task(task: BatchGameTask) -> RecordEntry:
    return run_single_game(
        seed=task.seed,
        policy_type=task.policy_type,
        map_size=task.map_size,
        turn_limit=task.turn_limit,
        map_difficulty=task.map_difficulty,
    )


def build_batch_tasks(
    *,
    games: int,
    seed_start: int,
    policy_type: PolicyType,
    map_size: int,
    turn_limit: int,
    map_difficulty: MapDifficulty,
) -> list[BatchGameTask]:
    return [
        BatchGameTask(
            seed=seed_start + index,
            policy_type=policy_type,
            map_size=map_size,
            turn_limit=turn_limit,
            map_difficulty=map_difficulty,
        )
        for index in range(games)
    ]


def _progress_interval(total_tasks: int) -> int:
    return max(1, total_tasks // PROGRESS_STEPS)


def _print_progress(
    *,
    completed: int,
    total: int,
    started_at: float,
    mode: str,
) -> None:
    elapsed = time.perf_counter() - started_at
    average = elapsed / max(completed, 1)
    remaining = average * max(total - completed, 0)
    print(
        f"[{mode}] {completed}/{total} games complete in {elapsed:.2f}s "
        f"({average:.3f}s per game, eta {remaining:.2f}s)",
        file=sys.stderr,
    )


def run_batch_tasks_serial(tasks: list[BatchGameTask]) -> list[RecordEntry]:
    records: list[RecordEntry] = []
    progress_interval = _progress_interval(len(tasks))
    started_at = time.perf_counter()
    for index, task in enumerate(tasks, start=1):
        records.append(run_single_game_task(task))
        if index == len(tasks) or index % progress_interval == 0:
            _print_progress(completed=index, total=len(tasks), started_at=started_at, mode="serial")
    return records


def run_batch_tasks_parallel(
    tasks: list[BatchGameTask],
    *,
    workers: int,
    chunksize: int,
) -> list[RecordEntry]:
    records: list[RecordEntry] = []
    progress_interval = _progress_interval(len(tasks))
    started_at = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for index, record in enumerate(
            executor.map(run_single_game_task, tasks, chunksize=chunksize),
            start=1,
        ):
            records.append(record)
            if index == len(tasks) or index % progress_interval == 0:
                _print_progress(
                    completed=index,
                    total=len(tasks),
                    started_at=started_at,
                    mode="parallel",
                )
    return records


def _write_database_json(path: Path, database: RecordDatabase) -> None:
    path.write_text(
        json.dumps(database.to_dict(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_database_csv(path: Path, records: list[RecordEntry]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_FIELD_ORDER))
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())


def main() -> int:
    args = _parse_args()
    policy_type = _policy_type_from_str(args.policy)
    map_difficulty = _map_difficulty_from_str(args.map_difficulty)
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks = build_batch_tasks(
        games=args.games,
        seed_start=args.seed_start,
        policy_type=policy_type,
        map_size=args.map_size,
        turn_limit=args.turn_limit,
        map_difficulty=map_difficulty,
    )
    execution_mode = "serial" if args.workers == 1 else "parallel"
    total_start = time.perf_counter()
    print(
        f"Batch plan: {args.games} games, mode={execution_mode}, "
        f"workers={args.workers}, chunksize={args.chunksize}",
        file=sys.stderr,
    )
    records = (
        run_batch_tasks_serial(tasks)
        if args.workers == 1
        else run_batch_tasks_parallel(tasks, workers=args.workers, chunksize=args.chunksize)
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
        _write_database_json(json_path, database)
        print(f"JSON exported: {json_path}", file=sys.stderr)

    if not args.no_export_csv:
        csv_path = output_dir / f"{base_name}.csv"
        _write_database_csv(csv_path, records)
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
            "workers": args.workers,
            "chunksize": args.chunksize,
            "execution_mode": execution_mode,
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
