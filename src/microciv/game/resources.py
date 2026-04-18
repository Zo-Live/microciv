"""Resource ownership and settlement calculations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from microciv.constants import (
    BUILDING_YIELDS,
    CITY_CENTER_YIELDS,
    COVER_REWARDS,
    FOOD_CONSUMPTION_PER_CITY,
    RIVER_ROAD_ORE_COST,
    RIVER_ROAD_WOOD_COST,
    TERRAIN_YIELDS,
)
from microciv.game.enums import BuildingType, OccupantType, ResourceType, TerrainType
from microciv.game.models import City, GameState, Network, ResourcePool, Tile
from microciv.game.networks import map_passable_coords_to_networks
from microciv.utils.grid import Coord, cardinal_neighbors, coord_sort_key, moore_neighbors

ResourceOwnership = dict[Coord, dict[ResourceType, int]]


RESOURCE_TO_BUILDING: dict[ResourceType, BuildingType] = {
    ResourceType.FOOD: BuildingType.FARM,
    ResourceType.WOOD: BuildingType.LUMBER_MILL,
    ResourceType.ORE: BuildingType.MINE,
    ResourceType.SCIENCE: BuildingType.LIBRARY,
}


@dataclass(slots=True)
class SettlementSummary:
    """The result of a single settlement pass."""

    ownership: ResourceOwnership
    famine_snapshot: dict[int, bool]
    terrain_yields: dict[int, ResourcePool]
    building_yields: dict[int, ResourcePool]
    food_consumption: dict[int, int]


def cover_reward_for_tile(tile: Tile | TerrainType) -> ResourcePool:
    """Return the one-time cover reward for building over a terrain."""
    terrain = tile.base_terrain if isinstance(tile, Tile) else tile
    reward = ResourcePool()
    for resource_type, amount in COVER_REWARDS[terrain].items():
        reward.add(resource_type, amount)
    return reward


def can_pay_river_road_cost(network: Network) -> bool:
    """Return whether a network can pay the extra cost for a river road."""
    return (
        network.resources.wood >= RIVER_ROAD_WOOD_COST
        or network.resources.ore >= RIVER_ROAD_ORE_COST
    )


def charge_river_road_cost(network: Network) -> ResourceType:
    """Spend the fixed river-road cost, preferring wood over ore."""
    if network.resources.wood >= RIVER_ROAD_WOOD_COST:
        network.resources.wood -= RIVER_ROAD_WOOD_COST
        return ResourceType.WOOD
    if network.resources.ore >= RIVER_ROAD_ORE_COST:
        network.resources.ore -= RIVER_ROAD_ORE_COST
        return ResourceType.ORE
    raise ValueError("Network cannot pay the river-road cost.")


def choose_river_road_payment_network(state: GameState, coord: Coord) -> int | None:
    """Choose the adjacent network that must pay a river-road surcharge."""
    network_coord_map = map_passable_coords_to_networks(state)
    candidate_network_ids = {
        network_coord_map[neighbor]
        for neighbor in cardinal_neighbors(coord)
        if neighbor in network_coord_map
        and can_pay_river_road_cost(state.networks[network_coord_map[neighbor]])
    }
    if not candidate_network_ids:
        return None

    return min(
        candidate_network_ids, key=lambda network_id: _network_priority_key(state, network_id)
    )


def recompute_resource_ownership(state: GameState) -> ResourceOwnership:
    """Recompute ownership for all resource-producing tiles on the board."""
    coord_to_city_id = {city.coord: city_id for city_id, city in state.cities.items()}
    ownership: ResourceOwnership = {}

    for coord in sorted(state.board, key=coord_sort_key):
        tile = state.board[coord]
        if tile.occupant is not OccupantType.NONE:
            continue
        if tile.base_terrain not in TERRAIN_YIELDS:
            continue

        nearby_cities = [
            state.cities[coord_to_city_id[neighbor]]
            for neighbor in moore_neighbors(coord)
            if neighbor in coord_to_city_id
        ]
        if not nearby_cities:
            continue

        if tile.base_terrain is TerrainType.PLAIN:
            ownership[coord] = {
                ResourceType.FOOD: _choose_owner(nearby_cities, ResourceType.FOOD).city_id
            }
        elif tile.base_terrain is TerrainType.FOREST:
            ownership[coord] = {
                ResourceType.WOOD: _choose_owner(nearby_cities, ResourceType.WOOD).city_id
            }
        elif tile.base_terrain is TerrainType.MOUNTAIN:
            ownership[coord] = {
                ResourceType.ORE: _choose_owner(nearby_cities, ResourceType.ORE).city_id
            }
        elif tile.base_terrain is TerrainType.RIVER:
            ownership[coord] = {
                ResourceType.FOOD: _choose_owner(nearby_cities, ResourceType.FOOD).city_id,
                ResourceType.SCIENCE: _choose_owner(nearby_cities, ResourceType.SCIENCE).city_id,
            }

    return ownership


def compute_famine_snapshot(state: GameState) -> dict[int, bool]:
    """Take the per-network famine snapshot used for the current settlement pass."""
    return {
        network_id: network.resources.food <= 0 for network_id, network in state.networks.items()
    }


def calculate_terrain_yields(
    state: GameState,
    ownership: ResourceOwnership,
    famine_snapshot: Mapping[int, bool],
) -> dict[int, ResourcePool]:
    """Calculate terrain-derived yields for each network."""
    yields = _empty_yield_map(state)
    for coord, assignments in ownership.items():
        tile = state.board[coord]
        for resource_type, city_id in assignments.items():
            network_id = state.cities[city_id].network_id
            if famine_snapshot.get(network_id, False) and resource_type is not ResourceType.FOOD:
                continue
            amount = TERRAIN_YIELDS[tile.base_terrain][resource_type]
            yields[network_id].add(resource_type, amount)

    for city in state.cities.values():
        network_id = city.network_id
        terrain = state.board[city.coord].base_terrain
        for resource_type, amount in CITY_CENTER_YIELDS[terrain].items():
            yields[network_id].add(resource_type, amount)
    return yields


def calculate_building_yields(
    state: GameState, famine_snapshot: Mapping[int, bool]
) -> dict[int, ResourcePool]:
    """Calculate building-derived yields for each network."""
    yields = _empty_yield_map(state)
    for city_id in state.sorted_city_ids():
        city = state.cities[city_id]
        network_id = city.network_id
        famine = famine_snapshot.get(network_id, False)
        for building_type in BuildingType:
            count = city.buildings.for_type(building_type)
            if count <= 0:
                continue
            for resource_type, amount in BUILDING_YIELDS[building_type].items():
                if famine and resource_type is not ResourceType.FOOD:
                    continue
                yields[network_id].add(resource_type, count * amount)
    return yields


def settle_resources(
    state: GameState,
    ownership: ResourceOwnership | None = None,
) -> SettlementSummary:
    """Apply terrain yields, building yields, and food consumption to all networks."""
    ownership = ownership if ownership is not None else recompute_resource_ownership(state)
    famine_snapshot = compute_famine_snapshot(state)
    terrain_yields = calculate_terrain_yields(state, ownership, famine_snapshot)
    building_yields = calculate_building_yields(state, famine_snapshot)

    for network_id, resource_pool in terrain_yields.items():
        state.networks[network_id].resources.merge(resource_pool)
    for network_id, resource_pool in building_yields.items():
        state.networks[network_id].resources.merge(resource_pool)

    food_consumption: dict[int, int] = {}
    for network_id, network in state.networks.items():
        consumption = FOOD_CONSUMPTION_PER_CITY * len(network.city_ids)
        network.resources.food -= consumption
        food_consumption[network_id] = consumption
        if network.resources.food <= 0:
            network.consecutive_starving_turns += 1
        else:
            network.consecutive_starving_turns = 0

    return SettlementSummary(
        ownership=ownership,
        famine_snapshot=famine_snapshot,
        terrain_yields=terrain_yields,
        building_yields=building_yields,
        food_consumption=food_consumption,
    )


def _choose_owner(cities: list[City], resource_type: ResourceType) -> City:
    building_type = RESOURCE_TO_BUILDING[resource_type]
    return min(
        cities,
        key=lambda city: (
            -city.buildings.for_type(building_type),
            city.founded_turn,
            coord_sort_key(city.coord),
            city.city_id,
        ),
    )


def _empty_yield_map(state: GameState) -> dict[int, ResourcePool]:
    return {network_id: ResourcePool() for network_id in state.networks}


def _network_priority_key(state: GameState, network_id: int) -> tuple[int, tuple[int, int], int]:
    city_ids = sorted(
        state.networks[network_id].city_ids,
        key=lambda city_id: (
            state.cities[city_id].founded_turn,
            coord_sort_key(state.cities[city_id].coord),
            city_id,
        ),
    )
    first_city = state.cities[city_ids[0]]
    return (first_city.founded_turn, coord_sort_key(first_city.coord), network_id)
