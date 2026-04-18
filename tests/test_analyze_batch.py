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
from microciv.records.models import RecordEntry

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
        policy_context={"greedy_priority": "skip", "greedy_best_action_type": "skip"},
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
    assert "## 5. Behavior Summary" in report
    assert "自动观察" not in report
    assert "building_utilization_score_mean" in report
    assert "river_access_score_mean" in report
    assert "tech_utilization_score" not in report
    assert score_df["river_access_score"].gt(0).all()
