"""Score calculation helpers."""

from __future__ import annotations

from microciv.constants import (
    RESOURCE_SCORE_DIVISORS,
    SCORE_BUILDING_WEIGHT,
    SCORE_CITY_WEIGHT,
    SCORE_TECH_WEIGHT,
)
from microciv.game.enums import ResourceType
from microciv.game.models import GameState, ResourcePool


def calculate_score(state: GameState) -> int:
    """Calculate the current score for a game state."""
    resources = total_resources(state)
    return (
        SCORE_CITY_WEIGHT * city_count(state)
        + SCORE_BUILDING_WEIGHT * building_count(state)
        + SCORE_TECH_WEIGHT * tech_count(state)
        + resources.food // RESOURCE_SCORE_DIVISORS[ResourceType.FOOD]
        + resources.wood // RESOURCE_SCORE_DIVISORS[ResourceType.WOOD]
        + resources.ore // RESOURCE_SCORE_DIVISORS[ResourceType.ORE]
        + resources.science // RESOURCE_SCORE_DIVISORS[ResourceType.SCIENCE]
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
