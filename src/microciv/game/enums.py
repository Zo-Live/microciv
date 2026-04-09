"""Core enumerations for the game domain."""

from __future__ import annotations

from enum import StrEnum


class TerrainType(StrEnum):
    PLAIN = "plain"
    FOREST = "forest"
    MOUNTAIN = "mountain"
    RIVER = "river"
    WASTELAND = "wasteland"


class OccupantType(StrEnum):
    NONE = "none"
    CITY = "city"
    ROAD = "road"


class ResourceType(StrEnum):
    FOOD = "food"
    WOOD = "wood"
    ORE = "ore"
    SCIENCE = "science"


class BuildingType(StrEnum):
    FARM = "farm"
    LUMBER_MILL = "lumber_mill"
    MINE = "mine"
    LIBRARY = "library"


class TechType(StrEnum):
    AGRICULTURE = "agriculture"
    LOGGING = "logging"
    MINING = "mining"
    EDUCATION = "education"


class Mode(StrEnum):
    PLAY = "play"
    AUTOPLAY = "autoplay"


class PolicyType(StrEnum):
    NONE = "none"
    BASELINE = "baseline"
    EXPERT = "expert"
    CUSTOM = "custom"


class PlaybackMode(StrEnum):
    NONE = "none"
    NORMAL = "normal"
    SPEED = "speed"


class MapDifficulty(StrEnum):
    NORMAL = "normal"
    HARD = "hard"


class ActionType(StrEnum):
    BUILD_CITY = "build_city"
    BUILD_ROAD = "build_road"
    BUILD_BUILDING = "build_building"
    RESEARCH_TECH = "research_tech"
    SKIP = "skip"
