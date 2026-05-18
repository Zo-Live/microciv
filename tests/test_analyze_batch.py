from __future__ import annotations

import importlib.util
from pathlib import Path

from microciv.game.actions import Action
from microciv.game.enums import (
    BuildingType,
    MapDifficulty,
    OccupantType,
    PlaybackMode,
    PolicyType,
    TechType,
    TerrainType,
)
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
from microciv.records.artifacts import write_record_artifacts
from microciv.records.models import (
    RecordActionLogEntry,
    RecordDecisionContext,
    RecordEntry,
    RecordSearchActionSnapshot,
    RecordTurnSnapshot,
)

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "analyze_batch.py"
SPEC = importlib.util.spec_from_file_location("analyze_batch", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
analyze_batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyze_batch)


def _make_record(policy_type: PolicyType, seed: int) -> RecordEntry:
    config = GameConfig.for_autoplay(
        map_size=12,
        turn_limit=30,
        map_difficulty=MapDifficulty.NORMAL,
        policy_type=policy_type,
        playback_mode=PlaybackMode.SPEED,
        seed=seed,
    )
    state = GameState.empty(config)
    state.turn = 12
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.RIVER),
        (0, 2): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.ROAD),
        (1, 0): Tile(base_terrain=TerrainType.FOREST),
        (1, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 2): Tile(base_terrain=TerrainType.MOUNTAIN),
    }
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(farm=1, lumber_mill=1),
        )
    }
    state.roads = {
        1: Road(road_id=1, coord=(0, 2), built_turn=3),
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=50, wood=20, ore=10, science=8),
            unlocked_techs={TechType.AGRICULTURE, TechType.LOGGING},
        )
    }
    state.stats.build_city_count = 1
    state.stats.build_road_count = 1
    state.stats.build_farm_count = 1
    state.stats.build_lumber_mill_count = 1
    state.stats.research_agriculture_count = 1
    state.stats.research_logging_count = 1
    state.stats.skip_count = 1
    state.stats.record_action(1, Action.build_city((0, 0)))
    state.stats.record_action(2, Action.research_tech(1, TechType.AGRICULTURE))
    state.stats.record_action(3, Action.build_road((0, 2)))
    state.stats.record_action(4, Action.build_building(1, BuildingType.FARM))
    state.stats.record_action(5, Action.skip())
    state.stats.record_turn_snapshot(
        turn=5,
        score=state.score,
        food=50,
        wood=20,
        ore=10,
        science=8,
        city_count=1,
        building_count=2,
        tech_count=2,
        road_count=1,
        network_count=1,
        connected_city_count=0,
        isolated_city_count=1,
        largest_network_size=1,
        starving_network_count=0,
        legal_actions_count=12,
        score_breakdown={
            "city_score": 14,
            "connected_city_score": 0,
            "resource_ring_score": 12,
            "river_access_score": 20,
            "city_composition_bonus": 0,
            "building_score": 28,
            "tech_score": 240,
            "building_utilization_score": 8,
            "food_score": 3,
            "wood_score": 4,
            "ore_score": 2,
            "science_score": 1,
            "resource_score": 10,
            "library_science_bonus": 0,
            "building_mismatch_penalty": 0,
            "starving_network_penalty": 0,
            "fragmented_network_penalty": 0,
            "isolated_city_penalty": 12,
            "unproductive_road_penalty": 0,
            "total": 320,
        },
    )
    state.stats.record_decision_context(
        turn=5,
        legal_actions_count=12,
        legal_build_city_count=4,
        legal_build_road_count=2,
        legal_build_building_count=1,
        legal_research_tech_count=1,
        legal_skip_count=1,
        chosen_action_type="skip",
        policy_context={
            "greedy_stage": "fill",
            "greedy_priority": "skip",
            "greedy_best_action_type": "skip",
            "greedy_best_delta_score": -12,
            "greedy_score_breakdown": {
                "city_score": 14,
                "building_score": 28,
                "tech_score": 240,
                "starving_network_penalty": 0,
                "total": 320,
            },
            "greedy_best_site_budget": {
                "food_yield": 0,
                "wood_yield": 0,
                "ore_yield": 0,
                "science_yield": 0,
                "food_balance": 0,
                "total_yield": 0,
            },
            "greedy_best_future_network_budget": {
                "network_id": 1,
                "city_count": 1,
                "food": 50,
                "wood": 20,
                "ore": 10,
                "science": 8,
                "pressure": -46,
            },
            "greedy_best_future_network_starving": False,
        },
    )
    return RecordEntry.from_game_state(
        record_id=seed + 1,
        timestamp="2026-04-18T12:00:00+08:00",
        state=state,
    )


def test_generate_report_is_descriptive_and_uses_current_score_fields() -> None:
    records = [
        _make_record(PolicyType.GREEDY, 1),
        _make_record(PolicyType.RANDOM, 2),
    ]

    report = analyze_batch.generate_report(records)
    score_df = analyze_batch.build_score_breakdown_df(records)

    assert "## 4. Score Component Summary" in report
    assert "## 5. Turn Score Composition Summary" in report
    assert "## 6. Behavior Summary" in report
    assert "## 7. Greedy Stage Summary" in report
    assert "自动观察" not in report
    assert "building_utilization_score_mean" in report
    assert "river_access_score_mean" in report
    assert "avg_site_food_balance" in report
    assert "score_total_mean" in report
    assert "tech_utilization_score" not in report
    assert score_df["river_access_score"].gt(0).all()


def test_generate_report_from_artifacts_uses_tabular_input(tmp_path) -> None:
    search = _make_record(PolicyType.SEARCH, 3)
    search.decision_contexts = [
        RecordDecisionContext(
            turn=1,
            legal_actions_count=8,
            legal_build_city_count=4,
            legal_build_road_count=1,
            legal_build_building_count=1,
            legal_research_tech_count=1,
            legal_skip_count=1,
            chosen_action_type="build_city",
            search_mode="expand",
            search_depth=2,
            search_base_depth=2,
            search_max_depth=2,
            search_depth_reason="fixed",
            search_beam_width=3,
            search_candidate_limit=5,
            search_best_value=123,
            search_sequence_adjustment=500,
            search_dominant_pressure="search_sequence_adjustment",
            search_dominant_pressure_value=500,
            search_risk_pressure_total=100,
            search_is_risk_dominated=False,
            search_is_sequence_adjusted=True,
        )
    ]
    records = [
        _make_record(PolicyType.GREEDY, 1),
        _make_record(PolicyType.RANDOM, 2),
        search,
    ]
    write_record_artifacts(records, tmp_path, preferred_format="jsonl")

    frames = analyze_batch.read_artifact_frames(tmp_path, analyze_batch.pd)
    report = analyze_batch.generate_report_from_artifacts(frames)

    assert "_Source: artifact tables_" in report
    assert "## 2. Policy Summary" in report
    assert "Greedy" in report
    assert "Random" in report
    assert "### 7.4 Search Pressure Driver Summary" in report
    assert "search_sequence_adjustment" in report


def test_analyze_batch_reports_search_diagnostics() -> None:
    search = _make_record(PolicyType.SEARCH, 3)
    search.decision_contexts = [
        RecordDecisionContext(
            turn=1,
            legal_actions_count=8,
            legal_build_city_count=4,
            legal_build_road_count=1,
            legal_build_building_count=1,
            legal_research_tech_count=1,
            legal_skip_count=1,
            chosen_action_type="build_city",
            search_mode="expand",
            search_depth=2,
            search_base_depth=2,
            search_max_depth=2,
            search_depth_reason="fixed",
            search_beam_width=3,
            search_candidate_limit=5,
            search_root_candidate_build_city_count=3,
            search_root_candidate_build_road_count=1,
            search_root_candidate_build_building_count=0,
            search_root_candidate_research_tech_count=1,
            search_root_candidate_skip_count=0,
            search_nodes_expanded=4,
            search_candidates_considered=16,
            search_leaf_count=12,
            search_best_value=12345,
            search_value_components={"score_total": 12000, "expansion_deficit_penalty": -1600},
            search_sequence_adjustment=8500,
            search_dominant_pressure="search_sequence_adjustment",
            search_dominant_pressure_value=8500,
            search_risk_pressure_total=1600,
            search_is_risk_dominated=False,
            search_is_sequence_adjusted=True,
            search_best_score_total=456,
            search_best_food_pressure=4,
            search_best_starving_turns=1,
            search_best_sequence=[
                RecordSearchActionSnapshot(action_type="build_city", x=0, y=0),
                RecordSearchActionSnapshot(action_type="skip"),
            ],
        )
    ]

    report = analyze_batch.generate_report([search])
    summary = analyze_batch.build_search_summary_df([search])
    pressure_summary = analyze_batch.build_search_pressure_summary_from_decision_df(
        analyze_batch.build_decision_context_df([search])
    )
    restored_state = analyze_batch.record_to_state(search)

    assert restored_state.config.policy_type is PolicyType.SEARCH
    assert "### 7.1 Search Diagnostic Summary" in report
    assert "### 7.2 Search Depth Reason Summary" in report
    assert "### 7.3 Search Mode Summary" in report
    assert "### 7.4 Search Pressure Driver Summary" in report
    assert "search_nodes_expanded_mean" in report
    assert "search_sequence_adjustment_mean" in report
    assert "search_risk_pressure_total_mean" in report
    assert "risk_pressure_total_mean" in report
    assert "search_value_score_total_mean" in report
    assert "search_best_food_pressure_mean" in report
    assert int(summary.iloc[0]["search_leaf_count_mean"]) == 12
    assert int(summary.iloc[0]["search_best_food_pressure_mean"]) == 4
    assert int(summary.iloc[0]["search_sequence_length_mean"]) == 2
    assert pressure_summary.iloc[0]["search_dominant_pressure"] == "search_sequence_adjustment"


def test_analyze_batch_separates_search_variants_and_reports_timing() -> None:
    shallow = _make_record(PolicyType.SEARCH, 31)
    deep = _make_record(PolicyType.SEARCH, 32)
    shallow.record_id = 301
    deep.record_id = 302
    shallow.decision_time_ms_avg = 7.5
    shallow.decision_time_ms_max = 11.0
    shallow.decision_time_ms_total = 225.0
    deep.decision_time_ms_avg = 19.0
    deep.decision_time_ms_max = 30.0
    deep.decision_time_ms_total = 570.0
    shallow.decision_contexts = [
        RecordDecisionContext(
            turn=1,
            legal_actions_count=8,
            legal_build_city_count=4,
            legal_build_road_count=1,
            legal_build_building_count=1,
            legal_research_tech_count=1,
            legal_skip_count=1,
            chosen_action_type="build_city",
            search_mode="expand",
            search_depth=2,
            search_base_depth=2,
            search_max_depth=2,
            search_depth_reason="fixed",
            search_beam_width=3,
            search_candidate_limit=5,
            search_nodes_expanded=4,
            search_candidates_considered=16,
            search_leaf_count=12,
            search_best_value=100,
            search_best_sequence=[RecordSearchActionSnapshot(action_type="build_city", x=0, y=0)],
        )
    ]
    deep.decision_contexts = [
        RecordDecisionContext(
            turn=1,
            legal_actions_count=8,
            legal_build_city_count=4,
            legal_build_road_count=1,
            legal_build_building_count=1,
            legal_research_tech_count=1,
            legal_skip_count=1,
            chosen_action_type="build_city",
            search_mode="connect",
            search_depth=5,
            search_base_depth=3,
            search_max_depth=6,
            search_depth_reason="network_connect",
            search_beam_width=4,
            search_candidate_limit=6,
            search_nodes_expanded=9,
            search_candidates_considered=32,
            search_leaf_count=24,
            search_best_value=150,
            search_best_sequence=[RecordSearchActionSnapshot(action_type="build_city", x=0, y=0)],
        )
    ]

    summary = analyze_batch.build_search_summary_df([shallow, deep])
    macro_df = analyze_batch.build_macro_df([shallow, deep])
    report = analyze_batch.generate_report([shallow, deep])

    assert set(summary["policy_variant"]) == {"Search d2 b3 c5", "Search d3-6 b4 c6"}
    assert set(macro_df["policy_variant"]) == {"Search d2 b3 c5", "Search d3-6 b4 c6"}
    assert "decision_time_ms_avg_mean" in report
    assert "Search d2 b3 c5" in report
    assert "Search d3-6 b4 c6" in report


def test_policy_anomaly_summary_uses_mixed_baselines_and_starvation() -> None:
    random = _make_record(PolicyType.RANDOM, 41)
    greedy = _make_record(PolicyType.GREEDY, 41)
    search = _make_record(PolicyType.SEARCH, 41)
    random.record_id = 401
    greedy.record_id = 402
    search.record_id = 403
    random.final_score = 50
    greedy.final_score = 40
    search.final_score = -5
    random.turn_snapshots = [
        RecordTurnSnapshot(
            turn=1,
            score=50,
            food=0,
            wood=10,
            ore=4,
            science=3,
            city_count=1,
            building_count=2,
            tech_count=2,
            road_count=1,
            network_count=1,
            connected_city_count=0,
            isolated_city_count=1,
            largest_network_size=1,
            starving_network_count=1,
            legal_actions_count=4,
            score_breakdown={"total": 50},
        )
    ]
    search.decision_contexts = [
        RecordDecisionContext(
            turn=1,
            legal_actions_count=8,
            legal_build_city_count=4,
            legal_build_road_count=1,
            legal_build_building_count=1,
            legal_research_tech_count=1,
            legal_skip_count=1,
            chosen_action_type="build_city",
            search_mode="expand",
            search_depth=2,
            search_base_depth=2,
            search_max_depth=2,
            search_depth_reason="fixed",
            search_beam_width=3,
            search_candidate_limit=5,
            search_nodes_expanded=4,
            search_candidates_considered=16,
            search_leaf_count=12,
            search_best_value=100,
            search_best_sequence=[RecordSearchActionSnapshot(action_type="build_city", x=0, y=0)],
        )
    ]

    anomaly_df = analyze_batch.build_policy_anomaly_df([random, greedy, search])
    summary = analyze_batch.build_policy_anomaly_summary_df([random, greedy, search])
    matchup = analyze_batch.build_search_matchup_summary_from_macro_df(
        analyze_batch.build_macro_df([random, greedy, search])
    )
    report = analyze_batch.generate_report([random, greedy, search])

    rows = {row["policy_variant"]: row for row in anomaly_df.to_dict("records")}
    assert rows["Random"]["has_starvation"] == 1
    assert rows["Random"]["is_anomaly"] == 1
    assert rows["Greedy"]["is_greedy_under_random"] == 1
    assert rows["Search d2 b3 c5"]["is_search_under_random"] == 1
    assert rows["Search d2 b3 c5"]["is_search_under_greedy"] == 1
    assert set(summary["policy_variant"]) == {"Random", "Greedy", "Search d2 b3 c5"}
    assert int(matchup.iloc[0]["same_map_win_rate"]) == 0
    assert "search_under_greedy_count" in report
    assert "### 7.5 Search Same-Map Matchup Summary" in report
    assert "task7_acceptance_candidate" in report
    assert "Search d2 b3 c5" in report


def test_analyze_batch_reports_greedy_anomalies_with_turn_diagnostics() -> None:
    greedy = _make_record(PolicyType.GREEDY, 11)
    random = _make_record(PolicyType.RANDOM, 11)
    greedy.record_id = 101
    random.record_id = 102
    greedy.final_score = -15
    random.final_score = 40
    greedy.skip_count = 3
    greedy.action_log = [
        RecordActionLogEntry(turn=1, action_type="build_city", x=0, y=0),
        RecordActionLogEntry(turn=2, action_type="build_road", x=0, y=2),
        RecordActionLogEntry(turn=3, action_type="skip"),
        RecordActionLogEntry(turn=4, action_type="skip"),
        RecordActionLogEntry(turn=5, action_type="skip"),
    ]
    greedy.turn_snapshots = [
        RecordTurnSnapshot(
            turn=1,
            score=50,
            food=5,
            wood=10,
            ore=4,
            science=3,
            city_count=1,
            building_count=2,
            tech_count=2,
            road_count=1,
            network_count=1,
            connected_city_count=0,
            isolated_city_count=1,
            largest_network_size=1,
            starving_network_count=0,
            legal_actions_count=4,
            score_breakdown={"total": 50, "starving_network_penalty": 0},
        ),
        RecordTurnSnapshot(
            turn=2,
            score=40,
            food=-1,
            wood=10,
            ore=4,
            science=3,
            city_count=1,
            building_count=2,
            tech_count=2,
            road_count=1,
            network_count=1,
            connected_city_count=0,
            isolated_city_count=1,
            largest_network_size=1,
            starving_network_count=1,
            legal_actions_count=3,
            score_breakdown={"total": 40, "starving_network_penalty": 35},
        ),
        RecordTurnSnapshot(
            turn=3,
            score=35,
            food=-2,
            wood=9,
            ore=4,
            science=3,
            city_count=1,
            building_count=2,
            tech_count=2,
            road_count=1,
            network_count=1,
            connected_city_count=0,
            isolated_city_count=1,
            largest_network_size=1,
            starving_network_count=1,
            legal_actions_count=2,
            score_breakdown={"total": 35, "starving_network_penalty": 70},
        ),
        RecordTurnSnapshot(
            turn=4,
            score=20,
            food=0,
            wood=9,
            ore=4,
            science=3,
            city_count=1,
            building_count=2,
            tech_count=2,
            road_count=1,
            network_count=1,
            connected_city_count=0,
            isolated_city_count=1,
            largest_network_size=1,
            starving_network_count=1,
            legal_actions_count=1,
            score_breakdown={"total": 20, "starving_network_penalty": 105},
        ),
        RecordTurnSnapshot(
            turn=5,
            score=18,
            food=1,
            wood=9,
            ore=4,
            science=3,
            city_count=1,
            building_count=2,
            tech_count=2,
            road_count=1,
            network_count=1,
            connected_city_count=0,
            isolated_city_count=1,
            largest_network_size=1,
            starving_network_count=0,
            legal_actions_count=1,
            score_breakdown={"total": 18, "starving_network_penalty": 105},
        ),
    ]
    greedy.decision_contexts = [
        RecordDecisionContext(
            turn=1,
            legal_actions_count=4,
            legal_build_city_count=1,
            legal_build_road_count=1,
            legal_build_building_count=1,
            legal_research_tech_count=1,
            legal_skip_count=1,
            chosen_action_type="build_city",
            greedy_stage="expand",
            greedy_priority="city",
            greedy_best_delta_score=8,
            greedy_food_pressure=2,
        ),
        RecordDecisionContext(
            turn=2,
            legal_actions_count=3,
            legal_build_city_count=0,
            legal_build_road_count=1,
            legal_build_building_count=1,
            legal_research_tech_count=0,
            legal_skip_count=1,
            chosen_action_type="build_road",
            greedy_stage="rescue",
            greedy_priority="food_rescue",
            greedy_best_delta_score=-2,
            greedy_food_pressure=4,
        ),
        RecordDecisionContext(
            turn=3,
            legal_actions_count=2,
            legal_build_city_count=0,
            legal_build_road_count=0,
            legal_build_building_count=1,
            legal_research_tech_count=0,
            legal_skip_count=1,
            chosen_action_type="skip",
            greedy_stage="rescue",
            greedy_priority="skip",
            greedy_best_delta_score=-4,
            greedy_food_pressure=6,
        ),
        RecordDecisionContext(
            turn=4,
            legal_actions_count=1,
            legal_build_city_count=0,
            legal_build_road_count=0,
            legal_build_building_count=0,
            legal_research_tech_count=0,
            legal_skip_count=1,
            chosen_action_type="skip",
            greedy_stage="fill",
            greedy_priority="skip",
            greedy_best_delta_score=-8,
            greedy_food_pressure=3,
        ),
        RecordDecisionContext(
            turn=5,
            legal_actions_count=1,
            legal_build_city_count=0,
            legal_build_road_count=0,
            legal_build_building_count=0,
            legal_research_tech_count=0,
            legal_skip_count=1,
            chosen_action_type="skip",
            greedy_stage="expand_reopen",
            greedy_priority="skip",
            greedy_best_delta_score=-2,
            greedy_food_pressure=1,
            greedy_fill_reopen_reason="repeated_fill_skip",
        ),
    ]

    anomaly_df = analyze_batch.build_anomaly_df([greedy, random])
    report = analyze_batch.generate_report([greedy, random])

    assert len(anomaly_df) == 1
    row = anomaly_df.iloc[0]
    assert int(row["negative_food_turns"]) == 2
    assert int(row["starvation_turns"]) == 3
    assert int(row["longest_starvation_streak"]) == 3
    assert int(row["first_skip_turn"]) == 3
    assert int(row["fill_stage_turns"]) == 1
    assert int(row["first_stage_expand_reopen_turn"]) == 5
    assert int(row["expand_reopen_stage_turns"]) == 1
    assert int(row["rescue_stage_turns"]) == 2
    assert int(row["late_game_no_growth_streak"]) == 4
    assert int(row["score_drop_turns"]) == 4
    assert int(row["worst_score_drop"]) == -15
    assert float(row["tail_skip_ratio"]) == 0.6
    assert "## 10. Anomaly Summary" in report
    assert "## 11. Anomaly Cases" in report
    assert "score_gap=-55" in report
    assert "tail_skip_ratio=0.60" in report
    assert "first_skip=3" in report
    assert "first_reopen=5" in report
    assert "reopen_turns=1" in report
