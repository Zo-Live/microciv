from __future__ import annotations

import json

import microciv.records.store as record_store_module
from microciv.game.enums import OccupantType, PlaybackMode, PolicyType, TechType, TerrainType
from microciv.game.models import (
    BuildingCounts,
    City,
    GameConfig,
    GameState,
    Network,
    ResourcePool,
    Road,
    Tile,
)
from microciv.records.export import export_records_json
from microciv.records.models import (
    RECORDS_SCHEMA_VERSION,
    RecordDatabase,
    RecordDecisionContext,
    RecordEntry,
)
from microciv.records.store import RecordStore


def test_record_entry_from_game_state_captures_frozen_fields() -> None:
    state = build_completed_state()

    entry = RecordEntry.from_game_state(
        record_id=7,
        timestamp="2026-04-09T12:34:56+08:00",
        state=state,
        game_version="0.1.0-test",
    )

    assert entry.record_id == 7
    assert entry.mode == "play"
    assert entry.ai_type == "Human"
    assert entry.playback_mode == ""
    assert entry.actual_turns == 30
    assert entry.final_score == 299
    assert entry.city_count == 1
    assert entry.building_count == 2
    assert entry.tech_count == 2
    assert entry.final_map[0].x == 0
    assert entry.final_map[0].occupant == "city"
    assert entry.cities[0].farm == 1
    assert entry.cities[0].library == 1
    assert entry.roads[0].road_id == 1
    assert entry.networks[0].unlocked_techs == ["agriculture", "education"]
    assert entry.turn_elapsed_ms_total == 900.0
    assert entry.session_elapsed_ms == 1200.0


def test_record_store_persists_and_reloads_completed_games(tmp_path) -> None:
    records_path = tmp_path / "data" / "records.json"
    store = RecordStore(records_path)

    entry = store.append_completed_game(
        build_completed_state(),
        timestamp="2026-04-09T12:00:00+08:00",
        game_version="0.1.0-test",
    )

    payload = json.loads(records_path.read_text(encoding="utf-8"))
    reloaded = store.load()

    assert entry.record_id == 1
    assert payload["schema_version"] == RECORDS_SCHEMA_VERSION
    assert payload["next_record_id"] == 2
    assert len(payload["records"]) == 1
    assert "final_map" in payload["records"][0]
    assert "cities" in payload["records"][0]
    assert "roads" in payload["records"][0]
    assert "networks" in payload["records"][0]
    assert reloaded.next_record_id == 2
    assert len(reloaded.records) == 1
    assert reloaded.records[0].timestamp == "2026-04-09T12:00:00+08:00"
    assert reloaded.records[0].final_score == 299


def test_record_store_resets_old_schema_file(tmp_path) -> None:
    records_path = tmp_path / "data" / "records.json"
    records_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.write_text(
        json.dumps({"schema_version": 1, "next_record_id": 1, "records": []}), encoding="utf-8"
    )

    database = RecordStore(records_path).load()

    assert database.schema_version == RECORDS_SCHEMA_VERSION
    assert database.records == []
    assert not records_path.exists()
    assert records_path.with_suffix(".json.incompatible").exists()


def test_record_store_resets_schema_version_3(tmp_path) -> None:
    records_path = tmp_path / "data" / "records.json"
    records_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.write_text(
        json.dumps({"schema_version": 3, "next_record_id": 1, "records": []}), encoding="utf-8"
    )

    database = RecordStore(records_path).load()

    assert database.schema_version == RECORDS_SCHEMA_VERSION
    assert database.records == []
    assert records_path.with_suffix(".json.incompatible").exists()


def test_record_store_resets_missing_top_level_fields(tmp_path) -> None:
    records_path = tmp_path / "data" / "records.json"
    records_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.write_text(
        json.dumps({"records": []}), encoding="utf-8"
    )

    database = RecordStore(records_path).load()

    assert database.schema_version == RECORDS_SCHEMA_VERSION
    assert database.records == []
    assert records_path.with_suffix(".json.incompatible").exists()


def test_record_store_resets_baseline_ai_type(tmp_path) -> None:
    records_path = tmp_path / "data" / "records.json"
    records_path.parent.mkdir(parents=True, exist_ok=True)
    record = build_completed_state()
    entry = RecordEntry.from_game_state(
        record_id=1,
        timestamp="2026-04-09T12:00:00+08:00",
        state=record,
    )
    payload = entry.to_dict()
    payload["ai_type"] = "baseline"
    records_path.write_text(
        json.dumps(
            {
                "schema_version": RECORDS_SCHEMA_VERSION,
                "next_record_id": 2,
                "records": [payload],
            }
        ),
        encoding="utf-8",
    )

    database = RecordStore(records_path).load()

    assert database.schema_version == RECORDS_SCHEMA_VERSION
    assert database.records == []
    assert records_path.with_suffix(".json.incompatible").exists()


def test_record_store_fifo_trims_oldest_entries(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(record_store_module, "MAX_RECORDS", 3)
    store = RecordStore(tmp_path / "data" / "records.json")

    for seed in range(5):
        store.append_completed_game(
            build_completed_state(seed=seed),
            timestamp=f"2026-04-09T12:00:0{seed}+08:00",
            game_version="0.1.0-test",
        )

    reloaded = store.load()

    assert [record.record_id for record in reloaded.records] == [3, 4, 5]
    assert [record.seed for record in reloaded.records] == [2, 3, 4]
    assert reloaded.next_record_id == 6


def test_export_records_json_uses_fixed_filename_and_payload(tmp_path) -> None:
    play_record = RecordEntry.from_game_state(
        record_id=1,
        timestamp="2026-04-09T12:34:56+08:00",
        state=build_completed_state(seed=11),
    )
    autoplay_record = RecordEntry.from_game_state(
        record_id=2,
        timestamp="2026-04-09T12:35:56+08:00",
        state=build_completed_autoplay_state(seed=22),
    )

    output_path = export_records_json(
        RecordDatabase(records=[play_record, autoplay_record]),
        tmp_path / "exports",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert output_path.name == "records_export.json"
    assert payload["records"][0]["record_id"] == 1
    assert payload["records"][0]["ai_type"] == "Human"
    assert payload["records"][1]["record_id"] == 2
    assert payload["records"][1]["ai_type"] == "Random"
    assert payload["records"][1]["playback_mode"] == "speed"


def test_record_store_can_delete_and_clear_records(tmp_path) -> None:
    store = RecordStore(tmp_path / "data" / "records.json")
    store.append_completed_game(
        build_completed_state(seed=1),
        timestamp="2026-04-09T12:00:00+08:00",
    )
    store.append_completed_game(
        build_completed_state(seed=2),
        timestamp="2026-04-09T12:01:00+08:00",
    )

    assert store.delete_record(1) is True
    assert [record.record_id for record in store.load().records] == [2]

    store.clear()
    assert store.load().records == []


def test_record_decision_context_roundtrip_preserves_greedy_history_fields() -> None:
    context = RecordDecisionContext(
        turn=12,
        legal_actions_count=7,
        legal_build_city_count=3,
        legal_build_road_count=2,
        legal_build_building_count=1,
        legal_research_tech_count=0,
        legal_skip_count=1,
        chosen_action_type="build_road",
        greedy_stage="rescue",
        greedy_priority="food_rescue",
        greedy_best_action_type="build_road",
        greedy_best_score=812.5,
        greedy_best_delta_score=-9,
        greedy_food_pressure=14,
        greedy_starving_networks=1,
        greedy_connected_cities=0,
        greedy_total_food=18,
        greedy_network_count=2,
        greedy_global_starving_delta=1,
        greedy_global_network_delta=1,
        greedy_global_isolation_delta=2,
        greedy_rescue_effective=False,
        greedy_escape_mode=True,
        greedy_escape_reason="negative_delta_stall",
        greedy_food_rescue_stalled=True,
        greedy_food_rescue_chain=3,
        greedy_fill_reopen_reason="repeated_fill_skip",
        greedy_best_connection_steps=1,
        greedy_best_future_network_starving=False,
        greedy_score_breakdown={"total": 320, "starving_network_penalty": 70},
        greedy_best_site_budget={"food_balance": 1, "total_yield": 9},
        greedy_best_future_network_budget={"network_id": 1, "pressure": 4},
        random_type_weights={"build_road": 2.5},
    )

    restored = RecordDecisionContext.from_dict(context.to_dict())

    assert restored.greedy_global_starving_delta == 1
    assert restored.greedy_global_network_delta == 1
    assert restored.greedy_global_isolation_delta == 2
    assert restored.greedy_escape_mode is True
    assert restored.greedy_escape_reason == "negative_delta_stall"
    assert restored.greedy_food_rescue_stalled is True
    assert restored.greedy_food_rescue_chain == 3
    assert restored.greedy_fill_reopen_reason == "repeated_fill_skip"


def build_completed_state(*, seed: int = 7) -> GameState:
    state = GameState.empty(GameConfig.for_play(turn_limit=30, seed=seed))
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.FOREST),
        (1, 0): Tile(base_terrain=TerrainType.RIVER, occupant=OccupantType.ROAD),
    }
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(farm=1, library=1),
        )
    }
    state.roads = {1: Road(road_id=1, coord=(1, 0), built_turn=10)}
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=12, wood=3, ore=4, science=6),
            unlocked_techs={TechType.AGRICULTURE, TechType.EDUCATION},
        )
    }
    state.turn = 30
    state.is_game_over = True
    state.stats.build_city_count = 1
    state.stats.build_road_count = 1
    state.stats.build_farm_count = 1
    state.stats.build_library_count = 1
    state.stats.research_agriculture_count = 1
    state.stats.research_education_count = 1
    state.stats.decision_count = 12
    state.stats.decision_time_ms_total = 240.0
    state.stats.decision_time_ms_avg = 20.0
    state.stats.decision_time_ms_max = 45.0
    state.stats.turn_elapsed_ms_total = 900.0
    state.stats.turn_elapsed_ms_avg = 30.0
    state.stats.turn_elapsed_ms_max = 75.0
    state.stats.session_elapsed_ms = 1200.0
    return state


def build_completed_autoplay_state(*, seed: int = 13) -> GameState:
    config = GameConfig.for_autoplay(
        turn_limit=30,
        seed=seed,
        policy_type=PolicyType.RANDOM,
        playback_mode=PlaybackMode.SPEED,
    )
    state = GameState.empty(config)
    state.board = {(0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY)}
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(mine=1),
        )
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=10, wood=5, ore=5, science=0),
            unlocked_techs={TechType.MINING},
        )
    }
    state.turn = 30
    state.is_game_over = True
    state.stats.build_city_count = 1
    state.stats.build_mine_count = 1
    state.stats.research_mining_count = 1
    state.stats.decision_count = 30
    state.stats.decision_time_ms_total = 1234.0
    state.stats.decision_time_ms_avg = 41.0
    state.stats.decision_time_ms_max = 99.0
    state.stats.turn_elapsed_ms_total = 1900.0
    state.stats.turn_elapsed_ms_avg = 63.0
    state.stats.turn_elapsed_ms_max = 144.0
    state.stats.session_elapsed_ms = 2500.0
    return state
