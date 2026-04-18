"""Score calculation helpers."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from microciv.constants import (
    BUILDING_MISMATCH_CAPS,
    BUILDING_MISMATCH_STEPS,
    BUILDING_MISMATCH_THRESHOLDS,
    BUILDING_YIELDS,
    NEGATIVE_RESOURCE_SCORE_DIVISORS,
    RESOURCE_SCORE_DIVISORS,
    SCORE_BUILDING_WEIGHT,
    SCORE_CITY_COMPOSITION_CONNECTED_MIN,
    SCORE_CITY_COMPOSITION_PER_CITY,
    SCORE_CITY_COMPOSITION_TARGET_RATIO,
    SCORE_CITY_COMPOSITION_TOLERANCE,
    SCORE_CITY_EARLY_WEIGHT,
    SCORE_CITY_LATE_WEIGHT,
    SCORE_CITY_MID_WEIGHT,
    SCORE_CONNECTED_CITY_WEIGHT,
    SCORE_FRAGMENTED_NETWORK_PENALTY,
    SCORE_ISOLATED_CITY_PENALTY,
    SCORE_RESOURCE_RING_DENSE_WEIGHT,
    SCORE_RESOURCE_RING_MIX_PLAIN_WEIGHT,
    SCORE_RESOURCE_RING_MIX_RESOURCE_ONLY_WEIGHT,
    SCORE_RESOURCE_RING_MIX_RIVER_WEIGHT,
    SCORE_RESOURCE_RING_PLAIN_WEIGHT,
    SCORE_RESOURCE_RING_TILE_WEIGHT,
    SCORE_RIVER_ACCESS_BASE,
    SCORE_RIVER_ACCESS_DECAY,
    SCORE_RIVER_ACCESS_FLOOR,
    SCORE_STARVING_NETWORK_PENALTY,
    SCORE_TECH_WEIGHT,
    SCORE_UNPRODUCTIVE_ROAD_PENALTY,
    TECH_UNLOCKS,
)
from microciv.game.enums import BuildingType, OccupantType, ResourceType, TerrainType
from microciv.game.models import GameState, Network, ResourcePool
from microciv.game.networks import map_passable_coords_to_networks
from microciv.utils.grid import Coord, cardinal_neighbors, moore_neighbors


@dataclass(slots=True, frozen=True)
class ScoreBreakdown:
    city_score: int
    connected_city_score: int
    resource_ring_score: int
    river_access_score: int
    city_composition_bonus: int
    building_score: int
    tech_score: int
    building_utilization_score: int
    food_score: int
    wood_score: int
    ore_score: int
    science_score: int
    excess_science_penalty: int
    building_mismatch_penalty: int
    starving_network_penalty: int
    fragmented_network_penalty: int
    isolated_city_penalty: int
    unproductive_road_penalty: int

    @property
    def resource_score(self) -> int:
        return self.food_score + self.wood_score + self.ore_score + self.science_score

    @property
    def total(self) -> int:
        return (
            self.city_score
            + self.connected_city_score
            + self.resource_ring_score
            + self.river_access_score
            + self.city_composition_bonus
            + self.building_score
            + self.tech_score
            + self.building_utilization_score
            + self.resource_score
            - self.excess_science_penalty
            - self.building_mismatch_penalty
            - self.starving_network_penalty
            - self.fragmented_network_penalty
            - self.isolated_city_penalty
            - self.unproductive_road_penalty
        )


def calculate_score(state: GameState) -> int:
    """Calculate the current score for a game state."""
    return score_breakdown(state).total


def score_breakdown(state: GameState) -> ScoreBreakdown:
    resources = total_resources(state)
    starvation_count = starving_network_count(state)
    fragmentation = max(len(state.networks) - 1, 0)
    return ScoreBreakdown(
        city_score=_city_score(city_count(state)),
        connected_city_score=connected_city_count(state) * SCORE_CONNECTED_CITY_WEIGHT,
        resource_ring_score=city_resource_ring_score(state),
        river_access_score=river_access_score(state),
        city_composition_bonus=city_composition_bonus(state),
        building_score=SCORE_BUILDING_WEIGHT * building_count(state),
        tech_score=SCORE_TECH_WEIGHT * tech_count(state),
        building_utilization_score=building_utilization_score(state),
        food_score=_resource_stock_score(resources.food, ResourceType.FOOD),
        wood_score=_resource_stock_score(resources.wood, ResourceType.WOOD),
        ore_score=_resource_stock_score(resources.ore, ResourceType.ORE),
        science_score=_resource_stock_score(resources.science, ResourceType.SCIENCE),
        excess_science_penalty=max(0, resources.science - 60) // 4,
        building_mismatch_penalty=building_mismatch_penalty(state),
        starving_network_penalty=starvation_count * SCORE_STARVING_NETWORK_PENALTY,
        fragmented_network_penalty=fragmentation * SCORE_FRAGMENTED_NETWORK_PENALTY,
        isolated_city_penalty=isolated_city_count(state) * SCORE_ISOLATED_CITY_PENALTY,
        unproductive_road_penalty=(
            unproductive_road_count(state) * SCORE_UNPRODUCTIVE_ROAD_PENALTY
        ),
    )


def city_count(state: GameState) -> int:
    """Return the total number of cities."""
    return len(state.cities)


def building_count(state: GameState) -> int:
    """Return the total number of built buildings across all cities."""
    return sum(city.total_buildings for city in state.cities.values())


def tech_count(state: GameState) -> int:
    """Return the total number of unique unlocked technologies across the civilization."""
    unlocked = set()
    for network in state.networks.values():
        unlocked.update(network.unlocked_techs)
    return len(unlocked)


def total_resources(state: GameState) -> ResourcePool:
    """Return the sum of resources across all networks."""
    total = ResourcePool()
    for network in state.networks.values():
        total.merge(network.resources)
    return total


def connected_city_count(state: GameState) -> int:
    return sum(
        len(network.city_ids)
        for network in state.networks.values()
        if len(network.city_ids) >= 2
    )


def city_resource_ring_score(state: GameState) -> int:
    score = 0
    for city in state.cities.values():
        forest_neighbors = 0
        mountain_neighbors = 0
        river_neighbors = 0
        plain_neighbors = 0
        occupied_neighbors = 0
        for neighbor in moore_neighbors(city.coord):
            tile = state.board.get(neighbor)
            if tile is None:
                continue
            if tile.occupant is not OccupantType.NONE:
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
        resource_neighbors = forest_neighbors + mountain_neighbors
        ring_neighbors = resource_neighbors + river_neighbors
        score += resource_neighbors * SCORE_RESOURCE_RING_TILE_WEIGHT
        score += plain_neighbors * SCORE_RESOURCE_RING_PLAIN_WEIGHT
        if resource_neighbors >= 4 and occupied_neighbors <= 4:
            mix = min(forest_neighbors, mountain_neighbors)
            if river_neighbors == 0 and plain_neighbors == 0:
                score += mix * SCORE_RESOURCE_RING_MIX_RESOURCE_ONLY_WEIGHT
            elif river_neighbors == 0 and plain_neighbors > 0:
                score += mix * SCORE_RESOURCE_RING_MIX_PLAIN_WEIGHT
            elif river_neighbors > 0:
                score += mix * SCORE_RESOURCE_RING_MIX_RIVER_WEIGHT
        score += max(0, ring_neighbors - 3) * SCORE_RESOURCE_RING_DENSE_WEIGHT
    return score


def river_access_score(state: GameState) -> int:
    component_map = _river_component_map(state)
    if not component_map:
        return 0

    adjacency_counts: dict[int, set[int]] = defaultdict(set)
    for city_id, city in state.cities.items():
        adjacent_components = {
            component_map[neighbor]
            for neighbor in cardinal_neighbors(city.coord)
            if neighbor in component_map
        }
        for component_id in adjacent_components:
            adjacency_counts[component_id].add(city_id)

    return sum(
        _river_component_access_score(len(adjacent_city_ids))
        for adjacent_city_ids in adjacency_counts.values()
    )


def city_composition_bonus(state: GameState) -> int:
    connected_cities = [
        city
        for city in state.cities.values()
        if len(state.networks[city.network_id].city_ids) >= 2
    ]
    connected_count = len(connected_cities)
    if connected_count < SCORE_CITY_COMPOSITION_CONNECTED_MIN:
        return 0

    inland_count = sum(1 for city in connected_cities if not _is_river_adjacent(state, city.coord))
    inland_ratio = inland_count / connected_count
    distance = abs(inland_ratio - SCORE_CITY_COMPOSITION_TARGET_RATIO)
    if distance >= SCORE_CITY_COMPOSITION_TOLERANCE:
        return 0

    scale = 1.0 - (distance / SCORE_CITY_COMPOSITION_TOLERANCE)
    return int(round(SCORE_CITY_COMPOSITION_PER_CITY * connected_count * scale))


def starving_network_count(state: GameState) -> int:
    return sum(1 for network in state.networks.values() if network.resources.food <= 0)


def largest_network_size(state: GameState) -> int:
    return max((len(network.city_ids) for network in state.networks.values()), default=0)


def isolated_city_count(state: GameState) -> int:
    return sum(
        len(network.city_ids)
        for network in state.networks.values()
        if len(network.city_ids) == 1
    )


def building_utilization_score(state: GameState) -> int:
    total = 0
    for network in state.networks.values():
        for tech_type in network.unlocked_techs:
            building_type = TECH_UNLOCKS[tech_type]
            total += _building_utilization_value(
                _network_building_count(state, network, building_type)
            )
    return total


def building_mismatch_penalty(state: GameState) -> int:
    total = 0
    for network in state.networks.values():
        for tech_type in network.unlocked_techs:
            building_type = TECH_UNLOCKS[tech_type]
            resource_type = _building_resource_type(building_type)
            building_total = _network_building_count(state, network, building_type)
            resource_total = network.resources.get(resource_type)
            threshold = BUILDING_MISMATCH_THRESHOLDS[resource_type]
            step = BUILDING_MISMATCH_STEPS[resource_type]
            cap = BUILDING_MISMATCH_CAPS[resource_type]
            excess_units = max(0, (resource_total - threshold) // step)
            mismatch = max(0, excess_units - building_total)
            total += min(cap, 6 * mismatch)
    return total


def unproductive_road_count(state: GameState) -> int:
    if not state.roads or not state.networks:
        return 0

    passable_map = map_passable_coords_to_networks(state)
    count = 0
    for road in state.roads.values():
        network_id = passable_map.get(road.coord)
        if network_id is None:
            continue
        if len(state.networks[network_id].city_ids) <= 1:
            count += 1
    return count


def _city_score(count: int) -> int:
    early = min(count, 8)
    mid = min(max(count - 8, 0), 8)
    late = max(count - 16, 0)
    return (
        early * SCORE_CITY_EARLY_WEIGHT
        + mid * SCORE_CITY_MID_WEIGHT
        + late * SCORE_CITY_LATE_WEIGHT
    )


def _resource_stock_score(amount: int, resource_type: ResourceType) -> int:
    if amount < 0:
        divisor = NEGATIVE_RESOURCE_SCORE_DIVISORS[resource_type]
        return -((abs(amount) + divisor - 1) // divisor)

    divisor = RESOURCE_SCORE_DIVISORS[resource_type]
    primary_cap = divisor * 8
    primary_score = min(amount, primary_cap) // divisor
    overflow = max(amount - primary_cap, 0)
    return primary_score + (overflow // (divisor * 4))


def _river_component_map(state: GameState) -> dict[Coord, int]:
    component_map: dict[Coord, int] = {}
    next_component_id = 1
    for coord, tile in state.board.items():
        if tile.base_terrain is not TerrainType.RIVER or coord in component_map:
            continue
        queue = deque([coord])
        component_map[coord] = next_component_id
        while queue:
            current = queue.popleft()
            for neighbor in cardinal_neighbors(current):
                if neighbor in component_map:
                    continue
                adjacent = state.board.get(neighbor)
                if adjacent is None or adjacent.base_terrain is not TerrainType.RIVER:
                    continue
                component_map[neighbor] = next_component_id
                queue.append(neighbor)
        next_component_id += 1
    return component_map


def _river_component_access_score(adjacent_city_count: int) -> int:
    total = 0
    for city_index in range(1, adjacent_city_count + 1):
        if city_index <= 2:
            total += SCORE_RIVER_ACCESS_BASE
            continue
        total += max(
            SCORE_RIVER_ACCESS_FLOOR,
            SCORE_RIVER_ACCESS_BASE - SCORE_RIVER_ACCESS_DECAY * (city_index - 2),
        )
    return total


def _is_river_adjacent(state: GameState, coord: Coord) -> bool:
    return any(
        (tile := state.board.get(neighbor)) is not None
        and tile.base_terrain is TerrainType.RIVER
        for neighbor in cardinal_neighbors(coord)
    )


def _building_utilization_value(building_count: int) -> int:
    if building_count <= 0:
        return -24
    if building_count == 1:
        return 4
    if building_count == 2:
        return 12
    if building_count == 3:
        return 18
    if building_count == 4:
        return 22
    return min(28, 22 + (2 * (building_count - 4)))


def _network_building_count(
    state: GameState,
    network: Network,
    building_type: BuildingType,
) -> int:
    return sum(
        state.cities[city_id].buildings.for_type(building_type)
        for city_id in network.city_ids
    )


def _building_resource_type(building_type: BuildingType) -> ResourceType:
    resource_yields = BUILDING_YIELDS[building_type]
    return next(iter(resource_yields))
