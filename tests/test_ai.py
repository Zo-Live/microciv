from __future__ import annotations

from microciv.ai.baseline import BaselinePolicy
from microciv.ai.random_policy import RandomPolicy
from microciv.game.actions import validate_action
from microciv.game.engine import GameEngine
from microciv.game.enums import OccupantType, TerrainType
from microciv.game.mapgen import MapGenerator
from microciv.game.models import City, GameConfig, GameState, Network, ResourcePool, Tile


def test_random_policy_returns_legal_action() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN),
        (1, 0): Tile(base_terrain=TerrainType.FOREST),
    }

    action = RandomPolicy(seed=3).select_action(state)

    assert validate_action(state, action).is_valid


def test_baseline_prefers_food_rescue_road_that_merges_into_healthy_network() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN),
        (2, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (2, -1): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
        2: City(city_id=2, coord=(2, 0), founded_turn=2, network_id=2),
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=2)),
        2: Network(network_id=2, city_ids={2}, resources=ResourcePool(food=12)),
    }

    action = BaselinePolicy().select_action(state)

    assert action == action.build_road((1, 0))
    assert validate_action(state, action).is_valid


def test_baseline_prefers_highest_scoring_city_site() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (-1, 0): Tile(base_terrain=TerrainType.PLAIN),
        (0, -1): Tile(base_terrain=TerrainType.PLAIN),
        (0, 0): Tile(base_terrain=TerrainType.FOREST),
        (0, 1): Tile(base_terrain=TerrainType.RIVER),
        (1, -1): Tile(base_terrain=TerrainType.MOUNTAIN),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN),
        (3, 0): Tile(base_terrain=TerrainType.PLAIN),
        (3, 1): Tile(base_terrain=TerrainType.WASTELAND),
    }

    action = BaselinePolicy().select_action(state)

    assert action == action.build_city((0, 0))
    assert validate_action(state, action).is_valid


def test_baseline_beats_random_policy_on_fixed_seed_set() -> None:
    seeds = list(range(30))
    baseline_scores = [play_full_game(BaselinePolicy(), seed) for seed in seeds]
    random_scores = [play_full_game(RandomPolicy(seed=seed), seed) for seed in seeds]

    baseline_average = sum(baseline_scores) / len(baseline_scores)
    random_average = sum(random_scores) / len(random_scores)
    not_worse_count = sum(1 for baseline, random in zip(baseline_scores, random_scores, strict=True) if baseline >= random)

    assert baseline_average > random_average
    assert not_worse_count >= 20


def play_full_game(policy: BaselinePolicy | RandomPolicy, seed: int) -> int:
    config = GameConfig.for_play(seed=seed)
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
        assert validation.is_valid, (seed, action, validation.message)
        result = engine.apply_action(action)
        assert result.success, (seed, action, result.message)

    return state.score
