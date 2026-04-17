"""Score calculation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from microciv.constants import (
    NEGATIVE_RESOURCE_SCORE_DIVISORS,
    RESOURCE_SCORE_DIVISORS,
    SCORE_BUILDING_WEIGHT,
    SCORE_CITY_EARLY_WEIGHT,
    SCORE_CITY_LATE_WEIGHT,
    SCORE_CITY_MID_WEIGHT,
    SCORE_CONNECTED_CITY_WEIGHT,
    SCORE_FRAGMENTED_NETWORK_PENALTY,
    SCORE_RESOURCE_RING_DENSE_WEIGHT,
    SCORE_RESOURCE_RING_MIX_PLAIN_WEIGHT,
    SCORE_RESOURCE_RING_MIX_RESOURCE_ONLY_WEIGHT,
    SCORE_RESOURCE_RING_MIX_RIVER_WEIGHT,
    SCORE_RESOURCE_RING_PLAIN_WEIGHT,
    SCORE_RESOURCE_RING_RIVER_WEIGHT,
    SCORE_RESOURCE_RING_TILE_WEIGHT,
    SCORE_STARVING_NETWORK_PENALTY,
    SCORE_TECH_UTILIZATION_WEIGHT,
    SCORE_TECH_WEIGHT,
    SCORE_UNPRODUCTIVE_ROAD_PENALTY,
)
from microciv.game.enums import BuildingType, OccupantType, ResourceType, TechType, TerrainType
from microciv.game.models import GameState, ResourcePool
from microciv.game.networks import map_passable_coords_to_networks
from microciv.utils.grid import moore_neighbors


def calculate_score(state: GameState) -> int:
    """Calculate the current score for a game state."""
    return score_breakdown(state).total


@dataclass(slots=True, frozen=True)
class ScoreBreakdown:
    city_score: int
    connected_city_score: int
    resource_ring_score: int
    building_score: int
    tech_score: int
    tech_utilization_score: int
    food_score: int
    wood_score: int
    ore_score: int
    science_score: int
    excess_science_penalty: int
    starving_network_penalty: int
    fragmented_network_penalty: int
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
            + self.building_score
            + self.tech_score
            + self.tech_utilization_score
            + self.resource_score
            - self.excess_science_penalty
            - self.starving_network_penalty
            - self.fragmented_network_penalty
            - self.unproductive_road_penalty
        )


def score_breakdown(state: GameState) -> ScoreBreakdown:
    resources = total_resources(state)
    starvation_count = starving_network_count(state)
    fragmentation = max(len(state.networks) - 1, 0)
    return ScoreBreakdown(
        city_score=_city_score(city_count(state)),
        connected_city_score=connected_city_count(state) * SCORE_CONNECTED_CITY_WEIGHT,
        resource_ring_score=city_resource_ring_score(state),
        building_score=SCORE_BUILDING_WEIGHT * building_count(state),
        tech_score=SCORE_TECH_WEIGHT * tech_count(state),
        tech_utilization_score=tech_utilization_count(state) * SCORE_TECH_UTILIZATION_WEIGHT,
        food_score=_resource_stock_score(resources.food, ResourceType.FOOD),
        wood_score=_resource_stock_score(resources.wood, ResourceType.WOOD),
        ore_score=_resource_stock_score(resources.ore, ResourceType.ORE),
        science_score=_resource_stock_score(resources.science, ResourceType.SCIENCE),
        excess_science_penalty=max(0, resources.science - 60) // 4,
        starving_network_penalty=starvation_count * SCORE_STARVING_NETWORK_PENALTY,
        fragmented_network_penalty=fragmentation * SCORE_FRAGMENTED_NETWORK_PENALTY,
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


def tech_utilization_count(state: GameState) -> int:
    utilized = 0
    if _has_unlocked_building(state, TechType.AGRICULTURE, BuildingType.FARM):
        utilized += 1
    if _has_unlocked_building(state, TechType.LOGGING, BuildingType.LUMBER_MILL):
        utilized += 1
    if _has_unlocked_building(state, TechType.MINING, BuildingType.MINE):
        utilized += 1
    if _has_unlocked_building(state, TechType.EDUCATION, BuildingType.LIBRARY):
        utilized += 1
    return utilized


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


def _has_unlocked_building(
    state: GameState,
    tech_type: TechType,
    building_type: BuildingType,
) -> bool:
    unlocked = False
    building_present = False
    for network in state.networks.values():
        if tech_type in network.unlocked_techs:
            unlocked = True
            break
    if not unlocked:
        return False

    for city in state.cities.values():
        if city.buildings.for_type(building_type) > 0:
            building_present = True
            break
    return building_present
