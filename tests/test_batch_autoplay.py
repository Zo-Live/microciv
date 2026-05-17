from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

from microciv.game.enums import PolicyType
from microciv.records.models import RecordDatabase, RecordEntry

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "batch_autoplay.py"
SPEC = importlib.util.spec_from_file_location("batch_autoplay", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
batch_autoplay = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = batch_autoplay
SPEC.loader.exec_module(batch_autoplay)


class _FakeProcessPoolExecutor:
    def __init__(self, *, max_workers: int) -> None:
        self.max_workers = max_workers
        self.map_calls: list[tuple[object, list[object], int]] = []

    def __enter__(self) -> _FakeProcessPoolExecutor:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb

    def map(
        self,
        fn: object,
        iterable: object,
        *,
        chunksize: int,
    ) -> list[object]:
        items = list(iterable)
        self.map_calls.append((fn, items, chunksize))
        assert callable(fn)
        return [fn(item) for item in items]


def _make_record(*, seed: int, policy_type: PolicyType, final_score: int) -> RecordEntry:
    if policy_type is PolicyType.GREEDY:
        ai_type = "Greedy"
    elif policy_type is PolicyType.RANDOM:
        ai_type = "Random"
    else:
        ai_type = "Search"
    return RecordEntry(
        record_id=seed,
        timestamp="2026-04-19T12:00:00+08:00",
        game_version="0.1.0-test",
        mode="autoplay",
        ai_type=ai_type,
        custom_goal="",
        playback_mode="speed",
        seed=seed,
        map_size=16,
        map_difficulty="normal",
        turn_limit=80,
        actual_turns=80,
        final_score=final_score,
        city_count=2,
        building_count=1,
        tech_count=1,
        food=0,
        wood=0,
        ore=0,
        science=0,
        build_city_count=1,
        build_road_count=0,
        build_farm_count=0,
        build_lumber_mill_count=0,
        build_mine_count=0,
        build_library_count=0,
        research_agriculture_count=0,
        research_logging_count=0,
        research_mining_count=0,
        research_education_count=0,
        skip_count=0,
        decision_count=0,
        decision_time_ms_total=0.0,
        decision_time_ms_avg=0.0,
        decision_time_ms_max=0.0,
        turn_elapsed_ms_total=0.0,
        turn_elapsed_ms_avg=0.0,
        turn_elapsed_ms_max=0.0,
        session_elapsed_ms=0.0,
    )


def test_batch_autoplay_exports_serial_outputs(monkeypatch, tmp_path) -> None:
    def fake_run_single_game_task(task: object) -> RecordEntry:
        assert isinstance(task, batch_autoplay.BatchGameTask)
        return _make_record(
            seed=task.seed,
            policy_type=task.policy_type,
            final_score=task.seed * 10,
        )

    monkeypatch.setattr(batch_autoplay, "run_single_game_task", fake_run_single_game_task)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "batch_autoplay.py",
            "-n",
            "2",
            "--policy",
            "greedy",
            "--seed-start",
            "3",
            "--output-dir",
            str(tmp_path),
            "--label",
            "serial",
            "--workers",
            "1",
        ],
    )

    exit_code = batch_autoplay.main()

    assert exit_code == 0
    base_name = "greedy_16_80_normal_3_4_serial"
    database = RecordDatabase.from_dict(
        json.loads((tmp_path / f"{base_name}.json").read_text(encoding="utf-8"))
    )
    summary = json.loads((tmp_path / f"{base_name}_summary.json").read_text(encoding="utf-8"))
    with (tmp_path / f"{base_name}.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert [record.record_id for record in database.records] == [3, 4]
    assert [row["record_id"] for row in rows] == ["3", "4"]
    assert summary["execution_mode"] == "serial"
    assert summary["workers"] == 1
    assert summary["chunksize"] == 8
    assert summary["seed_start"] == 3
    assert summary["seed_end"] == 4


def test_batch_autoplay_fast_mode_exports_artifacts(monkeypatch, tmp_path) -> None:
    def fake_run_single_game_task(task: object) -> RecordEntry:
        assert isinstance(task, batch_autoplay.BatchGameTask)
        return _make_record(
            seed=task.seed,
            policy_type=task.policy_type,
            final_score=task.seed * 10,
        )

    monkeypatch.setattr(batch_autoplay, "run_single_game_task", fake_run_single_game_task)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "batch_autoplay.py",
            "-n",
            "1",
            "--policy",
            "greedy",
            "--seed-start",
            "1",
            "--output-dir",
            str(tmp_path),
            "--label",
            "fast",
            "--workers",
            "1",
            "--artifact-mode",
            "fast",
            "--artifact-format",
            "jsonl",
        ],
    )

    exit_code = batch_autoplay.main()

    assert exit_code == 0
    artifact_dir = tmp_path / "greedy_16_80_normal_1_1_fast_artifacts"
    summary_path = tmp_path / "greedy_16_80_normal_1_1_fast_summary.json"
    assert artifact_dir.exists()
    assert (artifact_dir / "macro.jsonl").exists()
    assert not (tmp_path / "greedy_16_80_normal_1_1_fast.json").exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["effective_artifact_mode"] == "fast"
    assert summary["artifact_file_format"] == "jsonl"


def test_build_batch_tasks_preserves_seed_order() -> None:
    tasks = batch_autoplay.build_batch_tasks(
        games=3,
        seed_start=10,
        policy_type=PolicyType.RANDOM,
        map_size=16,
        turn_limit=80,
        map_difficulty=batch_autoplay._map_difficulty_from_str("hard"),
    )

    assert [task.seed for task in tasks] == [10, 11, 12]
    assert all(task.policy_type is PolicyType.RANDOM for task in tasks)


def test_build_batch_tasks_preserves_search_parameters() -> None:
    tasks = batch_autoplay.build_batch_tasks(
        games=2,
        seed_start=20,
        policy_type=PolicyType.SEARCH,
        map_size=12,
        turn_limit=30,
        map_difficulty=batch_autoplay._map_difficulty_from_str("normal"),
        search_depth=2,
        search_beam_width=3,
        search_candidate_limit=5,
    )

    assert [task.seed for task in tasks] == [20, 21]
    assert all(task.policy_type is PolicyType.SEARCH for task in tasks)
    assert all(task.search_depth == 2 for task in tasks)
    assert all(task.search_beam_width == 3 for task in tasks)
    assert all(task.search_candidate_limit == 5 for task in tasks)


def test_batch_autoplay_parallel_path_uses_process_pool(monkeypatch, tmp_path) -> None:
    fake_executor = _FakeProcessPoolExecutor(max_workers=2)

    def fake_executor_factory(*, max_workers: int) -> _FakeProcessPoolExecutor:
        assert max_workers == 2
        return fake_executor

    def fake_run_single_game_task(task: object) -> RecordEntry:
        assert isinstance(task, batch_autoplay.BatchGameTask)
        return _make_record(seed=task.seed, policy_type=task.policy_type, final_score=25)

    monkeypatch.setattr(batch_autoplay, "ProcessPoolExecutor", fake_executor_factory)
    monkeypatch.setattr(batch_autoplay, "run_single_game_task", fake_run_single_game_task)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "batch_autoplay.py",
            "-n",
            "3",
            "--policy",
            "random",
            "--seed-start",
            "8",
            "--output-dir",
            str(tmp_path),
            "--label",
            "parallel",
            "--workers",
            "2",
            "--chunksize",
            "4",
        ],
    )

    exit_code = batch_autoplay.main()

    assert exit_code == 0
    assert len(fake_executor.map_calls) == 1
    _, tasks, chunksize = fake_executor.map_calls[0]
    assert chunksize == 4
    assert [task.seed for task in tasks] == [8, 9, 10]

    summary = json.loads(
        (tmp_path / "random_16_80_normal_8_10_parallel_summary.json").read_text(encoding="utf-8")
    )
    database = RecordDatabase.from_dict(
        json.loads(
            (tmp_path / "random_16_80_normal_8_10_parallel.json").read_text(encoding="utf-8")
        )
    )

    assert [record.record_id for record in database.records] == [8, 9, 10]
    assert summary["execution_mode"] == "parallel"
    assert summary["workers"] == 2
    assert summary["chunksize"] == 4


def test_batch_autoplay_exports_search_outputs_with_search_config(
    monkeypatch,
    tmp_path,
) -> None:
    def fake_run_single_game_task(task: object) -> RecordEntry:
        assert isinstance(task, batch_autoplay.BatchGameTask)
        assert task.policy_type is PolicyType.SEARCH
        assert task.search_depth == 2
        assert task.search_beam_width == 3
        assert task.search_candidate_limit == 5
        return _make_record(seed=task.seed, policy_type=task.policy_type, final_score=50)

    monkeypatch.setattr(batch_autoplay, "run_single_game_task", fake_run_single_game_task)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "batch_autoplay.py",
            "-n",
            "1",
            "--policy",
            "search",
            "--search-depth",
            "2",
            "--search-beam-width",
            "3",
            "--search-candidate-limit",
            "5",
            "--seed-start",
            "12",
            "--output-dir",
            str(tmp_path),
            "--label",
            "search",
            "--workers",
            "1",
        ],
    )

    exit_code = batch_autoplay.main()

    assert exit_code == 0
    base_name = "search_d2_b3_c5_16_80_normal_12_12_search"
    database = RecordDatabase.from_dict(
        json.loads((tmp_path / f"{base_name}.json").read_text(encoding="utf-8"))
    )
    summary = json.loads((tmp_path / f"{base_name}_summary.json").read_text(encoding="utf-8"))

    assert database.records[0].ai_type == "Search"
    assert summary["policy"] == "search"
    assert summary["search_depth"] == 2
    assert summary["search_beam_width"] == 3
    assert summary["search_candidate_limit"] == 5
