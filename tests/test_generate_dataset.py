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
SPEC.loader.exec_module(generate_dataset)


def _make_record(
    *,
    record_id: int,
    seed: int,
    policy_type: PolicyType,
    final_score: int,
) -> RecordEntry:
    ai_type = "Greedy" if policy_type is PolicyType.GREEDY else "Random"
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
    ) -> RecordEntry:
        del map_size, turn_limit, map_difficulty
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
    assert manifest["anomaly_json_path"].endswith("dataset_unit_anomalies.json")
    assert manifest["anomaly_csv_path"].endswith("dataset_unit_anomalies.csv")
