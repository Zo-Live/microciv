from __future__ import annotations

from microciv.game.enums import OccupantType, TechType, TerrainType
from microciv.game.models import City, GameConfig, GameState, Network, ResourcePool, Tile
from microciv.game.networks import map_passable_coords_to_networks, recompute_networks


def test_recompute_networks_merges_connected_networks_through_river() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.RIVER),
        (2, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=2, network_id=5),
        2: City(city_id=2, coord=(2, 0), founded_turn=1, network_id=2),
    }
    state.networks = {
        5: Network(network_id=5, city_ids={1}, resources=ResourcePool(food=3), unlocked_techs={TechType.AGRICULTURE}),
        2: Network(network_id=2, city_ids={2}, resources=ResourcePool(wood=4), unlocked_techs={TechType.LOGGING}),
    }

    rebuilt = recompute_networks(state)

    assert sorted(rebuilt) == [2]
    assert rebuilt[2].city_ids == {1, 2}
    assert rebuilt[2].resources.food == 3
    assert rebuilt[2].resources.wood == 4
    assert rebuilt[2].unlocked_techs == {TechType.AGRICULTURE, TechType.LOGGING}
    assert state.cities[1].network_id == 2
    assert state.cities[2].network_id == 2


def test_map_passable_coords_to_networks_includes_roads_and_rivers() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.RIVER),
        (2, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.ROAD),
        (3, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
        2: City(city_id=2, coord=(3, 0), founded_turn=2, network_id=1),
    }
    state.networks = {1: Network(network_id=1, city_ids={1, 2})}

    mapping = map_passable_coords_to_networks(state)

    assert mapping[(0, 0)] == 1
    assert mapping[(1, 0)] == 1
    assert mapping[(2, 0)] == 1
    assert mapping[(3, 0)] == 1
