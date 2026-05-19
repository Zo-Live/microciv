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
    Stats,
    Tile,
)
from microciv.records.artifacts import record_decision_rows
from microciv.records.export import export_records_json
from microciv.records.models import (
    RECORDS_SCHEMA_VERSION,
    RecordDatabase,
    RecordDecisionContext,
    RecordEntry,
    RecordSearchActionSnapshot,
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
    records_path.write_text(json.dumps({"records": []}), encoding="utf-8")

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


def test_record_entry_accepts_search_ai_type_roundtrip() -> None:
    entry = RecordEntry.from_game_state(
        record_id=3,
        timestamp="2026-04-09T12:36:56+08:00",
        state=build_completed_autoplay_state(policy_type=PolicyType.SEARCH),
    )

    restored = RecordEntry.from_dict(entry.to_dict())

    assert entry.ai_type == "Search"
    assert restored.ai_type == "Search"


def test_record_entry_accepts_explicit_none_optional_decision_fields() -> None:
    state = build_completed_autoplay_state(policy_type=PolicyType.SEARCH)
    state.stats.decision_contexts = [
        {
            "turn": 1,
            "legal_actions_count": 1,
            "legal_build_city_count": 0,
            "legal_build_road_count": 0,
            "legal_build_building_count": 0,
            "legal_research_tech_count": 0,
            "legal_skip_count": 1,
            "chosen_action_type": None,
            "search_depth": None,
            "search_dominant_pressure": None,
            "search_is_risk_dominated": None,
        }
    ]

    entry = RecordEntry.from_game_state(
        record_id=4,
        timestamp="2026-04-09T12:37:56+08:00",
        state=state,
    )

    context = entry.decision_contexts[0]
    assert context.chosen_action_type is None
    assert context.search_depth is None
    assert context.search_dominant_pressure is None
    assert context.search_is_risk_dominated is None


def test_stats_record_decision_context_omits_none_policy_context_values() -> None:
    stats = Stats()

    stats.record_decision_context(
        turn=1,
        legal_actions_count=1,
        legal_build_city_count=0,
        legal_build_road_count=0,
        legal_build_building_count=0,
        legal_research_tech_count=0,
        legal_skip_count=1,
        decision_time_ms=7.25,
        policy_context={
            "search_depth": 3,
            "search_dominant_pressure": None,
        },
    )

    assert stats.decision_contexts[0]["decision_time_ms"] == 7.25
    assert stats.decision_contexts[0]["search_depth"] == 3
    assert "search_dominant_pressure" not in stats.decision_contexts[0]


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


def test_record_decision_context_roundtrip_preserves_search_fields() -> None:
    context = RecordDecisionContext(
        turn=3,
        legal_actions_count=5,
        legal_build_city_count=2,
        legal_build_road_count=1,
        legal_build_building_count=0,
        legal_research_tech_count=1,
        legal_skip_count=1,
        chosen_action_type="build_city",
        decision_time_ms=12.5,
        search_mode="expand",
        search_depth=2,
        search_actual_depth=1,
        search_base_depth=2,
        search_max_depth=2,
        search_depth_reason="fixed",
        search_deep_search_enabled=False,
        search_planning_mode="greedy_anchor",
        search_planning_reason="healthy_greedy_city",
        search_overrode_greedy=True,
        search_intervention_trigger="stall_probe",
        search_probe_accepted_reason="stall_score_not_worse",
        search_beam_width=3,
        search_candidate_limit=5,
        search_root_legal_build_city_count=4,
        search_root_legal_build_road_count=1,
        search_root_legal_build_building_count=0,
        search_root_legal_research_tech_count=1,
        search_root_legal_skip_count=1,
        search_root_candidate_build_city_count=3,
        search_root_candidate_build_road_count=1,
        search_root_candidate_build_building_count=0,
        search_root_candidate_research_tech_count=1,
        search_root_candidate_skip_count=0,
        search_nodes_expanded=4,
        search_candidates_considered=11,
        search_leaf_count=9,
        search_best_value=12345,
        search_value_components={"score_total": 1000, "expansion_deficit_penalty": -200},
        search_sequence_adjustment=2500,
        search_dominant_pressure="search_sequence_adjustment",
        search_dominant_pressure_value=2500,
        search_risk_pressure_total=200,
        search_is_risk_dominated=False,
        search_is_sequence_adjusted=True,
        search_best_score_total=321,
        search_best_connected_city_count=2,
        search_best_isolated_city_count=0,
        search_best_starving_network_count=0,
        search_best_network_count=1,
        search_best_largest_network_size=2,
        search_best_total_food=42,
        search_best_total_wood=7,
        search_best_total_ore=5,
        search_best_total_science=9,
        search_best_food_pressure=0,
        search_best_starving_turns=0,
        search_root_chosen_rank=2,
        search_root_chosen_value=12000,
        search_root_best_value=13000,
        search_root_value_margin=1000,
        search_root_best_action_type="build_road",
        search_root_chosen_action_type="build_city",
        search_root_best_build_city_value=12000,
        search_root_best_build_road_value=13000,
        search_root_candidate_cut_ratio=0.25,
        search_root_safe_city_candidate_count=2,
        search_root_effective_connection_road_candidate_count=1,
        search_root_rescue_candidate_count=3,
        search_root_effective_city_candidate_count=2,
        search_root_redundant_road_candidate_count=0,
        search_root_high_roi_building_candidate_count=1,
        search_root_gated_candidate_count=4,
        search_bridge_candidate_count=1,
        search_bridge_min_steps=2,
        search_bridge_progress_after_first_step=1,
        search_delta_starving_network_count=-1,
        search_delta_food_pressure=-4,
        search_delta_isolated_city_count=0,
        search_delta_network_count=-1,
        search_delta_connected_city_count=2,
        search_delta_road_overbuild=0,
        search_delta_worst_network_food_pressure=-3,
        search_delta_min_network_food=4,
        search_road_merges_networks=True,
        search_road_connected_city_delta=2,
        search_road_is_redundant=False,
        search_road_after_full_connectivity=False,
        search_greedy_action_type="build_city",
        search_matches_greedy_action=True,
        search_greedy_action_in_root_candidates=True,
        search_greedy_action_root_rank=1,
        search_greedy_action_root_value=12000,
        search_greedy_action_root_value_margin=1000,
        search_chosen_value_delta_vs_greedy_action=0,
        search_chosen_city_site_score=240,
        search_greedy_city_site_score=240,
        search_chosen_city_site_score_delta_vs_greedy=0,
        search_chosen_city_resource_ring_bonus=180,
        search_chosen_city_food_balance=2,
        search_chosen_city_total_yield=8,
        search_chosen_city_river_access=True,
        search_chosen_city_forest_neighbors=2,
        search_chosen_city_mountain_neighbors=1,
        search_chosen_city_river_neighbors=1,
        search_chosen_city_plain_neighbors=3,
        search_chosen_city_occupied_neighbors=0,
        search_chosen_city_distance_to_network=2,
        search_greedy_city_food_balance=2,
        search_greedy_city_total_yield=8,
        search_greedy_city_river_access=True,
        search_greedy_city_forest_neighbors=2,
        search_greedy_city_mountain_neighbors=1,
        search_greedy_city_river_neighbors=1,
        search_greedy_city_plain_neighbors=3,
        search_greedy_city_occupied_neighbors=0,
        search_greedy_city_distance_to_network=2,
        search_greedy_city_resource_ring_bonus=180,
        search_min_network_food_after_action=20,
        search_worst_network_food_pressure_after_action=0,
        search_food_surplus_network_count_after_action=1,
        search_food_deficit_network_count_after_action=0,
        search_greedy_after_score_total=320,
        search_greedy_after_starving_network_count=0,
        search_greedy_after_food_pressure=2,
        search_greedy_after_min_network_food=18,
        search_greedy_after_network_count=2,
        search_greedy_after_connected_city_count=1,
        search_greedy_after_isolated_city_count=1,
        search_selected_after_score_total=321,
        search_selected_after_starving_network_count=0,
        search_selected_after_food_pressure=0,
        search_selected_after_min_network_food=20,
        search_selected_after_network_count=1,
        search_selected_after_connected_city_count=2,
        search_selected_after_isolated_city_count=0,
        search_simulation_cache_hits=8,
        search_simulation_cache_misses=5,
        search_profile_city_count=1,
        search_profile_target_city_count=5,
        search_profile_expansion_deficit=4,
        search_profile_safe_expansion_deficit=3,
        search_profile_network_count=1,
        search_profile_connected_city_count=0,
        search_profile_isolated_city_count=1,
        search_profile_starving_network_count=0,
        search_profile_food_pressure=0,
        search_profile_road_overbuild=0,
        search_profile_fill_count=0,
        search_best_sequence=[
            RecordSearchActionSnapshot(action_type="build_city", x=1, y=2),
            RecordSearchActionSnapshot(
                action_type="research_tech",
                city_id=1,
                tech_type="agriculture",
            ),
        ],
    )

    restored = RecordDecisionContext.from_dict(context.to_dict())

    assert restored.search_depth == 2
    assert restored.search_actual_depth == 1
    assert restored.decision_time_ms == 12.5
    assert restored.search_mode == "expand"
    assert restored.search_deep_search_enabled is False
    assert restored.search_planning_mode == "greedy_anchor"
    assert restored.search_planning_reason == "healthy_greedy_city"
    assert restored.search_overrode_greedy is True
    assert restored.search_intervention_trigger == "stall_probe"
    assert restored.search_probe_accepted_reason == "stall_score_not_worse"
    assert restored.search_depth_reason == "fixed"
    assert restored.search_root_candidate_build_city_count == 3
    assert restored.search_root_candidate_skip_count == 0
    assert restored.search_nodes_expanded == 4
    assert restored.search_best_value == 12345
    assert restored.search_value_components["score_total"] == 1000
    assert restored.search_sequence_adjustment == 2500
    assert restored.search_dominant_pressure == "search_sequence_adjustment"
    assert restored.search_dominant_pressure_value == 2500
    assert restored.search_risk_pressure_total == 200
    assert restored.search_is_risk_dominated is False
    assert restored.search_is_sequence_adjusted is True
    assert restored.search_best_score_total == 321
    assert restored.search_best_connected_city_count == 2
    assert restored.search_best_total_food == 42
    assert restored.search_best_food_pressure == 0
    assert restored.search_root_chosen_rank == 2
    assert restored.search_root_best_value == 13000
    assert restored.search_root_value_margin == 1000
    assert restored.search_root_best_action_type == "build_road"
    assert restored.search_root_candidate_cut_ratio == 0.25
    assert restored.search_root_safe_city_candidate_count == 2
    assert restored.search_root_effective_city_candidate_count == 2
    assert restored.search_root_redundant_road_candidate_count == 0
    assert restored.search_root_high_roi_building_candidate_count == 1
    assert restored.search_root_gated_candidate_count == 4
    assert restored.search_bridge_candidate_count == 1
    assert restored.search_bridge_min_steps == 2
    assert restored.search_bridge_progress_after_first_step == 1
    assert restored.search_delta_food_pressure == -4
    assert restored.search_delta_worst_network_food_pressure == -3
    assert restored.search_delta_min_network_food == 4
    assert restored.search_delta_connected_city_count == 2
    assert restored.search_road_merges_networks is True
    assert restored.search_road_is_redundant is False
    assert restored.search_greedy_action_type == "build_city"
    assert restored.search_matches_greedy_action is True
    assert restored.search_greedy_action_in_root_candidates is True
    assert restored.search_greedy_action_root_rank == 1
    assert restored.search_chosen_city_site_score == 240
    assert restored.search_chosen_city_resource_ring_bonus == 180
    assert restored.search_chosen_city_food_balance == 2
    assert restored.search_chosen_city_river_access is True
    assert restored.search_greedy_city_site_score == 240
    assert restored.search_greedy_city_resource_ring_bonus == 180
    assert restored.search_min_network_food_after_action == 20
    assert restored.search_food_surplus_network_count_after_action == 1
    assert restored.search_greedy_after_score_total == 320
    assert restored.search_selected_after_score_total == 321
    assert restored.search_selected_after_connected_city_count == 2
    assert restored.search_simulation_cache_hits == 8
    assert restored.search_simulation_cache_misses == 5
    assert restored.search_profile_safe_expansion_deficit == 3
    assert [action.action_type for action in restored.search_best_sequence] == [
        "build_city",
        "research_tech",
    ]
    assert restored.search_best_sequence[0].x == 1
    assert restored.search_best_sequence[1].tech_type == "agriculture"


def test_record_decision_artifact_rows_preserve_search_planning_fields() -> None:
    record = RecordEntry.from_game_state(
        record_id=9,
        timestamp="2026-04-09T12:38:56+08:00",
        state=build_completed_autoplay_state(policy_type=PolicyType.SEARCH),
    )
    record.decision_contexts = [
        RecordDecisionContext(
            turn=3,
            legal_actions_count=5,
            legal_build_city_count=2,
            legal_build_road_count=1,
            legal_build_building_count=0,
            legal_research_tech_count=1,
            legal_skip_count=1,
            chosen_action_type="build_city",
            search_mode="expand",
            search_depth=2,
            search_actual_depth=1,
            search_base_depth=2,
            search_max_depth=6,
            search_depth_reason="steady",
            search_deep_search_enabled=False,
            search_planning_mode="greedy_anchor",
            search_planning_reason="healthy_greedy_city",
            search_overrode_greedy=True,
            search_intervention_trigger="stall_probe",
            search_probe_accepted_reason="stall_score_not_worse",
            search_delta_worst_network_food_pressure=-3,
            search_delta_min_network_food=4,
            search_greedy_after_score_total=320,
            search_selected_after_score_total=321,
            search_simulation_cache_hits=8,
            search_simulation_cache_misses=5,
            search_bridge_candidate_count=1,
            search_bridge_min_steps=2,
            search_bridge_progress_after_first_step=1,
            search_chosen_city_resource_ring_bonus=180,
            search_greedy_city_resource_ring_bonus=180,
        )
    ]

    row = record_decision_rows(record)[0]

    assert row["search_actual_depth"] == 1
    assert row["search_deep_search_enabled"] == 0
    assert row["search_planning_mode"] == "greedy_anchor"
    assert row["search_planning_reason"] == "healthy_greedy_city"
    assert row["search_overrode_greedy"] == 1
    assert row["search_intervention_trigger"] == "stall_probe"
    assert row["search_probe_accepted_reason"] == "stall_score_not_worse"
    assert row["search_delta_worst_network_food_pressure"] == -3
    assert row["search_delta_min_network_food"] == 4
    assert row["search_greedy_after_score_total"] == 320
    assert row["search_selected_after_score_total"] == 321
    assert row["search_simulation_cache_hits"] == 8
    assert row["search_simulation_cache_misses"] == 5
    assert row["search_bridge_candidate_count"] == 1
    assert row["search_bridge_min_steps"] == 2
    assert row["search_bridge_progress_after_first_step"] == 1
    assert row["search_chosen_city_resource_ring_bonus"] == 180
    assert row["search_greedy_city_resource_ring_bonus"] == 180


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


def build_completed_autoplay_state(
    *,
    seed: int = 13,
    policy_type: PolicyType = PolicyType.RANDOM,
) -> GameState:
    config = GameConfig.for_autoplay(
        turn_limit=30,
        seed=seed,
        policy_type=policy_type,
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
