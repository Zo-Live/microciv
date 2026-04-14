from __future__ import annotations

from microciv.ai.greedy import GreedyPolicy
from microciv.ai.random_policy import RandomPolicy
from microciv.game.actions import Action, validate_action
from microciv.game.engine import GameEngine
from microciv.game.enums import ActionType, OccupantType, TechType, TerrainType
from microciv.game.mapgen import MapGenerator
from microciv.game.models import (
    BuildingCounts,
    City,
    GameConfig,
    GameState,
    Network,
    ResourcePool,
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
            resources=ResourcePool(food=1, wood=5),
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

            assert state.score >= 0


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
        building_count = sum(city.total_buildings for city in state.cities.values())
        assert state.score >= 500, f"seed={seed} score={state.score} too low"
        assert city_count > 1, f"seed={seed} only {city_count} city"
        assert building_count > 0, f"seed={seed} no buildings"
