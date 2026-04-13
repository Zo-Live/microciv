"""Project-wide constants."""

from __future__ import annotations

from types import MappingProxyType

from microciv.game.enums import BuildingType, ResourceType, TechType, TerrainType

APP_NAME = "MicroCiv"
PROJECT_VERSION = "0.1.0"

MIN_MAP_SIZE = 12
DEFAULT_MAP_SIZE = 18
MAX_MAP_SIZE = 24

MIN_TURN_LIMIT = 30
DEFAULT_TURN_LIMIT = 80
MAX_TURN_LIMIT = 150

DEFAULT_SPEED_REFRESH_MS = 100
DEFAULT_SPEED_REFRESH_TURNS = 10
DEFAULT_AUTOPLAY_INTERVAL_MS = 300

BUILDING_LIMIT_PER_CITY = 6
FOOD_CONSUMPTION_PER_CITY = 4
COVER_REWARD_AMOUNT = 8
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

TECH_COSTS = MappingProxyType(
    {
        TechType.AGRICULTURE: 6,
        TechType.LOGGING: 12,
        TechType.MINING: 20,
        TechType.EDUCATION: 20,
    }
)

BUILDING_COSTS = MappingProxyType(
    {
        BuildingType.FARM: MappingProxyType({ResourceType.WOOD: 5}),
        BuildingType.LUMBER_MILL: MappingProxyType({ResourceType.WOOD: 5}),
        BuildingType.MINE: MappingProxyType({ResourceType.WOOD: 6, ResourceType.ORE: 4}),
        BuildingType.LIBRARY: MappingProxyType({ResourceType.WOOD: 6, ResourceType.ORE: 4}),
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

SCORE_CITY_WEIGHT = 20
SCORE_BUILDING_WEIGHT = 15
SCORE_TECH_WEIGHT = 30

RESOURCE_SCORE_DIVISORS = MappingProxyType(
    {
        ResourceType.FOOD: 10,
        ResourceType.WOOD: 5,
        ResourceType.ORE: 5,
        ResourceType.SCIENCE: 20,
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
