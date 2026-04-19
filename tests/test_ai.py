from __future__ import annotations

from copy import deepcopy

from microciv.ai.greedy import GreedyPolicy
from microciv.ai.heuristics import city_site_score
from microciv.ai.policy import simulate_action
from microciv.ai.random_policy import RandomPolicy
from microciv.game.actions import Action, list_legal_actions, validate_action
from microciv.game.engine import GameEngine
from microciv.game.enums import ActionType, MapDifficulty, OccupantType, TechType, TerrainType
from microciv.game.mapgen import MapGenerator
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
from microciv.session import GameSession


def _run_policy_game(config: GameConfig, policy: GreedyPolicy | RandomPolicy) -> GameState:
    generated = MapGenerator().generate(config)
    state = GameState.empty(config)
    state.board = {
        coord: Tile(base_terrain=tile.base_terrain, occupant=tile.occupant)
        for coord, tile in generated.board.items()
    }
    engine = GameEngine(state)

    while not state.is_game_over:
        action = policy.select_action(state)
        validation = validate_action(state, action)
        assert validation.is_valid, (config.seed, action, validation.message)
        result = engine.apply_action(action)
        assert result.success, (config.seed, action, result.message)

    return state


def _snapshot_state(state: GameState) -> dict[str, object]:
    return {
        "turn": state.turn,
        "score": state.score,
        "message": state.message,
        "is_game_over": state.is_game_over,
        "board": {
            coord: (tile.base_terrain.value, tile.occupant.value)
            for coord, tile in sorted(state.board.items())
        },
        "cities": {
            city_id: {
                "coord": city.coord,
                "founded_turn": city.founded_turn,
                "network_id": city.network_id,
                "buildings": (
                    city.buildings.farm,
                    city.buildings.lumber_mill,
                    city.buildings.mine,
                    city.buildings.library,
                ),
            }
            for city_id, city in sorted(state.cities.items())
        },
        "roads": {
            road_id: {"coord": road.coord, "built_turn": road.built_turn}
            for road_id, road in sorted(state.roads.items())
        },
        "networks": {
            network_id: {
                "city_ids": sorted(network.city_ids),
                "resources": (
                    network.resources.food,
                    network.resources.wood,
                    network.resources.ore,
                    network.resources.science,
                ),
                "unlocked_techs": sorted(tech.value for tech in network.unlocked_techs),
                "consecutive_starving_turns": network.consecutive_starving_turns,
            }
            for network_id, network in sorted(state.networks.items())
        },
        "stats": {
            "build_city_count": state.stats.build_city_count,
            "build_road_count": state.stats.build_road_count,
            "build_farm_count": state.stats.build_farm_count,
            "build_lumber_mill_count": state.stats.build_lumber_mill_count,
            "build_mine_count": state.stats.build_mine_count,
            "build_library_count": state.stats.build_library_count,
            "research_agriculture_count": state.stats.research_agriculture_count,
            "research_logging_count": state.stats.research_logging_count,
            "research_mining_count": state.stats.research_mining_count,
            "research_education_count": state.stats.research_education_count,
            "skip_count": state.stats.skip_count,
        },
    }


def test_random_policy_returns_legal_action() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN),
        (1, 0): Tile(base_terrain=TerrainType.FOREST),
    }

    action = RandomPolicy(seed=3).select_action(state)

    assert validate_action(state, action).is_valid


def test_greedy_prefers_farm_when_network_is_in_food_danger() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {(0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY)}
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(),
        )
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=1, wood=10),
            unlocked_techs={TechType.AGRICULTURE},
        )
    }

    action = GreedyPolicy().select_action(state)

    assert action.action_type is ActionType.BUILD_BUILDING
    assert action.city_id == 1
    assert action.building_type is not None
    assert action.building_type.value == "farm"


def test_greedy_prefers_missing_unlocked_building_before_city_expansion() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN),
        (1, 1): Tile(base_terrain=TerrainType.FOREST),
    }
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(),
        )
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=30, wood=20, ore=10, science=12),
            unlocked_techs={TechType.AGRICULTURE},
        )
    }

    action = GreedyPolicy().select_action(state)

    assert action.action_type is ActionType.BUILD_BUILDING
    assert action.city_id == 1
    assert action.building_type is not None
    assert action.building_type.value == "farm"


def test_greedy_explain_decision_reports_rescue_stage() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {(0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY)}
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(),
        )
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=-3, wood=12, science=10),
            unlocked_techs={TechType.AGRICULTURE},
        )
    }

    context = GreedyPolicy().explain_decision(state)

    assert context["greedy_stage"] == "rescue"
    assert context["greedy_starving_networks"] == 1


def test_autoplay_records_turn_score_breakdown_and_greedy_budget_context() -> None:
    state = GameState.empty(GameConfig.for_autoplay())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (2, 2): Tile(base_terrain=TerrainType.FOREST),
        (1, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 2): Tile(base_terrain=TerrainType.PLAIN),
        (1, 3): Tile(base_terrain=TerrainType.PLAIN),
        (2, 1): Tile(base_terrain=TerrainType.PLAIN),
        (2, 3): Tile(base_terrain=TerrainType.PLAIN),
        (3, 1): Tile(base_terrain=TerrainType.PLAIN),
        (3, 2): Tile(base_terrain=TerrainType.RIVER),
        (3, 3): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool()),
    }
    session = GameSession(state=state, engine=GameEngine(state), policy=GreedyPolicy())

    session.step_autoplay()

    snapshot = state.stats.turn_snapshots[0]
    context = state.stats.decision_contexts[0]
    assert snapshot["score_breakdown"]["resource_score"] >= 0
    assert context["greedy_stage"]
    assert context["chosen_action_type"] == "build_city"
    assert context["greedy_best_site_budget"]["total_yield"] > 0
    assert "greedy_global_starving_delta" in context
    assert "greedy_best_future_network_budget" in context


def test_greedy_prefers_research_over_non_structural_road() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN),
        (1, 1): Tile(base_terrain=TerrainType.PLAIN),
        (2, 2): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=30, wood=20, ore=10, science=12),
        ),
    }

    action = GreedyPolicy().select_action(state)

    assert action.action_type is ActionType.RESEARCH_TECH
    assert action.city_id == 1
    assert action.tech_type is TechType.AGRICULTURE


def test_greedy_prefers_forest_city_when_wood_is_scarce() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (2, 2): Tile(base_terrain=TerrainType.FOREST),
        (1, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 2): Tile(base_terrain=TerrainType.PLAIN),
        (1, 3): Tile(base_terrain=TerrainType.PLAIN),
        (2, 1): Tile(base_terrain=TerrainType.PLAIN),
        (2, 3): Tile(base_terrain=TerrainType.PLAIN),
        (3, 1): Tile(base_terrain=TerrainType.PLAIN),
        (3, 2): Tile(base_terrain=TerrainType.RIVER),
        (3, 3): Tile(base_terrain=TerrainType.PLAIN),
        (6, 6): Tile(base_terrain=TerrainType.PLAIN),
        (5, 5): Tile(base_terrain=TerrainType.PLAIN),
        (5, 6): Tile(base_terrain=TerrainType.PLAIN),
        (5, 7): Tile(base_terrain=TerrainType.PLAIN),
        (6, 5): Tile(base_terrain=TerrainType.PLAIN),
        (6, 7): Tile(base_terrain=TerrainType.PLAIN),
        (7, 5): Tile(base_terrain=TerrainType.PLAIN),
        (7, 6): Tile(base_terrain=TerrainType.PLAIN),
        (7, 7): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool()),
    }

    action = GreedyPolicy().select_action(state)

    assert action == Action.build_city((2, 2))


def test_greedy_prefers_mountain_city_when_ore_is_scarce() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (2, 2): Tile(base_terrain=TerrainType.MOUNTAIN),
        (1, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 2): Tile(base_terrain=TerrainType.PLAIN),
        (1, 3): Tile(base_terrain=TerrainType.PLAIN),
        (2, 1): Tile(base_terrain=TerrainType.RIVER),
        (2, 3): Tile(base_terrain=TerrainType.PLAIN),
        (3, 1): Tile(base_terrain=TerrainType.PLAIN),
        (3, 2): Tile(base_terrain=TerrainType.PLAIN),
        (3, 3): Tile(base_terrain=TerrainType.PLAIN),
        (6, 6): Tile(base_terrain=TerrainType.PLAIN),
        (5, 5): Tile(base_terrain=TerrainType.PLAIN),
        (5, 6): Tile(base_terrain=TerrainType.PLAIN),
        (5, 7): Tile(base_terrain=TerrainType.PLAIN),
        (6, 5): Tile(base_terrain=TerrainType.PLAIN),
        (6, 7): Tile(base_terrain=TerrainType.PLAIN),
        (7, 5): Tile(base_terrain=TerrainType.PLAIN),
        (7, 6): Tile(base_terrain=TerrainType.PLAIN),
        (7, 7): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool()),
    }

    action = GreedyPolicy().select_action(state)

    assert action == Action.build_city((2, 2))


def test_city_site_score_prefers_resource_ring_interior_over_river_edge() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (4, 4): Tile(base_terrain=TerrainType.PLAIN),
        (3, 3): Tile(base_terrain=TerrainType.FOREST),
        (3, 4): Tile(base_terrain=TerrainType.FOREST),
        (3, 5): Tile(base_terrain=TerrainType.MOUNTAIN),
        (4, 3): Tile(base_terrain=TerrainType.FOREST),
        (4, 5): Tile(base_terrain=TerrainType.MOUNTAIN),
        (5, 3): Tile(base_terrain=TerrainType.FOREST),
        (5, 4): Tile(base_terrain=TerrainType.MOUNTAIN),
        (5, 5): Tile(base_terrain=TerrainType.FOREST),
        (8, 8): Tile(base_terrain=TerrainType.PLAIN),
        (7, 8): Tile(base_terrain=TerrainType.RIVER),
        (8, 7): Tile(base_terrain=TerrainType.PLAIN),
        (8, 9): Tile(base_terrain=TerrainType.PLAIN),
        (9, 8): Tile(base_terrain=TerrainType.PLAIN),
        (7, 7): Tile(base_terrain=TerrainType.FOREST),
        (7, 9): Tile(base_terrain=TerrainType.PLAIN),
        (9, 7): Tile(base_terrain=TerrainType.PLAIN),
        (9, 9): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=60, wood=0, ore=0)),
    }

    interior_score = city_site_score(state, (4, 4))
    river_edge_score = city_site_score(state, (8, 8))

    assert interior_score > river_edge_score


def test_greedy_prefers_connective_action_that_merges_networks() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (0, 2): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.ROAD),
        (0, 3): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (2, 0): Tile(base_terrain=TerrainType.PLAIN),
        (2, 1): Tile(base_terrain=TerrainType.PLAIN),
        (2, 2): Tile(base_terrain=TerrainType.FOREST),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
        2: City(city_id=2, coord=(0, 3), founded_turn=2, network_id=2),
    }
    state.roads = {1: Road(road_id=1, coord=(0, 2), built_turn=2)}
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=20, wood=20, science=0),
        ),
        2: Network(
            network_id=2,
            city_ids={2},
            resources=ResourcePool(food=20, wood=20, science=0),
        ),
    }

    action = GreedyPolicy().select_action(state)

    assert action.coord == (0, 1)
    assert action.action_type in {ActionType.BUILD_CITY, ActionType.BUILD_ROAD}


def test_greedy_rescue_prefers_structural_road_over_local_farm() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.RIVER),
        (0, 2): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.ROAD),
        (0, 3): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
    }
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(),
        ),
        2: City(
            city_id=2,
            coord=(0, 3),
            founded_turn=2,
            network_id=2,
            buildings=BuildingCounts(),
        ),
    }
    state.roads = {1: Road(road_id=1, coord=(0, 2), built_turn=2)}
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=24, wood=20),
            unlocked_techs={TechType.AGRICULTURE},
        ),
        2: Network(
            network_id=2,
            city_ids={2},
            resources=ResourcePool(food=-6),
        ),
    }

    action = GreedyPolicy().select_action(state)

    assert action == Action.build_road((0, 1))


def test_greedy_rescue_rejects_isolated_food_positive_city() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (4, 4): Tile(base_terrain=TerrainType.PLAIN),
        (3, 3): Tile(base_terrain=TerrainType.PLAIN),
        (3, 4): Tile(base_terrain=TerrainType.PLAIN),
        (3, 5): Tile(base_terrain=TerrainType.PLAIN),
        (4, 3): Tile(base_terrain=TerrainType.PLAIN),
        (4, 5): Tile(base_terrain=TerrainType.PLAIN),
        (5, 3): Tile(base_terrain=TerrainType.PLAIN),
        (5, 4): Tile(base_terrain=TerrainType.PLAIN),
        (5, 5): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(),
        )
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=-2, wood=20),
            unlocked_techs={TechType.AGRICULTURE},
        )
    }

    action = GreedyPolicy().select_action(state)

    assert action.action_type is ActionType.BUILD_BUILDING
    assert action.city_id == 1
    assert action.building_type is not None
    assert action.building_type.value == "farm"


def test_greedy_fill_skips_non_structural_road_on_saturated_network() -> None:
    state = GameState.empty(GameConfig.for_play(turn_limit=80))
    state.turn = 70
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.ROAD),
        (0, 2): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 1): Tile(base_terrain=TerrainType.RIVER),
    }
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(farm=1, lumber_mill=1, mine=1, library=1),
        ),
        2: City(
            city_id=2,
            coord=(0, 2),
            founded_turn=2,
            network_id=1,
            buildings=BuildingCounts(farm=1, lumber_mill=1, mine=1, library=1),
        ),
    }
    state.roads = {1: Road(road_id=1, coord=(0, 1), built_turn=1)}
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1, 2},
            resources=ResourcePool(food=40, wood=20, ore=12, science=100),
            unlocked_techs=set(TechType),
        )
    }

    action = GreedyPolicy().select_action(state)

    assert action.action_type is not ActionType.BUILD_ROAD


def test_random_policy_downweights_city_under_food_pressure() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (0, 2): Tile(base_terrain=TerrainType.PLAIN),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN),
        (2, 2): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(),
        )
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=-2, wood=10, science=12),
            unlocked_techs={TechType.AGRICULTURE},
        )
    }

    policy = RandomPolicy(seed=7)
    context = policy.explain_decision(state)
    weights = context["random_type_weights"]

    assert weights["build_building"] > weights["build_city"]
    assert weights["build_road"] > weights["build_city"]


def test_greedy_and_random_can_finish_full_games() -> None:
    seeds = [1, 2, 3]
    for policy_cls in (GreedyPolicy, RandomPolicy):
        for seed in seeds:
            config = GameConfig.for_play(seed=seed, turn_limit=30, map_size=12)
            policy = policy_cls(seed=seed) if policy_cls is RandomPolicy else policy_cls()
            state = _run_policy_game(config, policy)

            minimum_score = -900 if policy_cls is RandomPolicy else -50
            assert state.score >= minimum_score


def test_greedy_scores_reasonably_on_standard_settings() -> None:
    expected_min_scores = {
        1: 2500,
        2: 1800,
        3: 2600,
        4: 2200,
        5: 2800,
    }
    for seed, min_score in expected_min_scores.items():
        config = GameConfig.for_autoplay(seed=seed, turn_limit=80, map_size=16)
        state = _run_policy_game(config, GreedyPolicy())

        city_count = len(state.cities)
        road_count = len(state.roads)
        research_count = (
            state.stats.research_agriculture_count
            + state.stats.research_logging_count
            + state.stats.research_mining_count
            + state.stats.research_education_count
        )
        assert state.score >= min_score, f"seed={seed} score={state.score} too low"
        assert city_count > 1, f"seed={seed} only {city_count} city"
        assert road_count > 0 or research_count >= 3, (
            f"seed={seed} built no road and only researched {research_count} techs"
        )


def test_greedy_does_not_stall_on_large_hard_map() -> None:
    config = GameConfig.for_autoplay(
        seed=0,
        turn_limit=150,
        map_size=24,
        map_difficulty=MapDifficulty.HARD,
    )
    state = _run_policy_game(config, GreedyPolicy())

    assert state.score >= 4500, state.score
    assert sum(city.total_buildings for city in state.cities.values()) >= 60
    assert len(state.networks) <= 2
    assert len(state.roads) >= 5 or len(state.networks) == 1


def test_simulate_action_matches_deepcopy_engine_result() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (0, 2): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.ROAD),
        (0, 3): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
        2: City(city_id=2, coord=(0, 3), founded_turn=2, network_id=2),
    }
    state.roads = {1: Road(road_id=1, coord=(0, 2), built_turn=2)}
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=20, wood=20)),
        2: Network(network_id=2, city_ids={2}, resources=ResourcePool(food=20, wood=20)),
    }
    action = Action.build_road((0, 1))

    expected = deepcopy(state)
    result = GameEngine(expected).apply_action(action)
    assert result.success

    simulated = simulate_action(state, action)

    assert _snapshot_state(simulated) == _snapshot_state(expected)
    assert state.board[(0, 1)].occupant is OccupantType.NONE
    assert len(state.roads) == 1
    assert len(state.networks) == 2


def test_list_legal_actions_order_remains_stable_with_frontier_road_filter() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 0): Tile(base_terrain=TerrainType.FOREST),
        (1, 1): Tile(base_terrain=TerrainType.RIVER),
        (2, 0): Tile(base_terrain=TerrainType.MOUNTAIN),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
    }
    state.networks = {1: Network(network_id=1, city_ids={1}, resources=ResourcePool())}

    actions = list_legal_actions(state)

    assert actions == [
        Action.build_city((0, 1)),
        Action.build_city((1, 0)),
        Action.build_city((2, 0)),
        Action.build_road((0, 1)),
        Action.build_road((1, 0)),
        Action.skip(),
    ]


def test_random_policy_fixed_seed_output_stays_stable() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN),
        (1, 1): Tile(base_terrain=TerrainType.PLAIN),
        (2, 2): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=30, wood=20, ore=10, science=12),
        )
    }

    action = RandomPolicy(seed=3).select_action(state)

    assert action == Action.build_city((1, 0))


def test_greedy_explain_decision_stays_stable_for_network_merge() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (0, 2): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.ROAD),
        (0, 3): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (2, 0): Tile(base_terrain=TerrainType.PLAIN),
        (2, 1): Tile(base_terrain=TerrainType.PLAIN),
        (2, 2): Tile(base_terrain=TerrainType.FOREST),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
        2: City(city_id=2, coord=(0, 3), founded_turn=2, network_id=2),
    }
    state.roads = {1: Road(road_id=1, coord=(0, 2), built_turn=2)}
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=20, wood=20, science=0),
        ),
        2: Network(
            network_id=2,
            city_ids={2},
            resources=ResourcePool(food=20, wood=20, science=0),
        ),
    }

    policy = GreedyPolicy()
    action = policy.select_action(state)
    context = policy.explain_decision(state)

    assert action == Action.build_road((0, 1))
    assert context["greedy_stage"] == "consolidate"
    assert context["greedy_priority"] == "connective_road"
    assert context["greedy_best_action_type"] == "build_road"
    assert context["greedy_best_score"] == 679.2
    assert context["greedy_best_delta_score"] == 55
    assert context["greedy_food_pressure"] == -12
    assert context["greedy_starving_networks"] == 0
    assert context["greedy_connected_cities"] == 0
    assert context["greedy_total_food"] == 40
    assert context["greedy_network_count"] == 2
    assert context["greedy_global_starving_delta"] == 0
    assert context["greedy_global_network_delta"] == 1
    assert context["greedy_global_isolation_delta"] == 2
    assert context["greedy_rescue_effective"] is True
    assert context["greedy_best_site_budget"] == {
        "food_yield": 0,
        "wood_yield": 0,
        "ore_yield": 0,
        "science_yield": 0,
        "food_balance": -4,
        "total_yield": 0,
    }
    assert context["greedy_best_future_network_budget"] == {
        "network_id": 1,
        "city_count": 2,
        "food": 40,
        "wood": 40,
        "ore": 0,
        "science": 0,
        "pressure": -24,
    }
