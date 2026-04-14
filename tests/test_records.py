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
from microciv.records.models import RECORDS_SCHEMA_VERSION, RecordDatabase, RecordEntry
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
    assert entry.final_score == 111
    assert entry.city_count == 1
    assert entry.building_count == 2
    assert entry.tech_count == 2
    assert entry.final_map[0].x == 0
    assert entry.final_map[0].occupant == "city"
    assert entry.cities[0].farm == 1
    assert entry.cities[0].library == 1
    assert entry.roads[0].road_id == 1
    assert entry.networks[0].unlocked_techs == ["agriculture", "education"]
    assert entry.turn_elapsed_ms_total == 900
    assert entry.session_elapsed_ms == 1200


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
    assert reloaded.records[0].final_score == 111


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
    store.append_completed_game(build_completed_state(seed=1), timestamp="2026-04-09T12:00:00+08:00")
    store.append_completed_game(build_completed_state(seed=2), timestamp="2026-04-09T12:01:00+08:00")

    assert store.delete_record(1) is True
    assert [record.record_id for record in store.load().records] == [2]

    store.clear()
    assert store.load().records == []


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
    state.stats.decision_time_ms_total = 240
    state.stats.decision_time_ms_avg = 20
    state.stats.decision_time_ms_max = 45
    state.stats.turn_elapsed_ms_total = 900
    state.stats.turn_elapsed_ms_avg = 30
    state.stats.turn_elapsed_ms_max = 75
    state.stats.session_elapsed_ms = 1200
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
    state.stats.decision_time_ms_total = 1234
    state.stats.decision_time_ms_avg = 41
    state.stats.decision_time_ms_max = 99
    state.stats.turn_elapsed_ms_total = 1900
    state.stats.turn_elapsed_ms_avg = 63
    state.stats.turn_elapsed_ms_max = 144
    state.stats.session_elapsed_ms = 2500
    return state
