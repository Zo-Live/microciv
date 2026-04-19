"""Generate a large labeled dataset for AI rule analysis."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from time import perf_counter
from typing import Final

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from microciv.game.enums import MapDifficulty, PlaybackMode, PolicyType  # noqa: E402
from microciv.game.models import GameConfig  # noqa: E402
from microciv.records.models import CSV_FIELD_ORDER, RecordDatabase, RecordEntry  # noqa: E402
from microciv.session import create_game_session  # noqa: E402

GREEDY_LABEL: Final[str] = "Greedy"
RANDOM_LABEL: Final[str] = "Random"
PROGRESS_STEPS: Final[int] = 20


@dataclass(frozen=True, slots=True)
class GameTask:
    task_index: int
    record_id: int
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
    parser = argparse.ArgumentParser(description="Generate large MicroCiv dataset.")
    parser.add_argument(
        "-n", "--games-per-combo", type=int, default=10, help="Games per parameter combo."
    )
    parser.add_argument(
        "--seed-start", type=int, default=1, help="Global starting seed offset."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "exports" / "dataset",
        help="Output directory.",
    )
    parser.add_argument(
        "--policies",
        type=str,
        default="greedy,random",
        help="Comma-separated policies.",
    )
    parser.add_argument(
        "--map-sizes",
        type=str,
        default="12,16,20,24",
        help="Comma-separated map sizes.",
    )
    parser.add_argument(
        "--turn-limits",
        type=str,
        default="30,50,80,100,150",
        help="Comma-separated turn limits.",
    )
    parser.add_argument(
        "--difficulties",
        type=str,
        default="normal,hard",
        help="Comma-separated difficulties.",
    )
    parser.add_argument(
        "--label",
        type=str,
        default="",
        help="Optional label appended to output filenames.",
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


def _policy_type(value: str) -> PolicyType:
    if value == "greedy":
        return PolicyType.GREEDY
    if value == "random":
        return PolicyType.RANDOM
    raise ValueError(value)


def _map_difficulty(value: str) -> MapDifficulty:
    if value == "normal":
        return MapDifficulty.NORMAL
    if value == "hard":
        return MapDifficulty.HARD
    raise ValueError(value)


def _parse_csv_values(raw: str, *, field_name: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if values:
        return values
    raise ValueError(f"{field_name} must contain at least one value.")


def run_game(
    *,
    record_id: int,
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
        record_id=record_id,
        timestamp=timestamp,
        state=session.state,
    )


def run_game_task(task: GameTask) -> RecordEntry:
    return run_game(
        record_id=task.record_id,
        seed=task.seed,
        policy_type=task.policy_type,
        map_size=task.map_size,
        turn_limit=task.turn_limit,
        map_difficulty=task.map_difficulty,
    )


def _record_match_key(record: RecordEntry) -> tuple[int, int, int, str]:
    return (record.seed, record.map_size, record.turn_limit, record.map_difficulty)


def _build_random_index(
    records: list[RecordEntry],
) -> dict[tuple[int, int, int, str], RecordEntry]:
    return {
        _record_match_key(record): record
        for record in records
        if record.ai_type == RANDOM_LABEL
    }


def collect_greedy_anomalies(
    records: list[RecordEntry],
) -> tuple[list[RecordEntry], dict[str, int]]:
    random_index = _build_random_index(records)
    anomalies: list[RecordEntry] = []
    negative_score_count = 0
    under_random_count = 0
    for record in records:
        if record.ai_type != GREEDY_LABEL:
            continue
        random_peer = random_index.get(_record_match_key(record))
        is_negative_score = record.final_score < 0
        is_under_random = (
            random_peer is not None and record.final_score < random_peer.final_score
        )
        if not is_negative_score and not is_under_random:
            continue
        if is_negative_score:
            negative_score_count += 1
        if is_under_random:
            under_random_count += 1
        anomalies.append(record)
    return anomalies, {
        "negative_score_anomaly_count": negative_score_count,
        "under_random_anomaly_count": under_random_count,
    }


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


def build_game_tasks(
    *,
    seed_start: int,
    games_per_combo: int,
    policies: list[PolicyType],
    base_combos: list[tuple[int, int, str]],
) -> tuple[list[GameTask], int]:
    tasks: list[GameTask] = []
    next_record_id = 1
    seed = seed_start
    for map_size, turn_limit, difficulty in base_combos:
        map_difficulty = _map_difficulty(difficulty)
        for _ in range(games_per_combo):
            for policy_type in policies:
                tasks.append(
                    GameTask(
                        task_index=len(tasks),
                        record_id=next_record_id,
                        seed=seed,
                        policy_type=policy_type,
                        map_size=map_size,
                        turn_limit=turn_limit,
                        map_difficulty=map_difficulty,
                    )
                )
                next_record_id += 1
            seed += 1
    return tasks, seed - 1


def _progress_interval(total_tasks: int) -> int:
    return max(1, total_tasks // PROGRESS_STEPS)


def _print_progress(
    *,
    completed: int,
    total: int,
    started_at: float,
    mode: str,
) -> None:
    elapsed = perf_counter() - started_at
    average = elapsed / max(completed, 1)
    remaining = average * max(total - completed, 0)
    print(
        f"[{mode}] {completed}/{total} games complete in {elapsed:.2f}s "
        f"({average:.3f}s per game, eta {remaining:.2f}s)",
        file=sys.stderr,
    )


def run_tasks_serial(tasks: list[GameTask]) -> list[RecordEntry]:
    records: list[RecordEntry] = []
    progress_interval = _progress_interval(len(tasks))
    started_at = perf_counter()
    for index, task in enumerate(tasks, start=1):
        records.append(run_game_task(task))
        if index == len(tasks) or index % progress_interval == 0:
            _print_progress(completed=index, total=len(tasks), started_at=started_at, mode="serial")
    return records


def run_tasks_parallel(
    tasks: list[GameTask],
    *,
    workers: int,
    chunksize: int,
) -> list[RecordEntry]:
    records: list[RecordEntry] = []
    progress_interval = _progress_interval(len(tasks))
    started_at = perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for index, record in enumerate(
            executor.map(run_game_task, tasks, chunksize=chunksize),
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


def main() -> int:
    args = _parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    param_grid = {
        "policy": _parse_csv_values(args.policies, field_name="policies"),
        "map_size": [
            int(item) for item in _parse_csv_values(args.map_sizes, field_name="map_sizes")
        ],
        "turn_limit": [
            int(item) for item in _parse_csv_values(args.turn_limits, field_name="turn_limits")
        ],
        "map_difficulty": _parse_csv_values(args.difficulties, field_name="difficulties"),
    }
    policies = [_policy_type(policy) for policy in param_grid["policy"]]
    base_combos = list(
        product(
            param_grid["map_size"],
            param_grid["turn_limit"],
            param_grid["map_difficulty"],
        )
    )
    tasks, seed_end = build_game_tasks(
        seed_start=args.seed_start,
        games_per_combo=args.games_per_combo,
        policies=policies,
        base_combos=base_combos,
    )
    total_games = len(tasks)
    run_tag = args.label.strip().replace(" ", "_")
    base_name = "dataset"
    if run_tag:
        base_name = f"{base_name}_{run_tag}"
    execution_mode = "serial" if args.workers == 1 else "parallel"

    print(
        f"Dataset plan: {len(base_combos)} base combos x {len(policies)} policies x "
        f"{args.games_per_combo} games = "
        f"{total_games} total",
        file=sys.stderr,
    )
    print(
        f"Execution mode: {execution_mode} (workers={args.workers}, chunksize={args.chunksize})",
        file=sys.stderr,
    )
    batch_start = perf_counter()

    records = (
        run_tasks_serial(tasks)
        if args.workers == 1
        else run_tasks_parallel(tasks, workers=args.workers, chunksize=args.chunksize)
    )

    total_elapsed = perf_counter() - batch_start
    print(
        f"Dataset complete: {total_games} games in {total_elapsed:.2f}s "
        f"({total_elapsed/total_games:.3f}s per game)",
        file=sys.stderr,
    )

    database = RecordDatabase(records=records)
    anomaly_records, anomaly_counts = collect_greedy_anomalies(records)
    anomaly_database = RecordDatabase(records=anomaly_records)
    greedy_record_count = sum(1 for record in records if record.ai_type == GREEDY_LABEL)

    json_path = output_dir / f"{base_name}.json"
    _write_database_json(json_path, database)
    print(f"Dataset JSON exported: {json_path}", file=sys.stderr)

    csv_path = output_dir / f"{base_name}.csv"
    _write_database_csv(csv_path, records)
    print(f"Dataset CSV exported: {csv_path}", file=sys.stderr)

    anomaly_json_path = output_dir / f"{base_name}_anomalies.json"
    _write_database_json(anomaly_json_path, anomaly_database)
    print(f"Anomaly dataset JSON exported: {anomaly_json_path}", file=sys.stderr)

    anomaly_csv_path = output_dir / f"{base_name}_anomalies.csv"
    _write_database_csv(anomaly_csv_path, anomaly_records)
    print(f"Anomaly dataset CSV exported: {anomaly_csv_path}", file=sys.stderr)

    manifest_path = output_dir / f"{base_name}_manifest.json"
    manifest = {
        "games_per_combo": args.games_per_combo,
        "seed_start": args.seed_start,
        "seed_end": seed_end,
        "param_grid": param_grid,
        "combo_count": len(base_combos) * len(policies),
        "base_combo_count": len(base_combos),
        "policy_count": len(policies),
        "workers": args.workers,
        "chunksize": args.chunksize,
        "execution_mode": execution_mode,
        "total_games": total_games,
        "total_elapsed_seconds": round(total_elapsed, 3),
        "avg_elapsed_seconds": round(total_elapsed / total_games, 3),
        "anomaly_count": len(anomaly_records),
        "anomaly_rate": round(len(anomaly_records) / max(greedy_record_count, 1), 4),
        "negative_score_anomaly_count": anomaly_counts["negative_score_anomaly_count"],
        "under_random_anomaly_count": anomaly_counts["under_random_anomaly_count"],
        "anomaly_json_path": str(anomaly_json_path),
        "anomaly_csv_path": str(anomaly_csv_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Dataset manifest exported: {manifest_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
