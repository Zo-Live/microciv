"""Shared heuristic helpers for lightweight AI policies."""

from __future__ import annotations

from collections import Counter, defaultdict

from microciv.constants import BUILDING_LIMIT_PER_CITY, FOOD_CONSUMPTION_PER_CITY, TECH_COSTS
from microciv.game.actions import Action
from microciv.game.enums import (
    ActionType,
    BuildingType,
    OccupantType,
    ResourceType,
    TechType,
    TerrainType,
)
from microciv.game.models import City, GameState, Network
from microciv.game.networks import map_passable_coords_to_networks
from microciv.game.scoring import total_resources
from microciv.utils.grid import Coord, cardinal_neighbors, coord_sort_key, moore_neighbors

BUILDING_RESOURCE_TYPE: dict[BuildingType, ResourceType] = {
    BuildingType.FARM: ResourceType.FOOD,
    BuildingType.LUMBER_MILL: ResourceType.WOOD,
    BuildingType.MINE: ResourceType.ORE,
    BuildingType.LIBRARY: ResourceType.SCIENCE,
}

TECH_UNLOCK_PRIORITY: tuple[TechType, ...] = (
    TechType.AGRICULTURE,
    TechType.LOGGING,
    TechType.MINING,
    TechType.EDUCATION,
)


def partition_actions(actions: list[Action]) -> dict[ActionType, list[Action]]:
    grouped: dict[ActionType, list[Action]] = defaultdict(list)
    for action in actions:
        grouped[action.action_type].append(action)
    return grouped


def material_targets(state: GameState) -> tuple[int, int]:
    city_count = len(state.cities)
    return (30 + city_count, 18 + city_count)


def city_terrain_counts(state: GameState) -> Counter[TerrainType]:
    counts: Counter[TerrainType] = Counter()
    for city in state.cities.values():
        counts[state.board[city.coord].base_terrain] += 1
    return counts


def resource_ring_counts(state: GameState, coord: Coord) -> tuple[int, int, int, int, int]:
    forest_neighbors = 0
    mountain_neighbors = 0
    river_neighbors = 0
    plain_neighbors = 0
    occupied_neighbors = 0
    for neighbor in moore_neighbors(coord):
        tile = state.board.get(neighbor)
        if tile is None:
            continue
        if tile.occupant.value != "none":
            occupied_neighbors += 1
            continue
        if tile.base_terrain is TerrainType.FOREST:
            forest_neighbors += 1
        elif tile.base_terrain is TerrainType.MOUNTAIN:
            mountain_neighbors += 1
        elif tile.base_terrain is TerrainType.RIVER:
            river_neighbors += 1
        elif tile.base_terrain is TerrainType.PLAIN:
            plain_neighbors += 1
    return (
        forest_neighbors,
        mountain_neighbors,
        river_neighbors,
        plain_neighbors,
        occupied_neighbors,
    )


def resource_ring_bonus(state: GameState, coord: Coord) -> int:
    resources = total_resources(state)
    wood_target, ore_target = material_targets(state)
    food_pressure = max(0, len(state.cities) * FOOD_CONSUMPTION_PER_CITY * 2 - resources.food)
    science_need = max(0, 14 + (len(state.networks) * 3) - resources.science)
    (
        forest_neighbors,
        mountain_neighbors,
        river_neighbors,
        plain_neighbors,
        occupied_neighbors,
    ) = resource_ring_counts(state, coord)
    resource_neighbors = forest_neighbors + mountain_neighbors
    ring_neighbors = resource_neighbors + river_neighbors
    wood_shortage = max(0, wood_target - resources.wood)
    ore_shortage = max(0, ore_target - resources.ore)
    shortage_bonus = (
        forest_neighbors * min(wood_shortage, 18) * 4
        + mountain_neighbors * min(ore_shortage, 16) * 5
    )
    river_bonus = river_neighbors * (
        8 + min(food_pressure, 12) + science_need // 2
    )
    mix = min(forest_neighbors, mountain_neighbors)
    mixed_bonus = 0
    if resource_neighbors >= 4 and occupied_neighbors <= 4:
        if river_neighbors == 0 and plain_neighbors == 0:
            mixed_bonus = mix * 56
        elif river_neighbors == 0 and plain_neighbors > 0:
            mixed_bonus = mix * 36
        elif river_neighbors > 0:
            mixed_bonus = mix * 36
    dense_bonus = max(0, ring_neighbors - 3) * 48
    interior_bonus = 0
    terrain = state.board[coord].base_terrain
    if terrain is TerrainType.PLAIN and ring_neighbors >= 4:
        interior_bonus += 110 + ((ring_neighbors - 4) * 35)
    elif terrain in {TerrainType.FOREST, TerrainType.MOUNTAIN} and ring_neighbors >= 4:
        interior_bonus += 40 + ((ring_neighbors - 4) * 20)
    if terrain in {TerrainType.FOREST, TerrainType.MOUNTAIN} and river_neighbors > 0:
        interior_bonus += 40
    return (
        (resource_neighbors * 36)
        + (river_neighbors * 4)
        + (plain_neighbors * 6)
        + mixed_bonus
        + dense_bonus
        + shortage_bonus
        + river_bonus
        + interior_bonus
    )


def city_site_score(state: GameState, coord: Coord) -> int:
    resources = total_resources(state)
    wood_target, ore_target = material_targets(state)
    terrain_counts = city_terrain_counts(state)
    ring_bonus = resource_ring_bonus(state, coord)
    food_pressure = max(0, len(state.cities) * FOOD_CONSUMPTION_PER_CITY * 2 - resources.food)
    wood_shortage = max(0, wood_target - resources.wood)
    ore_shortage = max(0, ore_target - resources.ore)
    science_need = max(0, 10 + (len(state.networks) * 2) - resources.science)

    food = 0
    wood = 0
    ore = 0
    science = 0
    nearby_cities = 0
    center_tile = state.board[coord]
    if center_tile.base_terrain is TerrainType.PLAIN:
        food += 4
    elif center_tile.base_terrain is TerrainType.FOREST:
        wood += 4
    elif center_tile.base_terrain is TerrainType.MOUNTAIN:
        ore += 4
    for neighbor in moore_neighbors(coord):
        tile = state.board.get(neighbor)
        if tile is None:
            continue
        if tile.occupant.value != "none":
            if tile.occupant.value == "city":
                nearby_cities += 1
            continue
        if tile.base_terrain is TerrainType.PLAIN:
            food += 2
        elif tile.base_terrain is TerrainType.FOREST:
            wood += 2
        elif tile.base_terrain is TerrainType.MOUNTAIN:
            ore += 2
        elif tile.base_terrain is TerrainType.RIVER:
            food += 1
            science += 1

    passable_edges = 0
    road_frontier = 0
    river_edges = 0
    for neighbor in cardinal_neighbors(coord):
        tile = state.board.get(neighbor)
        if tile is None:
            continue
        if tile.base_terrain is TerrainType.RIVER:
            passable_edges += 2
            river_edges += 1
        if tile.occupant.value in {"road", "city"}:
            passable_edges += 3
        elif tile.occupant.value == "none":
            road_frontier += 1

    net_food = food - FOOD_CONSUMPTION_PER_CITY
    food_weight = 8 + min(food_pressure // 8, 8)
    wood_weight = 4 + min(wood_shortage // 4, 8)
    ore_weight = 4 + min(ore_shortage // 3, 10)
    science_weight = 6 + min(science_need // 6, 4)
    terrain_bias = 0
    if center_tile.base_terrain is TerrainType.FOREST:
        terrain_bias += wood_shortage * 16
        terrain_bias += max(0, 4 - terrain_counts[TerrainType.FOREST]) * 56
        terrain_bias += 36 if food >= FOOD_CONSUMPTION_PER_CITY + 1 else -28
    elif center_tile.base_terrain is TerrainType.MOUNTAIN:
        terrain_bias += ore_shortage * 18
        terrain_bias += max(0, 4 - terrain_counts[TerrainType.MOUNTAIN]) * 60
        terrain_bias += 36 if food >= FOOD_CONSUMPTION_PER_CITY + 1 else -30
    elif center_tile.base_terrain is TerrainType.PLAIN:
        if (
            resources.food >= len(state.cities) * FOOD_CONSUMPTION_PER_CITY * 4
            and (wood_shortage >= 8 or ore_shortage >= 6)
        ):
            terrain_bias -= min(140, max(wood_shortage * 5, ore_shortage * 6))
        if food_pressure >= 8:
            terrain_bias += min(120, food_pressure * 4)

    return (
        (food * food_weight)
        + (wood * wood_weight)
        + (ore * ore_weight)
        + (science * science_weight)
        + (max(net_food, -2) * 10)
        + (passable_edges * 6)
        + (river_edges * 12)
        + (road_frontier * 2)
        + ring_bonus
        + terrain_bias
        - (nearby_cities * 8)
    )


def city_expansion_score(state: GameState, coord: Coord) -> int:
    resources = total_resources(state)
    terrain_counts = city_terrain_counts(state)
    wood_target, ore_target = material_targets(state)
    tile = state.board[coord]
    ring_bonus = resource_ring_bonus(state, coord)
    shortage_boost = 0
    if tile.base_terrain is TerrainType.FOREST:
        shortage_boost += max(0, wood_target - resources.wood) * 28
        shortage_boost += max(0, 4 - terrain_counts[TerrainType.FOREST]) * 40
    elif tile.base_terrain is TerrainType.MOUNTAIN:
        shortage_boost += max(0, ore_target - resources.ore) * 30
        shortage_boost += max(0, 4 - terrain_counts[TerrainType.MOUNTAIN]) * 44
    elif tile.base_terrain is TerrainType.PLAIN:
        shortage_boost += max(0, len(state.cities) * FOOD_CONSUMPTION_PER_CITY - resources.food) * 8
        shortage_boost += max(0, 4 - terrain_counts[TerrainType.PLAIN]) * 36
        if resources.food >= len(state.cities) * FOOD_CONSUMPTION_PER_CITY * 4 and (
            resources.wood < wood_target or resources.ore < ore_target
        ):
            shortage_boost -= 140

    river_adjacent = sum(
        1
        for neighbor in cardinal_neighbors(coord)
        if (adjacent := state.board.get(neighbor)) is not None
        and adjacent.base_terrain is TerrainType.RIVER
    )
    connected_edges = sum(
        1
        for neighbor in cardinal_neighbors(coord)
        if (adjacent := state.board.get(neighbor)) is not None
        and adjacent.occupant.value in {"road", "city"}
    )
    return (
        city_site_score(state, coord)
        + (ring_bonus // 2)
        + shortage_boost
        + (river_adjacent * 24)
        + (connected_edges * 14)
    )


def road_site_score(state: GameState, coord: Coord) -> int:
    passable_network_map = map_passable_coords_to_networks(state)
    adjacent_network_ids = {
        passable_network_map[neighbor]
        for neighbor in cardinal_neighbors(coord)
        if neighbor in passable_network_map
    }
    adjacent_city_count = sum(
        1
        for neighbor in cardinal_neighbors(coord)
        if (tile := state.board.get(neighbor)) is not None and tile.occupant.value == "city"
    )
    adjacent_road_count = sum(
        1
        for neighbor in cardinal_neighbors(coord)
        if (tile := state.board.get(neighbor)) is not None and tile.occupant.value == "road"
    )
    resulting_degree = sum(
        1
        for neighbor in cardinal_neighbors(coord)
        if (tile := state.board.get(neighbor)) is not None
        and (
            tile.occupant.value in {"city", "road"}
            or tile.base_terrain is TerrainType.RIVER
        )
    )
    merge_sizes = sorted(
        (len(state.networks[network_id].city_ids) for network_id in adjacent_network_ids),
        reverse=True,
    )
    nearest_foreign_city = min(
        (
            abs(coord[0] - city.coord[0]) + abs(coord[1] - city.coord[1])
            for city in state.cities.values()
            if city.network_id not in adjacent_network_ids
        ),
        default=99,
    )
    merge_bonus = 0
    if len(adjacent_network_ids) >= 2:
        merge_bonus = 180 + (sum(merge_sizes) * 16)

    target_city_bonus = max(0, 8 - nearest_foreign_city) * 14
    adjacency_bonus = (adjacent_city_count * 18) + (adjacent_road_count * 6)
    river_bridge_bonus = 18 if state.board[coord].base_terrain is TerrainType.RIVER else 0

    resource_frontier = 0
    for neighbor in moore_neighbors(coord):
        tile = state.board.get(neighbor)
        if tile is not None and tile.occupant is OccupantType.NONE and tile.base_terrain in {
            TerrainType.FOREST, TerrainType.MOUNTAIN
        }:
            resource_frontier += 1
    frontier_bonus = resource_frontier * 22
    if resource_frontier >= 4:
        frontier_bonus += 90

    dead_end_penalty = 40 if resulting_degree <= 1 else 0
    sprawl_penalty = 0
    if len(adjacent_network_ids) <= 1 and nearest_foreign_city > 5:
        sprawl_penalty += 35
    if adjacent_city_count == 0 and adjacent_road_count <= 1:
        sprawl_penalty += 20
    if resource_frontier >= 4:
        sprawl_penalty = max(0, sprawl_penalty - 35)

    return (
        merge_bonus
        + target_city_bonus
        + adjacency_bonus
        + river_bridge_bonus
        + frontier_bonus
        - dead_end_penalty
        - sprawl_penalty
    )


def building_action_score(state: GameState, action: Action) -> int:
    assert action.city_id is not None
    assert action.building_type is not None
    city = state.cities[action.city_id]
    network = state.networks[city.network_id]
    resource_type = BUILDING_RESOURCE_TYPE[action.building_type]
    shortage = _resource_shortage(network, resource_type)
    same_building = city.buildings.for_type(action.building_type)
    available_slots = max(0, BUILDING_LIMIT_PER_CITY - city.total_buildings)
    score = 40 + shortage + (available_slots * 3) - (same_building * 5)
    if action.building_type is BuildingType.FARM:
        needs_food = (
            network.resources.food
            <= len(network.city_ids) * FOOD_CONSUMPTION_PER_CITY * 2
        )
        score += 35 if needs_food else 10
    elif action.building_type is BuildingType.LIBRARY:
        if len(network.unlocked_techs) < len(TechType):
            score += 22
        else:
            score += 35
    elif action.building_type is BuildingType.LUMBER_MILL:
        score += 24 if network.resources.wood < 28 else 8
    elif action.building_type is BuildingType.MINE:
        score += 24 if network.resources.ore < 18 else 8
    return score


def research_action_score(state: GameState, action: Action) -> int:
    assert action.city_id is not None
    assert action.tech_type is not None
    city = state.cities[action.city_id]
    network = state.networks[city.network_id]
    deficit_food = max(
        0,
        len(network.city_ids) * FOOD_CONSUMPTION_PER_CITY * 2 - network.resources.food,
    )
    score = 55
    if action.tech_type is TechType.AGRICULTURE:
        score += 40 + deficit_food
    elif action.tech_type is TechType.LOGGING:
        score += 36 if network.resources.wood < 24 else 18
    elif action.tech_type is TechType.MINING:
        score += 34 if network.resources.ore < 16 else 16
    elif action.tech_type is TechType.EDUCATION:
        score += 30 if len(network.unlocked_techs) < len(TechType) - 1 else 12
    score += max(0, network.resources.science - TECH_COSTS[action.tech_type])
    return score


def city_network_pressure(network: Network) -> int:
    return len(network.city_ids) * FOOD_CONSUMPTION_PER_CITY * 2 - network.resources.food


def state_food_pressure(state: GameState) -> int:
    return max((city_network_pressure(network) for network in state.networks.values()), default=0)


def coord_key(action: Action) -> tuple[int, int]:
    assert action.coord is not None
    return coord_sort_key(action.coord)


def city_key(city: City) -> tuple[int, tuple[int, int], int]:
    return (city.founded_turn, coord_sort_key(city.coord), city.city_id)


def _resource_shortage(network: Network, resource_type: ResourceType) -> int:
    if resource_type is ResourceType.FOOD:
        target = len(network.city_ids) * FOOD_CONSUMPTION_PER_CITY * 2
    elif resource_type is ResourceType.WOOD:
        target = 24
    elif resource_type is ResourceType.ORE:
        target = 16
    else:
        target = 14
    return max(0, target - network.resources.get(resource_type))
