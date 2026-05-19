"""Batch autoplay runner for AI data collection."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, process_time
from typing import Final

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from microciv.constants import (  # noqa: E402
    DEFAULT_SEARCH_BEAM_WIDTH,
    DEFAULT_SEARCH_CANDIDATE_LIMIT,
    DEFAULT_SEARCH_DEPTH,
    DEFAULT_SEARCH_MAX_DEPTH,
)
from microciv.game.enums import MapDifficulty, PlaybackMode, PolicyType  # noqa: E402
from microciv.game.models import GameConfig  # noqa: E402
from microciv.records.artifacts import (  # noqa: E402
    ARTIFACT_MANIFEST_FILENAME,
    ARTIFACT_TABLES,
    ArtifactWriteResult,
    dumps_json_bytes,
    write_artifact_manifest,
    write_record_artifacts,
)
from microciv.records.models import (  # noqa: E402
    CSV_FIELD_ORDER,
    RECORDS_SCHEMA_VERSION,
    RecordDatabase,
    RecordEntry,
)
from microciv.session import create_game_session  # noqa: E402
from microciv.utils.files import atomic_output_path, write_bytes_atomic  # noqa: E402
from microciv.utils.process_pool import (  # noqa: E402
    shutdown_process_pool_gracefully,
    shutdown_process_pool_now,
)

PROGRESS_STEPS: Final[int] = 20
DEFAULT_FULL_JSON_THRESHOLD: Final[int] = 1000
AUTO_CHUNKSIZE: Final[str] = "auto"
AUTO_CHUNKSIZE_TARGET_BATCHES_PER_WORKER: Final[int] = 8
AUTO_CHUNKSIZE_MAX: Final[int] = 64
DEFAULT_PROGRESS_INTERVAL_SECONDS: Final[float] = 10.0


@dataclass(frozen=True, slots=True)
class BatchGameTask:
    task_index: int
    seed: int
    policy_type: PolicyType
    map_size: int
    turn_limit: int
    map_difficulty: MapDifficulty
    search_depth: int = DEFAULT_SEARCH_DEPTH
    search_max_depth: int = DEFAULT_SEARCH_MAX_DEPTH
    search_beam_width: int = DEFAULT_SEARCH_BEAM_WIDTH
    search_candidate_limit: int = DEFAULT_SEARCH_CANDIDATE_LIMIT


@dataclass(frozen=True, slots=True)
class BatchGameTaskBatch:
    batch_index: int
    tasks: tuple[BatchGameTask, ...]
    part_dir: Path
    artifact_dir: Path | None
    artifact_format: str
    effective_artifact_mode: str
    write_json_part: bool
    write_csv_part: bool


@dataclass(frozen=True, slots=True)
class BatchRecordSummary:
    task_index: int
    record_id: int
    seed: int
    final_score: int
    city_count: int
    building_count: int
    network_count: int


@dataclass(frozen=True, slots=True)
class BatchWorkerResult:
    batch_index: int
    completed: int
    summaries: list[BatchRecordSummary]
    record_part_path: str = ""
    csv_part_path: str = ""
    artifact_file_format: str = ""
    artifact_table_paths: dict[str, list[str]] = field(default_factory=dict)
    artifact_row_counts: dict[str, int] = field(default_factory=dict)
    worker_elapsed_seconds: float = 0.0
    worker_cpu_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class BatchRunResult:
    batch_results: list[BatchWorkerResult]
    summaries: list[BatchRecordSummary]
    run_elapsed_seconds: float


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def _chunksize_arg(value: str) -> int | str:
    if value == AUTO_CHUNKSIZE:
        return AUTO_CHUNKSIZE
    return _positive_int(value)


def _default_worker_count() -> int:
    cpu_count = os.cpu_count() or 1
    return max(1, cpu_count - 1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AI autoplay games in batch.")
    parser.add_argument(
        "-n",
        "--games",
        type=_positive_int,
        default=100,
        help="Number of games to run (default: 100).",
    )
    parser.add_argument(
        "--policy",
        type=str,
        default="greedy",
        choices=["greedy", "random", "search"],
        help="AI policy to use (default: greedy).",
    )
    parser.add_argument(
        "--search-depth",
        type=_positive_int,
        default=DEFAULT_SEARCH_DEPTH,
        help=f"Search horizon depth (default: {DEFAULT_SEARCH_DEPTH}).",
    )
    parser.add_argument(
        "--search-max-depth",
        type=_positive_int,
        default=DEFAULT_SEARCH_MAX_DEPTH,
        help=f"Search dynamic maximum depth (default: {DEFAULT_SEARCH_MAX_DEPTH}).",
    )
    parser.add_argument(
        "--search-beam-width",
        type=_positive_int,
        default=DEFAULT_SEARCH_BEAM_WIDTH,
        help=f"Search beam width (default: {DEFAULT_SEARCH_BEAM_WIDTH}).",
    )
    parser.add_argument(
        "--search-candidate-limit",
        type=_positive_int,
        default=DEFAULT_SEARCH_CANDIDATE_LIMIT,
        help=f"Search candidate limit per node (default: {DEFAULT_SEARCH_CANDIDATE_LIMIT}).",
    )
    parser.add_argument("--map-size", type=int, default=16, help="Map size (default: 16).")
    parser.add_argument("--turn-limit", type=int, default=80, help="Turn limit (default: 80).")
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
        type=_chunksize_arg,
        default=8,
        help="Task batch size for worker dispatch, or 'auto' (default: 8).",
    )
    parser.add_argument(
        "--artifact-mode",
        type=str,
        default="auto",
        choices=["auto", "compat", "fast", "dual"],
        help=(
            "Output mode: compat keeps legacy JSON/CSV, fast writes analysis artifacts, "
            "dual writes both, auto switches by --full-json-threshold."
        ),
    )
    parser.add_argument(
        "--artifact-format",
        type=str,
        default="parquet",
        choices=["parquet", "jsonl"],
        help="Preferred artifact file format (default: parquet, falls back to jsonl).",
    )
    parser.add_argument(
        "--full-json-threshold",
        type=_positive_int,
        default=DEFAULT_FULL_JSON_THRESHOLD,
        help=(
            "Maximum game count for auto mode to keep full legacy JSON "
            f"(default: {DEFAULT_FULL_JSON_THRESHOLD})."
        ),
    )
    parser.add_argument(
        "--progress-interval-seconds",
        type=_positive_float,
        default=DEFAULT_PROGRESS_INTERVAL_SECONDS,
        help=(
            "Minimum seconds between progress heartbeats "
            f"(default: {DEFAULT_PROGRESS_INTERVAL_SECONDS:g})."
        ),
    )
    return parser.parse_args()


def _policy_type_from_str(value: str) -> PolicyType:
    if value == "greedy":
        return PolicyType.GREEDY
    if value == "random":
        return PolicyType.RANDOM
    if value == "search":
        return PolicyType.SEARCH
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
    search_depth: int = DEFAULT_SEARCH_DEPTH,
    search_max_depth: int = DEFAULT_SEARCH_MAX_DEPTH,
    search_beam_width: int = DEFAULT_SEARCH_BEAM_WIDTH,
    search_candidate_limit: int = DEFAULT_SEARCH_CANDIDATE_LIMIT,
) -> RecordEntry:
    config = GameConfig.for_autoplay(
        map_size=map_size,
        turn_limit=turn_limit,
        map_difficulty=map_difficulty,
        policy_type=policy_type,
        playback_mode=PlaybackMode.SPEED,
        seed=seed,
        search_depth=search_depth,
        search_max_depth=search_max_depth,
        search_beam_width=search_beam_width,
        search_candidate_limit=search_candidate_limit,
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
        search_depth=task.search_depth,
        search_max_depth=task.search_max_depth,
        search_beam_width=task.search_beam_width,
        search_candidate_limit=task.search_candidate_limit,
    )


def build_batch_tasks(
    *,
    games: int,
    seed_start: int,
    policy_type: PolicyType,
    map_size: int,
    turn_limit: int,
    map_difficulty: MapDifficulty,
    search_depth: int = DEFAULT_SEARCH_DEPTH,
    search_max_depth: int = DEFAULT_SEARCH_MAX_DEPTH,
    search_beam_width: int = DEFAULT_SEARCH_BEAM_WIDTH,
    search_candidate_limit: int = DEFAULT_SEARCH_CANDIDATE_LIMIT,
) -> list[BatchGameTask]:
    return [
        BatchGameTask(
            task_index=index,
            seed=seed_start + index,
            policy_type=policy_type,
            map_size=map_size,
            turn_limit=turn_limit,
            map_difficulty=map_difficulty,
            search_depth=search_depth,
            search_max_depth=search_max_depth,
            search_beam_width=search_beam_width,
            search_candidate_limit=search_candidate_limit,
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
    completed_batches: int | None = None,
    total_batches: int | None = None,
    running_batches: int | None = None,
    pending_batches: int | None = None,
    previous_completed: int | None = None,
    previous_elapsed: float | None = None,
    worker_cpu_seconds_total: float = 0.0,
    worker_elapsed_seconds_total: float = 0.0,
    workers: int = 1,
) -> None:
    elapsed = perf_counter() - started_at
    average = elapsed / completed if completed else 0.0
    remaining = average * max(total - completed, 0) if completed else 0.0
    eta_text = f"{remaining:.2f}s" if completed else "unknown"
    throughput = completed / max(elapsed, 0.000001)
    recent_rate = throughput
    if previous_completed is not None and previous_elapsed is not None:
        recent_completed = max(completed - previous_completed, 0)
        recent_elapsed = elapsed - previous_elapsed
        recent_rate = recent_completed / max(recent_elapsed, 0.000001)
    batch_text = ""
    if completed_batches is not None and total_batches is not None:
        batch_text = f", batches={completed_batches}/{total_batches}"
    worker_text = ""
    if running_batches is not None and pending_batches is not None:
        worker_text = f", running_batches={running_batches}, pending_batches={pending_batches}"
    parallel_efficiency_pct = (
        worker_cpu_seconds_total / max(elapsed * max(workers, 1), 0.000001) * 100
    )
    print(
        f"[{mode}] {completed}/{total} games complete{batch_text}{worker_text} "
        f"in {elapsed:.2f}s (avg {average:.3f}s/game, "
        f"throughput {throughput:.2f} games/s, recent {recent_rate:.2f} games/s, "
        f"eta {eta_text}, worker_cpu {worker_cpu_seconds_total:.2f}s, "
        f"worker_elapsed {worker_elapsed_seconds_total:.2f}s, "
        f"parallel_eff {parallel_efficiency_pct:.1f}%)",
        file=sys.stderr,
    )


def _should_print_progress(
    *,
    completed: int,
    previous_completed: int,
    total: int,
    now: float,
    last_printed_at: float,
    progress_interval_seconds: float,
) -> bool:
    if completed == total:
        return True
    progress_interval = _progress_interval(total)
    if completed // progress_interval > previous_completed // progress_interval:
        return True
    return now - last_printed_at >= progress_interval_seconds


def _record_summary(*, task: BatchGameTask, record: RecordEntry) -> BatchRecordSummary:
    return BatchRecordSummary(
        task_index=task.task_index,
        record_id=record.record_id,
        seed=record.seed,
        final_score=record.final_score,
        city_count=record.city_count,
        building_count=record.building_count,
        network_count=len(record.networks),
    )


def _write_records_jsonl_part(path: Path, records: list[RecordEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        for record in records:
            f.write(dumps_json_bytes(record.to_dict()))
            f.write(b"\n")


def _write_records_csv_part(path: Path, records: list[RecordEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_FIELD_ORDER))
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())


def _should_write_artifact_parts(effective_artifact_mode: str) -> bool:
    return effective_artifact_mode in {"fast", "dual"}


def _prepare_artifact_output_dir(artifact_dir: Path) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _remove_artifact_output_files(artifact_dir)


def _remove_artifact_output_files(artifact_dir: Path) -> None:
    for table in ARTIFACT_TABLES:
        for suffix in ("parquet", "jsonl"):
            for path in artifact_dir.glob(f"{table}*.{suffix}"):
                path.unlink(missing_ok=True)
    (artifact_dir / ARTIFACT_MANIFEST_FILENAME).unlink(missing_ok=True)


def run_game_batch(batch: BatchGameTaskBatch) -> BatchWorkerResult:
    started_at = perf_counter()
    cpu_started_at = process_time()
    records: list[RecordEntry] = []
    summaries: list[BatchRecordSummary] = []
    for task in batch.tasks:
        record = run_single_game_task(task)
        records.append(record)
        summaries.append(_record_summary(task=task, record=record))

    record_part_path = ""
    csv_part_path = ""
    if batch.write_json_part:
        record_part = batch.part_dir / f"records_part_{batch.batch_index:06d}.jsonl"
        _write_records_jsonl_part(record_part, records)
        record_part_path = str(record_part)
    if batch.write_csv_part:
        csv_part = batch.part_dir / f"records_part_{batch.batch_index:06d}.csv"
        _write_records_csv_part(csv_part, records)
        csv_part_path = str(csv_part)

    artifact_file_format = ""
    artifact_table_paths: dict[str, list[str]] = {}
    artifact_row_counts: dict[str, int] = {}
    if _should_write_artifact_parts(batch.effective_artifact_mode):
        if batch.artifact_dir is None:
            raise ValueError("artifact_dir is required for artifact output.")
        artifact_result = write_record_artifacts(
            records,
            batch.artifact_dir,
            preferred_format=batch.artifact_format,
            part_name=f"part_{batch.batch_index:06d}",
            write_manifest=False,
        )
        artifact_file_format = artifact_result.file_format
        artifact_table_paths = artifact_result.table_paths
        artifact_row_counts = artifact_result.row_counts

    return BatchWorkerResult(
        batch_index=batch.batch_index,
        completed=len(batch.tasks),
        summaries=summaries,
        record_part_path=record_part_path,
        csv_part_path=csv_part_path,
        artifact_file_format=artifact_file_format,
        artifact_table_paths=artifact_table_paths,
        artifact_row_counts=artifact_row_counts,
        worker_elapsed_seconds=perf_counter() - started_at,
        worker_cpu_seconds=process_time() - cpu_started_at,
    )


def _collect_batch_results(
    batch_results: list[BatchWorkerResult],
    *,
    run_elapsed_seconds: float,
) -> BatchRunResult:
    ordered_batch_results = sorted(batch_results, key=lambda result: result.batch_index)
    summaries = [
        summary
        for result in ordered_batch_results
        for summary in sorted(result.summaries, key=lambda item: item.task_index)
    ]
    summaries.sort(key=lambda summary: summary.task_index)
    return BatchRunResult(
        batch_results=ordered_batch_results,
        summaries=summaries,
        run_elapsed_seconds=run_elapsed_seconds,
    )


def _batch_failure_message(batch: BatchGameTaskBatch, exc: BaseException) -> str:
    task_indexes = [task.task_index for task in batch.tasks]
    task_range = f"{min(task_indexes)}-{max(task_indexes)}" if task_indexes else "empty"
    return (
        f"Batch autoplay worker batch {batch.batch_index} failed "
        f"(tasks={task_range}, size={len(batch.tasks)}): {exc}"
    )


def run_batch_tasks_serial(
    batches: list[BatchGameTaskBatch],
    *,
    total_tasks: int,
    progress_interval_seconds: float,
) -> BatchRunResult:
    batch_results: list[BatchWorkerResult] = []
    started_at = perf_counter()
    last_printed_at = started_at
    last_printed_completed = 0
    last_printed_elapsed = 0.0
    completed = 0
    for batch in batches:
        previous_completed = completed
        try:
            result = run_game_batch(batch)
        except Exception as exc:
            raise RuntimeError(_batch_failure_message(batch, exc)) from exc
        batch_results.append(result)
        completed += result.completed
        now = perf_counter()
        if _should_print_progress(
            completed=completed,
            previous_completed=previous_completed,
            total=total_tasks,
            now=now,
            last_printed_at=last_printed_at,
            progress_interval_seconds=progress_interval_seconds,
        ):
            _print_progress(
                completed=completed,
                total=total_tasks,
                started_at=started_at,
                mode="serial",
                completed_batches=len(batch_results),
                total_batches=len(batches),
                previous_completed=last_printed_completed,
                previous_elapsed=last_printed_elapsed,
                worker_cpu_seconds_total=sum(item.worker_cpu_seconds for item in batch_results),
                worker_elapsed_seconds_total=sum(
                    item.worker_elapsed_seconds for item in batch_results
                ),
            )
            last_printed_at = now
            last_printed_completed = completed
            last_printed_elapsed = now - started_at
    return _collect_batch_results(
        batch_results,
        run_elapsed_seconds=perf_counter() - started_at,
    )


def run_batch_tasks_parallel(
    batches: list[BatchGameTaskBatch],
    *,
    total_tasks: int,
    workers: int,
    progress_interval_seconds: float,
) -> BatchRunResult:
    batch_results: list[BatchWorkerResult] = []
    started_at = perf_counter()
    last_printed_at = started_at
    last_printed_completed = 0
    last_printed_elapsed = 0.0
    completed = 0
    executor = ProcessPoolExecutor(max_workers=workers)
    executor_stopped = False
    future_to_batch: dict[Future[BatchWorkerResult], BatchGameTaskBatch] = {}
    try:
        future_to_batch = {executor.submit(run_game_batch, batch): batch for batch in batches}
        pending: set[Future[BatchWorkerResult]] = set(future_to_batch)
        while pending:
            done, pending = wait(
                pending,
                timeout=progress_interval_seconds,
                return_when=FIRST_COMPLETED,
            )
            previous_completed = completed
            for future in done:
                batch = future_to_batch[future]
                try:
                    result = future.result()
                except Exception as exc:
                    shutdown_process_pool_now(executor, pending)
                    executor_stopped = True
                    raise RuntimeError(_batch_failure_message(batch, exc)) from exc
                batch_results.append(result)
                completed += result.completed
            now = perf_counter()
            if _should_print_progress(
                completed=completed,
                previous_completed=previous_completed,
                total=total_tasks,
                now=now,
                last_printed_at=last_printed_at,
                progress_interval_seconds=progress_interval_seconds,
            ):
                running_batches = sum(1 for pending_future in pending if pending_future.running())
                _print_progress(
                    completed=completed,
                    total=total_tasks,
                    started_at=started_at,
                    mode="parallel",
                    completed_batches=len(batch_results),
                    total_batches=len(batches),
                    running_batches=running_batches,
                    pending_batches=len(pending) - running_batches,
                    previous_completed=last_printed_completed,
                    previous_elapsed=last_printed_elapsed,
                    worker_cpu_seconds_total=sum(item.worker_cpu_seconds for item in batch_results),
                    worker_elapsed_seconds_total=sum(
                        item.worker_elapsed_seconds for item in batch_results
                    ),
                    workers=workers,
                )
                last_printed_at = now
                last_printed_completed = completed
                last_printed_elapsed = now - started_at
    except KeyboardInterrupt:
        shutdown_process_pool_now(executor, future_to_batch)
        executor_stopped = True
        raise
    finally:
        if not executor_stopped:
            shutdown_process_pool_gracefully(executor)
    return _collect_batch_results(
        batch_results,
        run_elapsed_seconds=perf_counter() - started_at,
    )


def _write_database_json(path: Path, database: RecordDatabase) -> None:
    write_bytes_atomic(path, dumps_json_bytes(database.to_dict(), indent=True) + b"\n")


def _write_database_csv(path: Path, records: list[RecordEntry]) -> None:
    with atomic_output_path(path) as temporary_path:
        with temporary_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(CSV_FIELD_ORDER))
            writer.writeheader()
            for record in records:
                writer.writerow(record.to_csv_row())


def _effective_chunksize(
    requested_chunksize: int | str,
    *,
    total_tasks: int,
    workers: int,
) -> int:
    if isinstance(requested_chunksize, int):
        return requested_chunksize
    target_batches = max(1, workers * AUTO_CHUNKSIZE_TARGET_BATCHES_PER_WORKER)
    auto_size = max(1, (total_tasks + target_batches - 1) // target_batches)
    return min(AUTO_CHUNKSIZE_MAX, auto_size)


def build_task_batches(
    tasks: list[BatchGameTask],
    *,
    effective_chunksize: int,
    part_dir: Path,
    artifact_dir: Path | None,
    artifact_format: str,
    effective_artifact_mode: str,
    write_json_part: bool,
    write_csv_part: bool,
) -> list[BatchGameTaskBatch]:
    return [
        BatchGameTaskBatch(
            batch_index=batch_index,
            tasks=tuple(tasks[start : start + effective_chunksize]),
            part_dir=part_dir,
            artifact_dir=artifact_dir,
            artifact_format=artifact_format,
            effective_artifact_mode=effective_artifact_mode,
            write_json_part=write_json_part,
            write_csv_part=write_csv_part,
        )
        for batch_index, start in enumerate(range(0, len(tasks), effective_chunksize))
    ]


def _record_jsonl_part_paths(batch_results: list[BatchWorkerResult]) -> list[Path]:
    return [
        Path(result.record_part_path)
        for result in sorted(batch_results, key=lambda item: item.batch_index)
        if result.record_part_path
    ]


def _record_csv_part_paths(batch_results: list[BatchWorkerResult]) -> list[Path]:
    return [
        Path(result.csv_part_path)
        for result in sorted(batch_results, key=lambda item: item.batch_index)
        if result.csv_part_path
    ]


def _write_database_json_from_jsonl_parts(path: Path, part_paths: list[Path]) -> int:
    written = 0
    first = True
    with atomic_output_path(path) as temporary_path:
        with temporary_path.open("wb") as output:
            output.write(
                f'{{"schema_version":{RECORDS_SCHEMA_VERSION},"next_record_id":1,"records":['.encode(
                    "ascii"
                )
            )
            for part_path in part_paths:
                with part_path.open("rb") as part_file:
                    for line in part_file:
                        line = line.strip()
                        if not line:
                            continue
                        if not first:
                            output.write(b",")
                        output.write(line)
                        first = False
                        written += 1
            output.write(b"]}\n")
    return written


def _write_database_csv_from_csv_parts(path: Path, part_paths: list[Path]) -> int:
    written = 0
    with atomic_output_path(path) as temporary_path:
        with temporary_path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=list(CSV_FIELD_ORDER))
            writer.writeheader()
            for part_path in part_paths:
                with part_path.open(newline="", encoding="utf-8") as part_file:
                    reader = csv.DictReader(part_file)
                    for row in reader:
                        writer.writerow(row)
                        written += 1
    return written


def _write_partitioned_artifact_manifest(
    *,
    artifact_dir: Path,
    batch_results: list[BatchWorkerResult],
    record_count: int,
    total_games: int,
    part_count: int,
) -> str:
    table_paths: dict[str, list[str]] = {table: [] for table in ARTIFACT_TABLES}
    row_counts: dict[str, int] = {table: 0 for table in ARTIFACT_TABLES}
    artifact_file_format = ""
    for result in sorted(batch_results, key=lambda item: item.batch_index):
        if result.artifact_file_format:
            artifact_file_format = artifact_file_format or result.artifact_file_format
        for table in ARTIFACT_TABLES:
            table_paths[table].extend(result.artifact_table_paths.get(table, []))
            row_counts[table] += result.artifact_row_counts.get(table, 0)
    artifact_result = ArtifactWriteResult(
        output_dir=artifact_dir,
        file_format=artifact_file_format,
        table_paths=table_paths,
        row_counts=row_counts,
    )
    write_artifact_manifest(
        artifact_dir,
        result=artifact_result,
        record_count=record_count,
        mode="partitioned",
        extra={
            "total_games": total_games,
            "part_count": part_count,
        },
    )
    return artifact_file_format


def _effective_artifact_mode(raw_mode: str, *, total_games: int, threshold: int) -> str:
    if raw_mode != "auto":
        return raw_mode
    return "compat" if total_games <= threshold else "fast"


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
        search_depth=args.search_depth,
        search_max_depth=args.search_max_depth,
        search_beam_width=args.search_beam_width,
        search_candidate_limit=args.search_candidate_limit,
    )
    execution_mode = "serial" if args.workers == 1 else "parallel"
    effective_artifact_mode = _effective_artifact_mode(
        args.artifact_mode,
        total_games=args.games,
        threshold=args.full_json_threshold,
    )
    effective_chunksize = _effective_chunksize(
        args.chunksize,
        total_tasks=args.games,
        workers=args.workers,
    )
    run_tag = args.label.strip().replace(" ", "_")
    policy_name = args.policy
    if policy_type is PolicyType.SEARCH:
        policy_name = (
            f"{policy_name}_d{args.search_depth}-{args.search_max_depth}_"
            f"b{args.search_beam_width}_c{args.search_candidate_limit}"
        )
    base_name = (
        f"{policy_name}_{args.map_size}_{args.turn_limit}_{args.map_difficulty}_"
        f"{args.seed_start}_{args.seed_start + args.games - 1}"
    )
    if run_tag:
        base_name = f"{base_name}_{run_tag}"

    artifact_dir: Path | None = (
        output_dir / f"{base_name}_artifacts"
        if effective_artifact_mode in {"fast", "dual"}
        else None
    )
    if artifact_dir is not None:
        _prepare_artifact_output_dir(artifact_dir)
    write_json_part = effective_artifact_mode in {"compat", "dual"} and not args.no_export_json
    write_csv_part = effective_artifact_mode in {"compat", "dual"} and not args.no_export_csv
    part_dir = output_dir / f".{base_name}_parts_{os.getpid()}_{int(perf_counter() * 1000000)}"
    batches = build_task_batches(
        tasks,
        effective_chunksize=effective_chunksize,
        part_dir=part_dir,
        artifact_dir=artifact_dir,
        artifact_format=args.artifact_format,
        effective_artifact_mode=effective_artifact_mode,
        write_json_part=write_json_part,
        write_csv_part=write_csv_part,
    )

    total_start = perf_counter()
    print(
        f"Batch plan: {args.games} games, mode={execution_mode}, "
        f"workers={args.workers}, chunksize={args.chunksize}, "
        f"effective_chunksize={effective_chunksize}, batches={len(batches)}, "
        f"progress_interval={args.progress_interval_seconds:g}s",
        file=sys.stderr,
    )
    print(
        f"Output mode: requested={args.artifact_mode}, effective={effective_artifact_mode}",
        file=sys.stderr,
    )
    try:
        run_result = (
            run_batch_tasks_serial(
                batches,
                total_tasks=args.games,
                progress_interval_seconds=args.progress_interval_seconds,
            )
            if args.workers == 1
            else run_batch_tasks_parallel(
                batches,
                total_tasks=args.games,
                workers=args.workers,
                progress_interval_seconds=args.progress_interval_seconds,
            )
        )
        print(
            f"Batch compute complete: {args.games} games in "
            f"{run_result.run_elapsed_seconds:.2f}s "
            f"({run_result.run_elapsed_seconds / args.games:.3f}s per game)",
            file=sys.stderr,
        )

        merge_started_at = perf_counter()
        summaries = run_result.summaries
        json_path: Path | None = None
        csv_path: Path | None = None
        artifact_file_format = ""

        if write_json_part:
            json_path = output_dir / f"{base_name}.json"
            _write_database_json_from_jsonl_parts(
                json_path,
                _record_jsonl_part_paths(run_result.batch_results),
            )
            print(f"JSON exported: {json_path}", file=sys.stderr)

        if write_csv_part:
            csv_path = output_dir / f"{base_name}.csv"
            _write_database_csv_from_csv_parts(
                csv_path,
                _record_csv_part_paths(run_result.batch_results),
            )
            print(f"CSV exported: {csv_path}", file=sys.stderr)

        if effective_artifact_mode in {"fast", "dual"}:
            if artifact_dir is None:
                raise ValueError("artifact_dir is required for artifact output.")
            artifact_file_format = _write_partitioned_artifact_manifest(
                artifact_dir=artifact_dir,
                batch_results=run_result.batch_results,
                record_count=len(summaries),
                total_games=args.games,
                part_count=len(batches),
            )
            print(f"Artifacts exported: {artifact_dir} ({artifact_file_format})", file=sys.stderr)

        merge_elapsed = perf_counter() - merge_started_at
        total_elapsed = perf_counter() - total_start
        worker_cpu_seconds_total = sum(
            result.worker_cpu_seconds for result in run_result.batch_results
        )
        worker_elapsed_seconds_total = sum(
            result.worker_elapsed_seconds for result in run_result.batch_results
        )
        parallel_efficiency_pct = (
            worker_cpu_seconds_total
            / max(run_result.run_elapsed_seconds * args.workers, 0.000001)
            * 100
        )

        print(
            f"Batch complete: {args.games} games in {total_elapsed:.2f}s "
            f"({total_elapsed / args.games:.3f}s per game)",
            file=sys.stderr,
        )

        if not args.no_write_summary:
            summary_path = output_dir / f"{base_name}_summary.json"
            summary = {
                "games": args.games,
                "policy": args.policy,
                "search_depth": args.search_depth,
                "search_max_depth": args.search_max_depth,
                "search_beam_width": args.search_beam_width,
                "search_candidate_limit": args.search_candidate_limit,
                "map_size": args.map_size,
                "turn_limit": args.turn_limit,
                "map_difficulty": args.map_difficulty,
                "seed_start": args.seed_start,
                "seed_end": args.seed_start + args.games - 1,
                "workers": args.workers,
                "chunksize": args.chunksize,
                "effective_chunksize": effective_chunksize,
                "batch_count": len(batches),
                "progress_interval_seconds": args.progress_interval_seconds,
                "execution_mode": execution_mode,
                "artifact_mode": args.artifact_mode,
                "effective_artifact_mode": effective_artifact_mode,
                "artifact_format": args.artifact_format,
                "artifact_file_format": artifact_file_format,
                "artifact_dir": str(artifact_dir) if artifact_dir is not None else "",
                "full_json_threshold": args.full_json_threshold,
                "json_path": str(json_path) if json_path is not None else "",
                "csv_path": str(csv_path) if csv_path is not None else "",
                "run_elapsed_seconds": round(run_result.run_elapsed_seconds, 3),
                "merge_elapsed_seconds": round(merge_elapsed, 3),
                "total_elapsed_seconds": round(total_elapsed, 3),
                "avg_elapsed_seconds": round(total_elapsed / args.games, 3),
                "worker_cpu_seconds_total": round(worker_cpu_seconds_total, 3),
                "worker_elapsed_seconds_total": round(worker_elapsed_seconds_total, 3),
                "parallel_efficiency_pct": round(parallel_efficiency_pct, 2),
                "avg_score": round(
                    sum(summary.final_score for summary in summaries) / len(summaries), 2
                ),
                "max_score": max(summary.final_score for summary in summaries),
                "min_score": min(summary.final_score for summary in summaries),
                "avg_city_count": round(
                    sum(summary.city_count for summary in summaries) / len(summaries), 2
                ),
                "avg_building_count": round(
                    sum(summary.building_count for summary in summaries) / len(summaries), 2
                ),
                "avg_network_count": round(
                    sum(summary.network_count for summary in summaries) / len(summaries), 2
                ),
            }
            write_bytes_atomic(summary_path, dumps_json_bytes(summary, indent=True) + b"\n")
            print(f"Summary exported: {summary_path}", file=sys.stderr)
    except KeyboardInterrupt:
        print(
            "Interrupted by user; stopping workers and cleaning partial outputs.",
            file=sys.stderr,
        )
        if artifact_dir is not None:
            _remove_artifact_output_files(artifact_dir)
        return 130
    finally:
        shutil.rmtree(part_dir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
