from __future__ import annotations

from microciv.game.actions import Action, validate_action
from microciv.game.engine import GameEngine
from microciv.game.enums import BuildingType, OccupantType, TechType, TerrainType
from microciv.game.models import (
    City,
    GameConfig,
    GameState,
    Network,
    ResourcePool,
    Tile,
)


def test_validate_and_apply_invalid_city_build_does_not_advance_turn() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {(0, 0): Tile(base_terrain=TerrainType.RIVER)}
    engine = GameEngine(state)

    validation = validate_action(state, Action.build_city((0, 0)))
    result = engine.apply_action(Action.build_city((0, 0)))

    assert not validation.is_valid
    assert validation.message == "Cannot build city here"
    assert not result.success
    assert state.turn == 1
    assert not state.cities
    assert state.board[(0, 0)].occupant is OccupantType.NONE


def test_build_city_success_adds_cover_reward_and_same_turn_city_yield() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN),
        (1, 1): Tile(base_terrain=TerrainType.FOREST),
    }
    engine = GameEngine(state)

    result = engine.apply_action(Action.build_city((0, 0)))

    assert result.success
    assert state.turn == 2
    assert len(state.cities) == 1
    assert state.networks[1].resources.food == 4
    assert state.networks[1].resources.wood == 2
    assert state.score == 20
    assert state.stats.build_city_count == 1
    assert state.stats.turn_elapsed_ms_total >= 0


def test_build_road_success_adds_cover_reward_and_advances_turn() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.networks = {1: Network(network_id=1, city_ids={1})}
    engine = GameEngine(state)

    result = engine.apply_action(Action.build_road((1, 0)))

    assert result.success
    assert state.turn == 2
    assert state.board[(1, 0)].occupant is OccupantType.ROAD
    assert state.networks[1].resources.food == 4
    assert state.stats.build_road_count == 1


def test_invalid_river_road_without_resources_does_not_mutate_state() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.RIVER),
    }
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.networks = {1: Network(network_id=1, city_ids={1}, resources=ResourcePool())}
    engine = GameEngine(state)

    result = engine.apply_action(Action.build_road((1, 0)))

    assert not result.success
    assert result.message == "Not enough resources"
    assert state.turn == 1
    assert state.board[(1, 0)].occupant is OccupantType.NONE
    assert not state.roads


def test_build_building_succeeds_and_new_building_produces_same_turn() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {(0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY)}
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=4, wood=5),
            unlocked_techs={TechType.AGRICULTURE},
        )
    }
    engine = GameEngine(state)

    result = engine.apply_action(Action.build_building(1, BuildingType.FARM))

    assert result.success
    assert state.turn == 2
    assert state.cities[1].buildings.farm == 1
    assert state.networks[1].resources.food == 3
    assert state.networks[1].resources.wood == 0
    assert state.score == 65
    assert state.stats.build_farm_count == 1


def test_research_tech_succeeds_and_does_not_generate_immediate_resources() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {(0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY)}
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=4, science=6))
    }
    engine = GameEngine(state)

    result = engine.apply_action(Action.research_tech(1, TechType.AGRICULTURE))

    assert result.success
    assert state.turn == 2
    assert state.networks[1].resources.science == 0
    assert TechType.AGRICULTURE in state.networks[1].unlocked_techs
    assert state.networks[1].resources.food == 0
    assert state.stats.research_agriculture_count == 1


def test_skip_advances_turn_and_final_turn_enters_game_over() -> None:
    state = GameState.empty(GameConfig.for_play(turn_limit=30))
    state.turn = 30
    state.board = {(0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY)}
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.networks = {1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=4))}
    engine = GameEngine(state)

    result = engine.apply_action(Action.skip())

    assert result.success
    assert state.turn == 30
    assert state.is_game_over
    assert state.stats.skip_count == 1
