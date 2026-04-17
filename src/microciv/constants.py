"""Project-wide constants."""

from __future__ import annotations

from types import MappingProxyType

from microciv.game.enums import BuildingType, ResourceType, TechType, TerrainType

APP_NAME = "MicroCiv"
PROJECT_VERSION = "0.1.0"

MIN_MAP_SIZE = 12
DEFAULT_MAP_SIZE = 16
MAX_MAP_SIZE = 24

MIN_TURN_LIMIT = 30
DEFAULT_TURN_LIMIT = 80
MAX_TURN_LIMIT = 150

DEFAULT_SPEED_REFRESH_MS = 100
DEFAULT_SPEED_REFRESH_TURNS = 10
DEFAULT_AUTOPLAY_INTERVAL_MS = 300

BUILDING_LIMIT_PER_CITY = 6
FOOD_CONSUMPTION_PER_CITY = 4
RIVER_ROAD_WOOD_COST = 3
RIVER_ROAD_ORE_COST = 2

MAX_RECORDS = 10_000

RESOURCE_TYPES: tuple[ResourceType, ...] = (
    ResourceType.FOOD,
    ResourceType.WOOD,
    ResourceType.ORE,
    ResourceType.SCIENCE,
)

TERRAIN_YIELDS = MappingProxyType(
    {
        TerrainType.PLAIN: MappingProxyType({ResourceType.FOOD: 2}),
        TerrainType.FOREST: MappingProxyType({ResourceType.WOOD: 2}),
        TerrainType.MOUNTAIN: MappingProxyType({ResourceType.ORE: 2}),
        TerrainType.RIVER: MappingProxyType({ResourceType.FOOD: 1, ResourceType.SCIENCE: 1}),
        TerrainType.WASTELAND: MappingProxyType({}),
    }
)

COVER_REWARDS = MappingProxyType(
    {
        TerrainType.PLAIN: MappingProxyType({ResourceType.FOOD: 8}),
        TerrainType.FOREST: MappingProxyType({ResourceType.WOOD: 16}),
        TerrainType.MOUNTAIN: MappingProxyType({ResourceType.ORE: 16}),
        TerrainType.RIVER: MappingProxyType({ResourceType.FOOD: 8, ResourceType.SCIENCE: 8}),
        TerrainType.WASTELAND: MappingProxyType({}),
    }
)

CITY_CENTER_YIELDS = MappingProxyType(
    {
        TerrainType.PLAIN: MappingProxyType({}),
        TerrainType.FOREST: MappingProxyType({ResourceType.WOOD: 2}),
        TerrainType.MOUNTAIN: MappingProxyType({ResourceType.ORE: 2}),
        TerrainType.RIVER: MappingProxyType({}),
        TerrainType.WASTELAND: MappingProxyType({}),
    }
)

TECH_COSTS = MappingProxyType(
    {
        TechType.AGRICULTURE: 8,
        TechType.LOGGING: 18,
        TechType.MINING: 30,
        TechType.EDUCATION: 30,
    }
)

BUILDING_COSTS = MappingProxyType(
    {
        BuildingType.FARM: MappingProxyType({ResourceType.WOOD: 10}),
        BuildingType.LUMBER_MILL: MappingProxyType({ResourceType.WOOD: 10}),
        BuildingType.MINE: MappingProxyType({ResourceType.WOOD: 12, ResourceType.ORE: 8}),
        BuildingType.LIBRARY: MappingProxyType({ResourceType.WOOD: 12, ResourceType.ORE: 8}),
    }
)

BUILDING_YIELDS = MappingProxyType(
    {
        BuildingType.FARM: MappingProxyType({ResourceType.FOOD: 3}),
        BuildingType.LUMBER_MILL: MappingProxyType({ResourceType.WOOD: 2}),
        BuildingType.MINE: MappingProxyType({ResourceType.ORE: 2}),
        BuildingType.LIBRARY: MappingProxyType({ResourceType.SCIENCE: 2}),
    }
)

TECH_UNLOCKS = MappingProxyType(
    {
        TechType.AGRICULTURE: BuildingType.FARM,
        TechType.LOGGING: BuildingType.LUMBER_MILL,
        TechType.MINING: BuildingType.MINE,
        TechType.EDUCATION: BuildingType.LIBRARY,
    }
)

SCORE_CITY_EARLY_WEIGHT = 14
SCORE_CITY_MID_WEIGHT = 8
SCORE_CITY_LATE_WEIGHT = 3
SCORE_CONNECTED_CITY_WEIGHT = 6
SCORE_RESOURCE_RING_TILE_WEIGHT = 6
SCORE_RESOURCE_RING_RIVER_WEIGHT = 2
SCORE_RESOURCE_RING_PLAIN_WEIGHT = 1
SCORE_RESOURCE_RING_MIX_RIVER_WEIGHT = 5
SCORE_RESOURCE_RING_MIX_PLAIN_WEIGHT = 5
SCORE_RESOURCE_RING_MIX_RESOURCE_ONLY_WEIGHT = 9
SCORE_RESOURCE_RING_DENSE_WEIGHT = 4
SCORE_BUILDING_WEIGHT = 18
SCORE_TECH_WEIGHT = 120
SCORE_TECH_UTILIZATION_WEIGHT = 18
SCORE_STARVING_NETWORK_PENALTY = 140
SCORE_FRAGMENTED_NETWORK_PENALTY = 10
SCORE_UNPRODUCTIVE_ROAD_PENALTY = 4

RESOURCE_SCORE_DIVISORS = MappingProxyType(
    {
        ResourceType.FOOD: 16,
        ResourceType.WOOD: 5,
        ResourceType.ORE: 5,
        ResourceType.SCIENCE: 24,
    }
)

NEGATIVE_RESOURCE_SCORE_DIVISORS = MappingProxyType(
    {
        ResourceType.FOOD: 2,
        ResourceType.WOOD: 5,
        ResourceType.ORE: 5,
        ResourceType.SCIENCE: 24,
    }
)

BASELINE_TARGET_BUFFERS = MappingProxyType(
    {
        ResourceType.FOOD: 12,
        ResourceType.WOOD: 10,
        ResourceType.ORE: 8,
        ResourceType.SCIENCE: 10,
    }
)
