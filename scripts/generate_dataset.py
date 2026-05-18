"""Generate a large labeled dataset for AI rule analysis."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import product
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
    loads_json_bytes,
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

GREEDY_LABEL: Final[str] = "Greedy"
RANDOM_LABEL: Final[str] = "Random"
SEARCH_LABEL: Final[str] = "Search"
PROGRESS_STEPS: Final[int] = 20
DEFAULT_FULL_JSON_THRESHOLD: Final[int] = 1000
AUTO_CHUNKSIZE: Final[str] = "auto"
AUTO_CHUNKSIZE_TARGET_BATCHES_PER_WORKER: Final[int] = 8
AUTO_CHUNKSIZE_MAX: Final[int] = 64


@dataclass(frozen=True, slots=True)
class GameTask:
    task_index: int
    record_id: int
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
class GameTaskBatch:
    batch_index: int
    tasks: tuple[GameTask, ...]
    output_dir: Path
    part_dir: Path
    artifact_dir: Path | None
    artifact_format: str
    effective_artifact_mode: str


@dataclass(frozen=True, slots=True)
class RecordSummary:
    task_index: int
    record_id: int
    seed: int
    map_size: int
    turn_limit: int
    map_difficulty: str
    ai_type: str
    final_score: int
    has_starvation: bool


@dataclass(frozen=True, slots=True)
class WorkerBatchResult:
    batch_index: int
    completed: int
    summaries: list[RecordSummary]
    record_part_path: str = ""
    csv_part_path: str = ""
    artifact_file_format: str = ""
    artifact_table_paths: dict[str, list[str]] = field(default_factory=dict)
    artifact_row_counts: dict[str, int] = field(default_factory=dict)
    worker_elapsed_seconds: float = 0.0
    worker_cpu_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class DatasetRunResult:
    batch_results: list[WorkerBatchResult]
    summaries: list[RecordSummary]
    run_elapsed_seconds: float


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _chunksize_arg(value: str) -> int | str:
    if value == AUTO_CHUNKSIZE:
        return AUTO_CHUNKSIZE
    return _positive_int(value)


def _default_worker_count() -> int:
    cpu_count = os.cpu_count() or 1
    return max(1, cpu_count - 1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate large MicroCiv dataset.")
    parser.add_argument(
        "-n", "--games-per-combo", type=int, default=10, help="Games per parameter combo."
    )
    parser.add_argument("--seed-start", type=int, default=1, help="Global starting seed offset.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "exports" / "dataset",
        help="Output directory.",
    )
    parser.add_argument(
        "--policies",
        type=str,
        default="greedy,random,search",
        help="Comma-separated policies.",
    )
    parser.add_argument(
        "--search-depths",
        type=str,
        default=str(DEFAULT_SEARCH_DEPTH),
        help=f"Comma-separated Search depths (default: {DEFAULT_SEARCH_DEPTH}).",
    )
    parser.add_argument(
        "--search-max-depths",
        type=str,
        default=str(DEFAULT_SEARCH_MAX_DEPTH),
        help=f"Comma-separated Search max depths (default: {DEFAULT_SEARCH_MAX_DEPTH}).",
    )
    parser.add_argument(
        "--search-beam-widths",
        type=str,
        default=str(DEFAULT_SEARCH_BEAM_WIDTH),
        help=f"Comma-separated Search beam widths (default: {DEFAULT_SEARCH_BEAM_WIDTH}).",
    )
    parser.add_argument(
        "--search-candidate-limits",
        type=str,
        default=str(DEFAULT_SEARCH_CANDIDATE_LIMIT),
        help=(
            f"Comma-separated Search candidate limits (default: {DEFAULT_SEARCH_CANDIDATE_LIMIT})."
        ),
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
        type=_chunksize_arg,
        default=AUTO_CHUNKSIZE,
        help="Task batch size for worker dispatch, or 'auto' (default: auto).",
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
            "Maximum task count for auto mode to keep full legacy JSON "
            f"(default: {DEFAULT_FULL_JSON_THRESHOLD})."
        ),
    )
    return parser.parse_args()


def _policy_type(value: str) -> PolicyType:
    if value == "greedy":
        return PolicyType.GREEDY
    if value == "random":
        return PolicyType.RANDOM
    if value == "search":
        return PolicyType.SEARCH
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


def _parse_csv_int_values(raw: str, *, field_name: str) -> list[int]:
    values = [int(item) for item in _parse_csv_values(raw, field_name=field_name)]
    for value in values:
        if value < 1:
            raise ValueError(f"{field_name} values must be at least 1.")
    return values


def run_game(
    *,
    record_id: int,
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
        search_depth=task.search_depth,
        search_max_depth=task.search_max_depth,
        search_beam_width=task.search_beam_width,
        search_candidate_limit=task.search_candidate_limit,
    )


def _record_match_key(record: RecordEntry) -> tuple[int, int, int, str]:
    return (record.seed, record.map_size, record.turn_limit, record.map_difficulty)


def _build_random_index(
    records: list[RecordEntry],
) -> dict[tuple[int, int, int, str], RecordEntry]:
    return {
        _record_match_key(record): record for record in records if record.ai_type == RANDOM_LABEL
    }


def _build_greedy_index(
    records: list[RecordEntry],
) -> dict[tuple[int, int, int, str], RecordEntry]:
    return {
        _record_match_key(record): record for record in records if record.ai_type == GREEDY_LABEL
    }


def _has_starvation(record: RecordEntry) -> bool:
    return any(snapshot.starving_network_count > 0 for snapshot in record.turn_snapshots) or any(
        network.food <= 0 for network in record.networks
    )


def _record_summary(*, task: GameTask, record: RecordEntry) -> RecordSummary:
    return RecordSummary(
        task_index=task.task_index,
        record_id=record.record_id,
        seed=record.seed,
        map_size=record.map_size,
        turn_limit=record.turn_limit,
        map_difficulty=record.map_difficulty,
        ai_type=record.ai_type,
        final_score=record.final_score,
        has_starvation=_has_starvation(record),
    )


def _summary_match_key(summary: RecordSummary) -> tuple[int, int, int, str]:
    return (summary.seed, summary.map_size, summary.turn_limit, summary.map_difficulty)


def collect_policy_anomaly_ids(
    summaries: list[RecordSummary],
) -> tuple[set[int], dict[str, int]]:
    random_index = {
        _summary_match_key(summary): summary
        for summary in summaries
        if summary.ai_type == RANDOM_LABEL
    }
    greedy_index = {
        _summary_match_key(summary): summary
        for summary in summaries
        if summary.ai_type == GREEDY_LABEL
    }
    anomaly_ids: set[int] = set()
    negative_score_count = 0
    starvation_count = 0
    common_anomaly_count = 0
    greedy_under_random_count = 0
    search_under_random_count = 0
    search_under_greedy_count = 0

    for summary in summaries:
        match_key = _summary_match_key(summary)
        random_peer = random_index.get(match_key)
        greedy_peer = greedy_index.get(match_key)
        is_negative_score = summary.final_score < 0
        is_common_anomaly = is_negative_score or summary.has_starvation
        is_greedy_under_random = (
            summary.ai_type == GREEDY_LABEL
            and random_peer is not None
            and summary.final_score < random_peer.final_score
        )
        is_search_under_random = (
            summary.ai_type == SEARCH_LABEL
            and random_peer is not None
            and summary.final_score < random_peer.final_score
        )
        is_search_under_greedy = (
            summary.ai_type == SEARCH_LABEL
            and greedy_peer is not None
            and summary.final_score < greedy_peer.final_score
        )
        if not (
            is_common_anomaly
            or is_greedy_under_random
            or is_search_under_random
            or is_search_under_greedy
        ):
            continue
        if is_negative_score:
            negative_score_count += 1
        if summary.has_starvation:
            starvation_count += 1
        if is_common_anomaly:
            common_anomaly_count += 1
        if is_greedy_under_random:
            greedy_under_random_count += 1
        if is_search_under_random:
            search_under_random_count += 1
        if is_search_under_greedy:
            search_under_greedy_count += 1
        anomaly_ids.add(summary.record_id)

    return anomaly_ids, {
        "common_anomaly_count": common_anomaly_count,
        "negative_score_anomaly_count": negative_score_count,
        "starvation_anomaly_count": starvation_count,
        "greedy_under_random_anomaly_count": greedy_under_random_count,
        "search_under_random_anomaly_count": search_under_random_count,
        "search_under_greedy_anomaly_count": search_under_greedy_count,
        "under_random_anomaly_count": greedy_under_random_count + search_under_random_count,
    }


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


def _should_write_compat_parts(effective_artifact_mode: str) -> bool:
    return effective_artifact_mode in {"compat", "dual"}


def _should_write_artifact_parts(effective_artifact_mode: str) -> bool:
    return effective_artifact_mode in {"fast", "dual"}


def _prepare_artifact_output_dir(artifact_dir: Path) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for table in ARTIFACT_TABLES:
        for suffix in ("parquet", "jsonl"):
            for path in artifact_dir.glob(f"{table}*.{suffix}"):
                path.unlink()
    (artifact_dir / ARTIFACT_MANIFEST_FILENAME).unlink(missing_ok=True)


def run_game_batch(batch: GameTaskBatch) -> WorkerBatchResult:
    started_at = perf_counter()
    cpu_started_at = process_time()
    records: list[RecordEntry] = []
    summaries: list[RecordSummary] = []
    for task in batch.tasks:
        record = run_game_task(task)
        records.append(record)
        summaries.append(_record_summary(task=task, record=record))

    record_part_path = ""
    csv_part_path = ""
    if _should_write_compat_parts(batch.effective_artifact_mode):
        record_part = batch.part_dir / f"records_part_{batch.batch_index:06d}.jsonl"
        csv_part = batch.part_dir / f"records_part_{batch.batch_index:06d}.csv"
        _write_records_jsonl_part(record_part, records)
        _write_records_csv_part(csv_part, records)
        record_part_path = str(record_part)
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

    return WorkerBatchResult(
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


def collect_policy_anomalies(
    records: list[RecordEntry],
) -> tuple[list[RecordEntry], dict[str, int]]:
    random_index = _build_random_index(records)
    greedy_index = _build_greedy_index(records)
    anomalies: list[RecordEntry] = []
    negative_score_count = 0
    starvation_count = 0
    common_anomaly_count = 0
    greedy_under_random_count = 0
    search_under_random_count = 0
    search_under_greedy_count = 0
    for record in records:
        match_key = _record_match_key(record)
        random_peer = random_index.get(match_key)
        greedy_peer = greedy_index.get(match_key)
        is_negative_score = record.final_score < 0
        has_starvation = _has_starvation(record)
        is_common_anomaly = is_negative_score or has_starvation
        is_greedy_under_random = (
            record.ai_type == GREEDY_LABEL
            and random_peer is not None
            and record.final_score < random_peer.final_score
        )
        is_search_under_random = (
            record.ai_type == SEARCH_LABEL
            and random_peer is not None
            and record.final_score < random_peer.final_score
        )
        is_search_under_greedy = (
            record.ai_type == SEARCH_LABEL
            and greedy_peer is not None
            and record.final_score < greedy_peer.final_score
        )
        if not (
            is_common_anomaly
            or is_greedy_under_random
            or is_search_under_random
            or is_search_under_greedy
        ):
            continue
        if is_negative_score:
            negative_score_count += 1
        if has_starvation:
            starvation_count += 1
        if is_common_anomaly:
            common_anomaly_count += 1
        if is_greedy_under_random:
            greedy_under_random_count += 1
        if is_search_under_random:
            search_under_random_count += 1
        if is_search_under_greedy:
            search_under_greedy_count += 1
        anomalies.append(record)
    return anomalies, {
        "common_anomaly_count": common_anomaly_count,
        "negative_score_anomaly_count": negative_score_count,
        "starvation_anomaly_count": starvation_count,
        "greedy_under_random_anomaly_count": greedy_under_random_count,
        "search_under_random_anomaly_count": search_under_random_count,
        "search_under_greedy_anomaly_count": search_under_greedy_count,
        "under_random_anomaly_count": greedy_under_random_count + search_under_random_count,
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
        is_under_random = random_peer is not None and record.final_score < random_peer.final_score
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
    path.write_bytes(dumps_json_bytes(database.to_dict(), indent=True) + b"\n")


def _write_database_csv(path: Path, records: list[RecordEntry]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_FIELD_ORDER))
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())


def _effective_artifact_mode(raw_mode: str, *, total_games: int, threshold: int) -> str:
    if raw_mode != "auto":
        return raw_mode
    return "compat" if total_games <= threshold else "fast"


def build_game_tasks(
    *,
    seed_start: int,
    games_per_combo: int,
    policies: list[PolicyType],
    base_combos: list[tuple[int, int, str]],
    search_depths: list[int] | None = None,
    search_max_depths: list[int] | None = None,
    search_beam_widths: list[int] | None = None,
    search_candidate_limits: list[int] | None = None,
) -> tuple[list[GameTask], int]:
    tasks: list[GameTask] = []
    next_record_id = 1
    seed = seed_start
    search_depth_values = search_depths or [DEFAULT_SEARCH_DEPTH]
    search_max_depth_values = search_max_depths or [DEFAULT_SEARCH_MAX_DEPTH]
    search_beam_width_values = search_beam_widths or [DEFAULT_SEARCH_BEAM_WIDTH]
    search_candidate_limit_values = search_candidate_limits or [DEFAULT_SEARCH_CANDIDATE_LIMIT]
    for map_size, turn_limit, difficulty in base_combos:
        map_difficulty = _map_difficulty(difficulty)
        for _ in range(games_per_combo):
            for policy_type in policies:
                if policy_type is PolicyType.SEARCH:
                    for (
                        search_depth,
                        search_max_depth,
                        search_beam_width,
                        search_candidate_limit,
                    ) in product(
                        search_depth_values,
                        search_max_depth_values,
                        search_beam_width_values,
                        search_candidate_limit_values,
                    ):
                        if search_max_depth < search_depth:
                            continue
                        tasks.append(
                            GameTask(
                                task_index=len(tasks),
                                record_id=next_record_id,
                                seed=seed,
                                policy_type=policy_type,
                                map_size=map_size,
                                turn_limit=turn_limit,
                                map_difficulty=map_difficulty,
                                search_depth=search_depth,
                                search_max_depth=search_max_depth,
                                search_beam_width=search_beam_width,
                                search_candidate_limit=search_candidate_limit,
                            )
                        )
                        next_record_id += 1
                    continue
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
    tasks: list[GameTask],
    *,
    effective_chunksize: int,
    output_dir: Path,
    part_dir: Path,
    artifact_dir: Path | None,
    artifact_format: str,
    effective_artifact_mode: str,
) -> list[GameTaskBatch]:
    return [
        GameTaskBatch(
            batch_index=batch_index,
            tasks=tuple(tasks[start : start + effective_chunksize]),
            output_dir=output_dir,
            part_dir=part_dir,
            artifact_dir=artifact_dir,
            artifact_format=artifact_format,
            effective_artifact_mode=effective_artifact_mode,
        )
        for batch_index, start in enumerate(range(0, len(tasks), effective_chunksize))
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
    elapsed = perf_counter() - started_at
    average = elapsed / max(completed, 1)
    remaining = average * max(total - completed, 0)
    print(
        f"[{mode}] {completed}/{total} games complete in {elapsed:.2f}s "
        f"({average:.3f}s per game, eta {remaining:.2f}s)",
        file=sys.stderr,
    )


def _should_print_progress(completed: int, previous_completed: int, total: int) -> bool:
    if completed == total:
        return True
    progress_interval = _progress_interval(total)
    return completed // progress_interval > previous_completed // progress_interval


def _collect_batch_results(
    batch_results: list[WorkerBatchResult],
    *,
    run_elapsed_seconds: float,
) -> DatasetRunResult:
    ordered_batch_results = sorted(batch_results, key=lambda result: result.batch_index)
    summaries = [
        summary
        for result in ordered_batch_results
        for summary in sorted(result.summaries, key=lambda item: item.task_index)
    ]
    summaries.sort(key=lambda summary: summary.task_index)
    return DatasetRunResult(
        batch_results=ordered_batch_results,
        summaries=summaries,
        run_elapsed_seconds=run_elapsed_seconds,
    )


def run_task_batches_serial(batches: list[GameTaskBatch], *, total_tasks: int) -> DatasetRunResult:
    batch_results: list[WorkerBatchResult] = []
    started_at = perf_counter()
    completed = 0
    for batch in batches:
        previous_completed = completed
        result = run_game_batch(batch)
        batch_results.append(result)
        completed += result.completed
        if _should_print_progress(completed, previous_completed, total_tasks):
            _print_progress(
                completed=completed,
                total=total_tasks,
                started_at=started_at,
                mode="serial",
            )
    return _collect_batch_results(
        batch_results,
        run_elapsed_seconds=perf_counter() - started_at,
    )


def run_task_batches_parallel(
    batches: list[GameTaskBatch],
    *,
    total_tasks: int,
    workers: int,
) -> DatasetRunResult:
    batch_results: list[WorkerBatchResult] = []
    started_at = perf_counter()
    completed = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_to_batch_index = {
            executor.submit(run_game_batch, batch): batch.batch_index for batch in batches
        }
        for future in as_completed(future_to_batch_index):
            previous_completed = completed
            result = future.result()
            batch_results.append(result)
            completed += result.completed
            if _should_print_progress(completed, previous_completed, total_tasks):
                _print_progress(
                    completed=completed,
                    total=total_tasks,
                    started_at=started_at,
                    mode="parallel",
                )
    return _collect_batch_results(
        batch_results,
        run_elapsed_seconds=perf_counter() - started_at,
    )


def _record_jsonl_part_paths(batch_results: list[WorkerBatchResult]) -> list[Path]:
    return [
        Path(result.record_part_path)
        for result in sorted(batch_results, key=lambda item: item.batch_index)
        if result.record_part_path
    ]


def _record_csv_part_paths(batch_results: list[WorkerBatchResult]) -> list[Path]:
    return [
        Path(result.csv_part_path)
        for result in sorted(batch_results, key=lambda item: item.batch_index)
        if result.csv_part_path
    ]


def _write_database_json_from_jsonl_parts(
    path: Path,
    part_paths: list[Path],
    *,
    record_ids: set[int] | None = None,
) -> int:
    written = 0
    first = True
    with path.open("wb") as output:
        output.write(
            f'{{"schema_version":{RECORDS_SCHEMA_VERSION},'
            f'"next_record_id":1,"records":['.encode("ascii")
        )
        for part_path in part_paths:
            with part_path.open("rb") as part_file:
                for line in part_file:
                    line = line.strip()
                    if not line:
                        continue
                    if record_ids is not None:
                        payload = loads_json_bytes(line)
                        if not isinstance(payload, dict):
                            raise ValueError("Record JSONL rows must be JSON objects.")
                        if int(payload["record_id"]) not in record_ids:
                            continue
                    if not first:
                        output.write(b",")
                    output.write(line)
                    first = False
                    written += 1
        output.write(b"]}\n")
    return written


def _write_database_csv_from_csv_parts(
    path: Path,
    part_paths: list[Path],
    *,
    record_ids: set[int] | None = None,
) -> int:
    written = 0
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(CSV_FIELD_ORDER))
        writer.writeheader()
        for part_path in part_paths:
            with part_path.open(newline="", encoding="utf-8") as part_file:
                reader = csv.DictReader(part_file)
                for row in reader:
                    if record_ids is not None and int(row["record_id"]) not in record_ids:
                        continue
                    writer.writerow(row)
                    written += 1
    return written


def _write_partitioned_artifact_manifest(
    *,
    artifact_dir: Path,
    batch_results: list[WorkerBatchResult],
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
    search_depths = _parse_csv_int_values(args.search_depths, field_name="search_depths")
    search_max_depths = _parse_csv_int_values(
        args.search_max_depths,
        field_name="search_max_depths",
    )
    search_beam_widths = _parse_csv_int_values(
        args.search_beam_widths,
        field_name="search_beam_widths",
    )
    search_candidate_limits = _parse_csv_int_values(
        args.search_candidate_limits,
        field_name="search_candidate_limits",
    )

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
    search_param_grid = {
        "search_depth": search_depths,
        "search_max_depth": search_max_depths,
        "search_beam_width": search_beam_widths,
        "search_candidate_limit": search_candidate_limits,
    }
    policies = [_policy_type(policy) for policy in param_grid["policy"]]
    search_variant_count = (
        sum(
            1
            for search_depth in search_depths
            for search_max_depth in search_max_depths
            if search_max_depth >= search_depth
        )
        * len(search_beam_widths)
        * len(search_candidate_limits)
        if PolicyType.SEARCH in policies
        else 0
    )
    policy_variant_count = sum(
        search_variant_count if policy is PolicyType.SEARCH else 1 for policy in policies
    )
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
        search_depths=search_depths,
        search_max_depths=search_max_depths,
        search_beam_widths=search_beam_widths,
        search_candidate_limits=search_candidate_limits,
    )
    total_games = len(tasks)
    run_tag = args.label.strip().replace(" ", "_")
    base_name = "dataset"
    if run_tag:
        base_name = f"{base_name}_{run_tag}"
    execution_mode = "serial" if args.workers == 1 else "parallel"
    effective_artifact_mode = _effective_artifact_mode(
        args.artifact_mode,
        total_games=total_games,
        threshold=args.full_json_threshold,
    )
    effective_chunksize = _effective_chunksize(
        args.chunksize,
        total_tasks=total_games,
        workers=args.workers,
    )
    artifact_dir: Path | None = (
        output_dir / f"{base_name}_artifacts"
        if effective_artifact_mode in {"fast", "dual"}
        else None
    )
    if artifact_dir is not None:
        _prepare_artifact_output_dir(artifact_dir)
    part_dir = output_dir / f".{base_name}_parts_{os.getpid()}_{int(perf_counter() * 1000000)}"
    batches = build_task_batches(
        tasks,
        effective_chunksize=effective_chunksize,
        output_dir=output_dir,
        part_dir=part_dir,
        artifact_dir=artifact_dir,
        artifact_format=args.artifact_format,
        effective_artifact_mode=effective_artifact_mode,
    )

    print(
        f"Dataset plan: {len(base_combos)} base combos x {policy_variant_count} policy variants x "
        f"{args.games_per_combo} games = "
        f"{total_games} total",
        file=sys.stderr,
    )
    print(
        f"Execution mode: {execution_mode} (workers={args.workers}, "
        f"chunksize={args.chunksize}, effective_chunksize={effective_chunksize}, "
        f"batches={len(batches)})",
        file=sys.stderr,
    )
    print(
        f"Output mode: requested={args.artifact_mode}, effective={effective_artifact_mode}",
        file=sys.stderr,
    )
    total_started_at = perf_counter()

    try:
        run_result = (
            run_task_batches_serial(batches, total_tasks=total_games)
            if args.workers == 1
            else run_task_batches_parallel(
                batches,
                total_tasks=total_games,
                workers=args.workers,
            )
        )

        print(
            f"Dataset compute complete: {total_games} games in "
            f"{run_result.run_elapsed_seconds:.2f}s "
            f"({run_result.run_elapsed_seconds / total_games:.3f}s per game)",
            file=sys.stderr,
        )

        merge_started_at = perf_counter()
        summaries = run_result.summaries
        anomaly_ids, anomaly_counts = collect_policy_anomaly_ids(summaries)

        json_path: Path | None = None
        csv_path: Path | None = None
        anomaly_json_path: Path | None = None
        anomaly_csv_path: Path | None = None
        artifact_file_format = ""
        if effective_artifact_mode in {"compat", "dual"}:
            record_part_paths = _record_jsonl_part_paths(run_result.batch_results)
            csv_part_paths = _record_csv_part_paths(run_result.batch_results)

            json_path = output_dir / f"{base_name}.json"
            _write_database_json_from_jsonl_parts(json_path, record_part_paths)
            print(f"Dataset JSON exported: {json_path}", file=sys.stderr)

            csv_path = output_dir / f"{base_name}.csv"
            _write_database_csv_from_csv_parts(csv_path, csv_part_paths)
            print(f"Dataset CSV exported: {csv_path}", file=sys.stderr)

            anomaly_json_path = output_dir / f"{base_name}_anomalies.json"
            _write_database_json_from_jsonl_parts(
                anomaly_json_path,
                record_part_paths,
                record_ids=anomaly_ids,
            )
            print(f"Anomaly dataset JSON exported: {anomaly_json_path}", file=sys.stderr)

            anomaly_csv_path = output_dir / f"{base_name}_anomalies.csv"
            _write_database_csv_from_csv_parts(
                anomaly_csv_path,
                csv_part_paths,
                record_ids=anomaly_ids,
            )
            print(f"Anomaly dataset CSV exported: {anomaly_csv_path}", file=sys.stderr)

        if effective_artifact_mode in {"fast", "dual"}:
            if artifact_dir is None:
                raise ValueError("artifact_dir is required for artifact output.")
            artifact_file_format = _write_partitioned_artifact_manifest(
                artifact_dir=artifact_dir,
                batch_results=run_result.batch_results,
                record_count=len(summaries),
                total_games=total_games,
                part_count=len(batches),
            )
            print(
                f"Dataset artifacts exported: {artifact_dir} ({artifact_file_format})",
                file=sys.stderr,
            )

        merge_elapsed = perf_counter() - merge_started_at
        total_elapsed = perf_counter() - total_started_at
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

        manifest_path = output_dir / f"{base_name}_manifest.json"
        manifest = {
            "games_per_combo": args.games_per_combo,
            "seed_start": args.seed_start,
            "seed_end": seed_end,
            "param_grid": param_grid,
            "search_param_grid": search_param_grid,
            "combo_count": len(base_combos) * policy_variant_count,
            "base_combo_count": len(base_combos),
            "policy_count": len(policies),
            "policy_variant_count": policy_variant_count,
            "search_variant_count": search_variant_count,
            "workers": args.workers,
            "chunksize": args.chunksize,
            "effective_chunksize": effective_chunksize,
            "batch_count": len(batches),
            "execution_mode": execution_mode,
            "artifact_mode": args.artifact_mode,
            "effective_artifact_mode": effective_artifact_mode,
            "artifact_format": args.artifact_format,
            "artifact_file_format": artifact_file_format,
            "artifact_dir": str(artifact_dir) if artifact_dir is not None else "",
            "full_json_threshold": args.full_json_threshold,
            "dataset_json_path": str(json_path) if json_path is not None else "",
            "dataset_csv_path": str(csv_path) if csv_path is not None else "",
            "total_games": total_games,
            "run_elapsed_seconds": round(run_result.run_elapsed_seconds, 3),
            "merge_elapsed_seconds": round(merge_elapsed, 3),
            "total_elapsed_seconds": round(total_elapsed, 3),
            "avg_elapsed_seconds": round(total_elapsed / total_games, 3),
            "worker_cpu_seconds_total": round(worker_cpu_seconds_total, 3),
            "worker_elapsed_seconds_total": round(worker_elapsed_seconds_total, 3),
            "parallel_efficiency_pct": round(parallel_efficiency_pct, 2),
            "anomaly_count": len(anomaly_ids),
            "anomaly_rate": round(len(anomaly_ids) / max(len(summaries), 1), 4),
            "common_anomaly_count": anomaly_counts["common_anomaly_count"],
            "negative_score_anomaly_count": anomaly_counts["negative_score_anomaly_count"],
            "starvation_anomaly_count": anomaly_counts["starvation_anomaly_count"],
            "greedy_under_random_anomaly_count": anomaly_counts[
                "greedy_under_random_anomaly_count"
            ],
            "search_under_random_anomaly_count": anomaly_counts[
                "search_under_random_anomaly_count"
            ],
            "search_under_greedy_anomaly_count": anomaly_counts[
                "search_under_greedy_anomaly_count"
            ],
            "under_random_anomaly_count": anomaly_counts["under_random_anomaly_count"],
            "anomaly_json_path": str(anomaly_json_path) if anomaly_json_path is not None else "",
            "anomaly_csv_path": str(anomaly_csv_path) if anomaly_csv_path is not None else "",
        }
        manifest_path.write_bytes(dumps_json_bytes(manifest, indent=True) + b"\n")
        print(f"Dataset manifest exported: {manifest_path}", file=sys.stderr)
        print(
            f"Dataset complete: {total_games} games in {total_elapsed:.2f}s "
            f"({total_elapsed / total_games:.3f}s per game)",
            file=sys.stderr,
        )
    finally:
        shutil.rmtree(part_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
