"""Primary data models for game state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from microciv.constants import (
    BUILDING_LIMIT_PER_CITY,
    DEFAULT_MAP_SIZE,
    DEFAULT_TURN_LIMIT,
    MAX_MAP_SIZE,
    MAX_TURN_LIMIT,
    MIN_MAP_SIZE,
    MIN_TURN_LIMIT,
    RESOURCE_TYPES,
)
from microciv.game.enums import (
    BuildingType,
    MapDifficulty,
    Mode,
    OccupantType,
    PlaybackMode,
    PolicyType,
    ResourceType,
    TechType,
    TerrainType,
)
from microciv.utils.grid import Coord, coord_sort_key


@dataclass(slots=True)
class Tile:
    base_terrain: TerrainType
    occupant: OccupantType = OccupantType.NONE


@dataclass(slots=True)
class ResourcePool:
    food: int = 0
    wood: int = 0
    ore: int = 0
    science: int = 0

    def get(self, resource_type: ResourceType) -> int:
        if resource_type is ResourceType.FOOD:
            return self.food
        if resource_type is ResourceType.WOOD:
            return self.wood
        if resource_type is ResourceType.ORE:
            return self.ore
        if resource_type is ResourceType.SCIENCE:
            return self.science
        raise ValueError(f"Unsupported resource type: {resource_type}")

    def set(self, resource_type: ResourceType, amount: int) -> None:
        if resource_type is ResourceType.FOOD:
            self.food = amount
            return
        if resource_type is ResourceType.WOOD:
            self.wood = amount
            return
        if resource_type is ResourceType.ORE:
            self.ore = amount
            return
        if resource_type is ResourceType.SCIENCE:
            self.science = amount
            return
        raise ValueError(f"Unsupported resource type: {resource_type}")

    def add(self, resource_type: ResourceType, amount: int) -> None:
        self.set(resource_type, self.get(resource_type) + amount)

    def add_many(self, values: Mapping[ResourceType, int]) -> None:
        for resource_type, amount in values.items():
            self.add(resource_type, amount)

    def can_afford(self, costs: Mapping[ResourceType, int]) -> bool:
        return all(self.get(resource_type) >= amount for resource_type, amount in costs.items())

    def spend(self, costs: Mapping[ResourceType, int]) -> None:
        if not self.can_afford(costs):
            raise ValueError("Insufficient resources to spend the requested cost.")
        for resource_type, amount in costs.items():
            self.add(resource_type, -amount)

    def merge(self, other: ResourcePool) -> None:
        for resource_type in RESOURCE_TYPES:
            self.add(resource_type, other.get(resource_type))

    def as_dict(self) -> dict[ResourceType, int]:
        return {resource_type: self.get(resource_type) for resource_type in RESOURCE_TYPES}


@dataclass(slots=True)
class BuildingCounts:
    farm: int = 0
    lumber_mill: int = 0
    mine: int = 0
    library: int = 0

    @property
    def total(self) -> int:
        return self.farm + self.lumber_mill + self.mine + self.library

    def for_type(self, building_type: BuildingType) -> int:
        if building_type is BuildingType.FARM:
            return self.farm
        if building_type is BuildingType.LUMBER_MILL:
            return self.lumber_mill
        if building_type is BuildingType.MINE:
            return self.mine
        if building_type is BuildingType.LIBRARY:
            return self.library
        raise ValueError(f"Unsupported building type: {building_type}")

    def add(self, building_type: BuildingType, amount: int = 1) -> None:
        if building_type is BuildingType.FARM:
            self.farm += amount
            return
        if building_type is BuildingType.LUMBER_MILL:
            self.lumber_mill += amount
            return
        if building_type is BuildingType.MINE:
            self.mine += amount
            return
        if building_type is BuildingType.LIBRARY:
            self.library += amount
            return
        raise ValueError(f"Unsupported building type: {building_type}")

    def can_add_more(self) -> bool:
        return self.total < BUILDING_LIMIT_PER_CITY


@dataclass(slots=True)
class City:
    city_id: int
    coord: Coord
    founded_turn: int
    network_id: int
    buildings: BuildingCounts = field(default_factory=BuildingCounts)

    def __post_init__(self) -> None:
        if self.city_id < 1:
            raise ValueError("city_id must be positive.")
        if self.founded_turn < 1:
            raise ValueError("founded_turn must be at least 1.")

    @property
    def total_buildings(self) -> int:
        return self.buildings.total


@dataclass(slots=True)
class Road:
    road_id: int
    coord: Coord
    built_turn: int

    def __post_init__(self) -> None:
        if self.road_id < 1:
            raise ValueError("road_id must be positive.")
        if self.built_turn < 1:
            raise ValueError("built_turn must be at least 1.")


@dataclass(slots=True)
class Network:
    network_id: int
    city_ids: set[int] = field(default_factory=set)
    resources: ResourcePool = field(default_factory=ResourcePool)
    unlocked_techs: set[TechType] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.network_id < 1:
            raise ValueError("network_id must be positive.")

    def merge_from(self, other: Network) -> None:
        self.city_ids.update(other.city_ids)
        self.resources.merge(other.resources)
        self.unlocked_techs.update(other.unlocked_techs)


@dataclass(slots=True)
class SelectionState:
    selected_coord: Coord | None = None
    selected_city_id: int | None = None

    def clear(self) -> None:
        self.selected_coord = None
        self.selected_city_id = None


@dataclass(slots=True)
class Stats:
    build_city_count: int = 0
    build_road_count: int = 0
    build_farm_count: int = 0
    build_lumber_mill_count: int = 0
    build_mine_count: int = 0
    build_library_count: int = 0
    research_agriculture_count: int = 0
    research_logging_count: int = 0
    research_mining_count: int = 0
    research_education_count: int = 0
    skip_count: int = 0
    decision_count: int = 0
    decision_time_ms_total: float = 0.0
    decision_time_ms_avg: float = 0.0
    decision_time_ms_max: float = 0.0
    turn_elapsed_ms_total: float = 0.0
    turn_elapsed_ms_avg: float = 0.0
    turn_elapsed_ms_max: float = 0.0
    session_elapsed_ms: float = 0.0

    def record_decision_time(self, duration_ms: float) -> None:
        if duration_ms < 0:
            raise ValueError("duration_ms must be non-negative.")
        self.decision_count += 1
        self.decision_time_ms_total += duration_ms
        self.decision_time_ms_max = max(self.decision_time_ms_max, duration_ms)
        self.decision_time_ms_avg = self.decision_time_ms_total / self.decision_count

    def record_turn_time(self, duration_ms: float) -> None:
        if duration_ms < 0:
            raise ValueError("duration_ms must be non-negative.")
        turn_count = (
            self.build_city_count
            + self.build_road_count
            + self.build_farm_count
            + self.build_lumber_mill_count
            + self.build_mine_count
            + self.build_library_count
            + self.research_agriculture_count
            + self.research_logging_count
            + self.research_mining_count
            + self.research_education_count
            + self.skip_count
        )
        turn_count = max(turn_count, 1)
        self.turn_elapsed_ms_total += duration_ms
        self.turn_elapsed_ms_max = max(self.turn_elapsed_ms_max, duration_ms)
        self.turn_elapsed_ms_avg = self.turn_elapsed_ms_total / turn_count


@dataclass(slots=True)
class GameConfig:
    mode: Mode = Mode.PLAY
    map_size: int = DEFAULT_MAP_SIZE
    turn_limit: int = DEFAULT_TURN_LIMIT
    map_difficulty: MapDifficulty = MapDifficulty.NORMAL
    policy_type: PolicyType = PolicyType.NONE
    playback_mode: PlaybackMode = PlaybackMode.NONE
    seed: int = 0

    def __post_init__(self) -> None:
        if not MIN_MAP_SIZE <= self.map_size <= MAX_MAP_SIZE:
            raise ValueError(
                f"map_size must be between {MIN_MAP_SIZE} and {MAX_MAP_SIZE}, got {self.map_size}."
            )
        if not MIN_TURN_LIMIT <= self.turn_limit <= MAX_TURN_LIMIT:
            raise ValueError(
                "turn_limit must be between "
                f"{MIN_TURN_LIMIT} and {MAX_TURN_LIMIT}, got {self.turn_limit}."
            )
        if self.mode is Mode.PLAY:
            if self.policy_type is not PolicyType.NONE:
                raise ValueError("Play mode requires policy_type=PolicyType.NONE.")
            if self.playback_mode is not PlaybackMode.NONE:
                raise ValueError("Play mode requires playback_mode=PlaybackMode.NONE.")
        if self.mode is Mode.AUTOPLAY:
            if self.policy_type is PolicyType.NONE:
                raise ValueError("Autoplay mode requires a concrete policy_type.")
            if self.policy_type not in {PolicyType.GREEDY, PolicyType.RANDOM}:
                raise ValueError("Autoplay mode only supports greedy or random policy types.")
            if self.playback_mode is PlaybackMode.NONE:
                raise ValueError("Autoplay mode requires a playback_mode.")

    @classmethod
    def for_play(
        cls,
        *,
        map_size: int = DEFAULT_MAP_SIZE,
        turn_limit: int = DEFAULT_TURN_LIMIT,
        map_difficulty: MapDifficulty = MapDifficulty.NORMAL,
        seed: int = 0,
    ) -> GameConfig:
        return cls(
            mode=Mode.PLAY,
            map_size=map_size,
            turn_limit=turn_limit,
            map_difficulty=map_difficulty,
            policy_type=PolicyType.NONE,
            playback_mode=PlaybackMode.NONE,
            seed=seed,
        )

    @classmethod
    def for_autoplay(
        cls,
        *,
        map_size: int = DEFAULT_MAP_SIZE,
        turn_limit: int = DEFAULT_TURN_LIMIT,
        map_difficulty: MapDifficulty = MapDifficulty.NORMAL,
        policy_type: PolicyType = PolicyType.GREEDY,
        playback_mode: PlaybackMode = PlaybackMode.NORMAL,
        seed: int = 0,
    ) -> GameConfig:
        return cls(
            mode=Mode.AUTOPLAY,
            map_size=map_size,
            turn_limit=turn_limit,
            map_difficulty=map_difficulty,
            policy_type=policy_type,
            playback_mode=playback_mode,
            seed=seed,
        )


@dataclass(slots=True)
class GameState:
    config: GameConfig
    board: dict[Coord, Tile] = field(default_factory=dict)
    cities: dict[int, City] = field(default_factory=dict)
    roads: dict[int, Road] = field(default_factory=dict)
    networks: dict[int, Network] = field(default_factory=dict)
    turn: int = 1
    score: int = 0
    message: str = ""
    selection: SelectionState = field(default_factory=SelectionState)
    is_game_over: bool = False
    stats: Stats = field(default_factory=Stats)
    next_city_id: int = 1
    next_road_id: int = 1
    next_network_id: int = 1

    def __post_init__(self) -> None:
        if self.turn < 1:
            raise ValueError("turn must be at least 1.")
        if self.next_city_id < 1 or self.next_road_id < 1 or self.next_network_id < 1:
            raise ValueError("All next-id counters must be positive.")

    @classmethod
    def empty(cls, config: GameConfig) -> GameState:
        return cls(config=config)

    def sorted_city_ids(self) -> list[int]:
        return sorted(self.cities, key=lambda city_id: coord_sort_key(self.cities[city_id].coord))
