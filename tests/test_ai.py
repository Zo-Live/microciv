from __future__ import annotations

from microciv.ai.greedy import GreedyPolicy
from microciv.ai.heuristics import city_site_score
from microciv.ai.random_policy import RandomPolicy
from microciv.game.actions import Action, validate_action
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


def test_greedy_prefers_high_food_city_site() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 0): Tile(base_terrain=TerrainType.RIVER),
        (1, 1): Tile(base_terrain=TerrainType.FOREST),
        (3, 3): Tile(base_terrain=TerrainType.PLAIN),
        (4, 4): Tile(base_terrain=TerrainType.WASTELAND),
    }

    action = GreedyPolicy().select_action(state)

    assert action == Action.build_city((1, 1))


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
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=80, wood=0, ore=20)),
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
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=80, wood=20, ore=0)),
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


def test_greedy_prefers_connective_road_that_merges_networks() -> None:
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

    assert action == Action.build_road((0, 1))


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
            generated = MapGenerator().generate(config)
            state = GameState.empty(config)
            state.board = {
                coord: Tile(base_terrain=tile.base_terrain, occupant=tile.occupant)
                for coord, tile in generated.board.items()
            }
            engine = GameEngine(state)
            policy = policy_cls(seed=seed) if policy_cls is RandomPolicy else policy_cls()

            while not state.is_game_over:
                action = policy.select_action(state)
                validation = validate_action(state, action)
                assert validation.is_valid, (seed, action, validation.message)
                result = engine.apply_action(action)
                assert result.success, (seed, action, result.message)

            assert state.score >= -50


def test_greedy_scores_reasonably_on_standard_settings() -> None:
    for seed in range(1, 6):
        config = GameConfig.for_autoplay(seed=seed, turn_limit=80, map_size=16)
        generated = MapGenerator().generate(config)
        state = GameState.empty(config)
        state.board = {
            coord: Tile(base_terrain=tile.base_terrain, occupant=tile.occupant)
            for coord, tile in generated.board.items()
        }
        engine = GameEngine(state)
        policy = GreedyPolicy()

        while not state.is_game_over:
            action = policy.select_action(state)
            validation = validate_action(state, action)
            assert validation.is_valid, (seed, action, validation.message)
            result = engine.apply_action(action)
            assert result.success, (seed, action, result.message)

        city_count = len(state.cities)
        road_count = len(state.roads)
        research_count = (
            state.stats.research_agriculture_count
            + state.stats.research_logging_count
            + state.stats.research_mining_count
            + state.stats.research_education_count
        )
        assert state.score >= 350, f"seed={seed} score={state.score} too low"
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
    generated = MapGenerator().generate(config)
    state = GameState.empty(config)
    state.board = {
        coord: Tile(base_terrain=tile.base_terrain, occupant=tile.occupant)
        for coord, tile in generated.board.items()
    }
    engine = GameEngine(state)
    policy = GreedyPolicy()
    skip_count = 0

    while not state.is_game_over:
        action = policy.select_action(state)
        validation = validate_action(state, action)
        assert validation.is_valid, action
        result = engine.apply_action(action)
        assert result.success
        if action.action_type is ActionType.SKIP:
            skip_count += 1

    assert state.score >= 1500, state.score
    assert sum(city.total_buildings for city in state.cities.values()) >= 20
    assert skip_count <= 10
