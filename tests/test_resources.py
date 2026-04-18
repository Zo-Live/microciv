from __future__ import annotations

from microciv.game.enums import OccupantType, ResourceType, TerrainType
from microciv.game.models import (
    BuildingCounts,
    City,
    GameConfig,
    GameState,
    Network,
    ResourcePool,
    Tile,
)
from microciv.game.networks import recompute_networks
from microciv.game.resources import (
    can_pay_river_road_cost,
    charge_river_road_cost,
    choose_river_road_payment_network,
    cover_reward_for_tile,
    recompute_resource_ownership,
    settle_resources,
)


def test_recompute_resource_ownership_uses_moore_neighborhood() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (2, 2): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 1): Tile(base_terrain=TerrainType.RIVER),
    }
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(farm=2),
        ),
        2: City(
            city_id=2,
            coord=(2, 2),
            founded_turn=2,
            network_id=2,
            buildings=BuildingCounts(library=2),
        ),
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1}),
        2: Network(network_id=2, city_ids={2}),
    }

    ownership = recompute_resource_ownership(state)

    assert ownership[(1, 1)][ResourceType.FOOD] == 1
    assert ownership[(1, 1)][ResourceType.SCIENCE] == 2


def test_settle_resources_applies_network_famine_snapshot_rules() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.FOREST),
        (3, 3): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (3, 2): Tile(base_terrain=TerrainType.FOREST),
    }
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(farm=1, lumber_mill=1),
        ),
        2: City(
            city_id=2,
            coord=(3, 3),
            founded_turn=2,
            network_id=2,
            buildings=BuildingCounts(lumber_mill=1),
        ),
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=0)),
        2: Network(network_id=2, city_ids={2}, resources=ResourcePool(food=5)),
    }

    summary = settle_resources(state)

    assert summary.famine_snapshot == {1: True, 2: False}
    assert state.networks[1].resources.food == -1
    assert state.networks[1].resources.wood == 0
    assert state.networks[2].resources.food == 1
    assert state.networks[2].resources.wood == 4
    assert summary.food_consumption == {1: 4, 2: 4}


def test_cover_reward_and_river_road_cost_helpers_follow_rules() -> None:
    river_reward = cover_reward_for_tile(TerrainType.RIVER)
    network = Network(network_id=1, resources=ResourcePool(wood=15, ore=10))

    assert river_reward.food == 8
    assert river_reward.science == 8
    assert can_pay_river_road_cost(network)
    assert charge_river_road_cost(network) is ResourceType.WOOD
    assert network.resources.wood == 0
    assert network.resources.ore == 10


def test_choose_river_road_payment_network_uses_founded_turn_then_coord() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 1): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (2, 1): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 1), founded_turn=2, network_id=1),
        2: City(city_id=2, coord=(2, 1), founded_turn=1, network_id=2),
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(wood=15)),
        2: Network(network_id=2, city_ids={2}, resources=ResourcePool(wood=15)),
    }
    recompute_networks(state)

    chosen_network_id = choose_river_road_payment_network(state, (1, 1))

    assert chosen_network_id == 2
