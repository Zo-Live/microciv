from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

from microciv.game.enums import PolicyType
from microciv.records.models import RecordDatabase, RecordEntry

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_dataset.py"
SPEC = importlib.util.spec_from_file_location("generate_dataset", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
generate_dataset = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generate_dataset
SPEC.loader.exec_module(generate_dataset)


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


def _make_record(
    *,
    record_id: int,
    seed: int,
    policy_type: PolicyType,
    final_score: int,
) -> RecordEntry:
    if policy_type is PolicyType.GREEDY:
        ai_type = "Greedy"
    elif policy_type is PolicyType.RANDOM:
        ai_type = "Random"
    else:
        ai_type = "Search"
    return RecordEntry(
        record_id=record_id,
        timestamp="2026-04-19T12:00:00+08:00",
        game_version="0.1.0-test",
        mode="autoplay",
        ai_type=ai_type,
        custom_goal="",
        playback_mode="speed",
        seed=seed,
        map_size=12,
        map_difficulty="normal",
        turn_limit=30,
        actual_turns=30,
        final_score=final_score,
        city_count=1,
        building_count=0,
        tech_count=0,
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


def test_generate_dataset_exports_anomaly_json_and_csv(monkeypatch, tmp_path) -> None:
    def fake_run_game(
        *,
        record_id: int,
        seed: int,
        policy_type: PolicyType,
        map_size: int,
        turn_limit: int,
        map_difficulty: object,
        search_depth: int = 3,
        search_max_depth: int = 6,
        search_beam_width: int = 4,
        search_candidate_limit: int = 16,
    ) -> RecordEntry:
        del map_size, turn_limit, map_difficulty, search_depth, search_max_depth
        del search_beam_width
        del search_candidate_limit
        if policy_type is PolicyType.GREEDY:
            score = 5 if seed == 1 else -3
        else:
            score = 10 if seed == 1 else 2
        return _make_record(
            record_id=record_id,
            seed=seed,
            policy_type=policy_type,
            final_score=score,
        )

    monkeypatch.setattr(generate_dataset, "run_game", fake_run_game)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_dataset.py",
            "-n",
            "2",
            "--seed-start",
            "1",
            "--output-dir",
            str(tmp_path),
            "--policies",
            "greedy,random",
            "--map-sizes",
            "12",
            "--turn-limits",
            "30",
            "--difficulties",
            "normal",
            "--label",
            "unit",
            "--workers",
            "1",
        ],
    )

    exit_code = generate_dataset.main()

    assert exit_code == 0
    json_path = tmp_path / "dataset_unit.json"
    csv_path = tmp_path / "dataset_unit.csv"
    anomaly_json_path = tmp_path / "dataset_unit_anomalies.json"
    anomaly_csv_path = tmp_path / "dataset_unit_anomalies.csv"
    manifest_path = tmp_path / "dataset_unit_manifest.json"
    assert json_path.exists()
    assert csv_path.exists()
    assert anomaly_json_path.exists()
    assert anomaly_csv_path.exists()
    assert manifest_path.exists()

    database = RecordDatabase.from_dict(json.loads(json_path.read_text(encoding="utf-8")))
    anomaly_database = RecordDatabase.from_dict(
        json.loads(anomaly_json_path.read_text(encoding="utf-8"))
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with anomaly_csv_path.open(newline="", encoding="utf-8") as f:
        anomaly_rows = list(csv.DictReader(f))

    assert [record.record_id for record in database.records] == [1, 2, 3, 4]
    assert [(record.ai_type, record.seed) for record in database.records] == [
        ("Greedy", 1),
        ("Random", 1),
        ("Greedy", 2),
        ("Random", 2),
    ]
    assert [record.record_id for record in anomaly_database.records] == [1, 3]
    assert all(record.ai_type == "Greedy" for record in anomaly_database.records)
    assert [row["record_id"] for row in anomaly_rows] == ["1", "3"]
    assert manifest["anomaly_count"] == 2
    assert manifest["negative_score_anomaly_count"] == 1
    assert manifest["under_random_anomaly_count"] == 2
    assert manifest["seed_start"] == 1
    assert manifest["seed_end"] == 2
    assert manifest["execution_mode"] == "serial"
    assert manifest["workers"] == 1
    assert manifest["chunksize"] == 8
    assert manifest["anomaly_json_path"].endswith("dataset_unit_anomalies.json")
    assert manifest["anomaly_csv_path"].endswith("dataset_unit_anomalies.csv")


def test_generate_dataset_fast_mode_exports_artifacts_without_full_json(
    monkeypatch, tmp_path
) -> None:
    def fake_run_game_task(task: object) -> RecordEntry:
        assert isinstance(task, generate_dataset.GameTask)
        return _make_record(
            record_id=task.record_id,
            seed=task.seed,
            policy_type=task.policy_type,
            final_score=task.record_id * 10,
        )

    monkeypatch.setattr(generate_dataset, "run_game_task", fake_run_game_task)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_dataset.py",
            "-n",
            "1",
            "--seed-start",
            "1",
            "--output-dir",
            str(tmp_path),
            "--policies",
            "greedy,random",
            "--map-sizes",
            "12",
            "--turn-limits",
            "30",
            "--difficulties",
            "normal",
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

    exit_code = generate_dataset.main()

    assert exit_code == 0
    artifact_dir = tmp_path / "dataset_fast_artifacts"
    assert artifact_dir.exists()
    assert (artifact_dir / "macro.jsonl").exists()
    assert (artifact_dir / "artifact_manifest.json").exists()
    assert not (tmp_path / "dataset_fast.json").exists()
    assert not (tmp_path / "dataset_fast.csv").exists()

    manifest = json.loads((tmp_path / "dataset_fast_manifest.json").read_text(encoding="utf-8"))
    assert manifest["effective_artifact_mode"] == "fast"
    assert manifest["artifact_file_format"] == "jsonl"
    assert manifest["dataset_json_path"] == ""
    assert manifest["artifact_dir"].endswith("dataset_fast_artifacts")


def test_generate_dataset_defaults_to_three_policies(monkeypatch, tmp_path) -> None:
    def fake_run_game_task(task: object) -> RecordEntry:
        assert isinstance(task, generate_dataset.GameTask)
        return _make_record(
            record_id=task.record_id,
            seed=task.seed,
            policy_type=task.policy_type,
            final_score=task.record_id * 10,
        )

    monkeypatch.setattr(generate_dataset, "run_game_task", fake_run_game_task)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_dataset.py",
            "-n",
            "1",
            "--seed-start",
            "3",
            "--output-dir",
            str(tmp_path),
            "--map-sizes",
            "12",
            "--turn-limits",
            "30",
            "--difficulties",
            "normal",
            "--label",
            "defaults",
            "--workers",
            "1",
        ],
    )

    exit_code = generate_dataset.main()

    assert exit_code == 0
    database = RecordDatabase.from_dict(
        json.loads((tmp_path / "dataset_defaults.json").read_text(encoding="utf-8"))
    )
    manifest = json.loads((tmp_path / "dataset_defaults_manifest.json").read_text(encoding="utf-8"))

    assert [(record.ai_type, record.seed) for record in database.records] == [
        ("Greedy", 3),
        ("Random", 3),
        ("Search", 3),
    ]
    assert manifest["param_grid"]["policy"] == ["greedy", "random", "search"]
    assert manifest["policy_count"] == 3
    assert manifest["policy_variant_count"] == 3
    assert manifest["search_variant_count"] == 1


def test_build_game_tasks_preserves_seed_pairing_and_record_order() -> None:
    tasks, seed_end = generate_dataset.build_game_tasks(
        seed_start=5,
        games_per_combo=2,
        policies=[PolicyType.GREEDY, PolicyType.RANDOM],
        base_combos=[(12, 30, "normal")],
    )

    assert seed_end == 6
    assert [task.record_id for task in tasks] == [1, 2, 3, 4]
    assert [(task.seed, task.policy_type) for task in tasks] == [
        (5, PolicyType.GREEDY),
        (5, PolicyType.RANDOM),
        (6, PolicyType.GREEDY),
        (6, PolicyType.RANDOM),
    ]


def test_build_game_tasks_expands_search_grid_after_fixed_seed_baselines() -> None:
    tasks, seed_end = generate_dataset.build_game_tasks(
        seed_start=11,
        games_per_combo=1,
        policies=[PolicyType.GREEDY, PolicyType.RANDOM, PolicyType.SEARCH],
        base_combos=[(12, 30, "normal")],
        search_depths=[1, 2],
        search_max_depths=[6],
        search_beam_widths=[3],
        search_candidate_limits=[4, 5],
    )

    assert seed_end == 11
    assert [task.record_id for task in tasks] == [1, 2, 3, 4, 5, 6]
    assert [(task.seed, task.policy_type) for task in tasks] == [
        (11, PolicyType.GREEDY),
        (11, PolicyType.RANDOM),
        (11, PolicyType.SEARCH),
        (11, PolicyType.SEARCH),
        (11, PolicyType.SEARCH),
        (11, PolicyType.SEARCH),
    ]
    assert [
        (
            task.search_depth,
            task.search_max_depth,
            task.search_beam_width,
            task.search_candidate_limit,
        )
        for task in tasks
        if task.policy_type is PolicyType.SEARCH
    ] == [(1, 6, 3, 4), (1, 6, 3, 5), (2, 6, 3, 4), (2, 6, 3, 5)]


def test_generate_dataset_parallel_path_uses_process_pool_and_keeps_order(
    monkeypatch,
    tmp_path,
) -> None:
    fake_executor = _FakeProcessPoolExecutor(max_workers=2)

    def fake_executor_factory(*, max_workers: int) -> _FakeProcessPoolExecutor:
        assert max_workers == 2
        return fake_executor

    def fake_run_game_task(task: object) -> RecordEntry:
        assert isinstance(task, generate_dataset.GameTask)
        score = 20 if task.policy_type is PolicyType.GREEDY else 10
        return _make_record(
            record_id=task.record_id,
            seed=task.seed,
            policy_type=task.policy_type,
            final_score=score,
        )

    monkeypatch.setattr(generate_dataset, "ProcessPoolExecutor", fake_executor_factory)
    monkeypatch.setattr(generate_dataset, "run_game_task", fake_run_game_task)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_dataset.py",
            "-n",
            "2",
            "--seed-start",
            "7",
            "--output-dir",
            str(tmp_path),
            "--policies",
            "greedy,random",
            "--map-sizes",
            "12",
            "--turn-limits",
            "30",
            "--difficulties",
            "normal",
            "--label",
            "parallel",
            "--workers",
            "2",
            "--chunksize",
            "3",
        ],
    )

    exit_code = generate_dataset.main()

    assert exit_code == 0
    assert len(fake_executor.map_calls) == 1
    _, tasks, chunksize = fake_executor.map_calls[0]
    assert chunksize == 3
    assert [task.record_id for task in tasks] == [1, 2, 3, 4]
    assert [(task.seed, task.policy_type) for task in tasks] == [
        (7, PolicyType.GREEDY),
        (7, PolicyType.RANDOM),
        (8, PolicyType.GREEDY),
        (8, PolicyType.RANDOM),
    ]

    database = RecordDatabase.from_dict(
        json.loads((tmp_path / "dataset_parallel.json").read_text(encoding="utf-8"))
    )
    manifest = json.loads((tmp_path / "dataset_parallel_manifest.json").read_text(encoding="utf-8"))

    assert [record.record_id for record in database.records] == [1, 2, 3, 4]
    assert manifest["execution_mode"] == "parallel"
    assert manifest["workers"] == 2
    assert manifest["chunksize"] == 3
    assert manifest["seed_start"] == 7
    assert manifest["seed_end"] == 8


def test_generate_dataset_parallel_path_includes_search_grid_tasks(
    monkeypatch,
    tmp_path,
) -> None:
    fake_executor = _FakeProcessPoolExecutor(max_workers=2)

    def fake_executor_factory(*, max_workers: int) -> _FakeProcessPoolExecutor:
        assert max_workers == 2
        return fake_executor

    def fake_run_game_task(task: object) -> RecordEntry:
        assert isinstance(task, generate_dataset.GameTask)
        return _make_record(
            record_id=task.record_id,
            seed=task.seed,
            policy_type=task.policy_type,
            final_score=task.record_id,
        )

    monkeypatch.setattr(generate_dataset, "ProcessPoolExecutor", fake_executor_factory)
    monkeypatch.setattr(generate_dataset, "run_game_task", fake_run_game_task)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_dataset.py",
            "-n",
            "1",
            "--seed-start",
            "9",
            "--output-dir",
            str(tmp_path),
            "--policies",
            "greedy,random,search",
            "--search-depths",
            "1,2",
            "--search-max-depths",
            "6",
            "--search-beam-widths",
            "3",
            "--search-candidate-limits",
            "4,5",
            "--map-sizes",
            "12",
            "--turn-limits",
            "30",
            "--difficulties",
            "normal",
            "--label",
            "searchgrid",
            "--workers",
            "2",
        ],
    )

    exit_code = generate_dataset.main()

    assert exit_code == 0
    assert len(fake_executor.map_calls) == 1
    _, tasks, _chunksize = fake_executor.map_calls[0]
    assert len(tasks) == 6
    assert [
        (
            task.policy_type,
            task.search_depth,
            task.search_max_depth,
            task.search_beam_width,
            task.search_candidate_limit,
        )
        for task in tasks
    ] == [
        (PolicyType.GREEDY, 3, 6, 4, 16),
        (PolicyType.RANDOM, 3, 6, 4, 16),
        (PolicyType.SEARCH, 1, 6, 3, 4),
        (PolicyType.SEARCH, 1, 6, 3, 5),
        (PolicyType.SEARCH, 2, 6, 3, 4),
        (PolicyType.SEARCH, 2, 6, 3, 5),
    ]

    manifest = json.loads(
        (tmp_path / "dataset_searchgrid_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["execution_mode"] == "parallel"
    assert manifest["policy_variant_count"] == 6
    assert manifest["search_variant_count"] == 4
    assert manifest["search_param_grid"] == {
        "search_depth": [1, 2],
        "search_max_depth": [6],
        "search_beam_width": [3],
        "search_candidate_limit": [4, 5],
    }
