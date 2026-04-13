"""Data models for persisted match records."""

from __future__ import annotations

from dataclasses import dataclass, field

from microciv.constants import PROJECT_VERSION
from microciv.game.enums import Mode, PolicyType
from microciv.game.models import City, GameState, Network, Road, Tile
from microciv.game.scoring import (
    building_count,
    calculate_score,
    city_count,
    tech_count,
    total_resources,
)
from microciv.utils.grid import Coord, coord_sort_key

RECORDS_SCHEMA_VERSION = 2

CSV_FIELD_ORDER: tuple[str, ...] = (
    "record_id",
    "timestamp",
    "game_version",
    "mode",
    "ai_type",
    "custom_goal",
    "playback_mode",
    "seed",
    "map_size",
    "map_difficulty",
    "turn_limit",
    "actual_turns",
    "final_score",
    "city_count",
    "building_count",
    "tech_count",
    "food",
    "wood",
    "ore",
    "science",
    "build_city_count",
    "build_road_count",
    "build_farm_count",
    "build_lumber_mill_count",
    "build_mine_count",
    "build_library_count",
    "research_agriculture_count",
    "research_logging_count",
    "research_mining_count",
    "research_education_count",
    "skip_count",
    "decision_count",
    "decision_time_ms_total",
    "decision_time_ms_avg",
    "decision_time_ms_max",
    "turn_elapsed_ms_total",
    "turn_elapsed_ms_avg",
    "turn_elapsed_ms_max",
    "session_elapsed_ms",
)


@dataclass(slots=True, frozen=True)
class RecordTileSnapshot:
    """Serializable snapshot of a final map tile."""

    x: int
    y: int
    base_terrain: str
    occupant: str

    @classmethod
    def from_tile(cls, coord: Coord, tile: Tile) -> RecordTileSnapshot:
        return cls(
            x=coord[0],
            y=coord[1],
            base_terrain=tile.base_terrain.value,
            occupant=tile.occupant.value,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordTileSnapshot:
        return cls(
            x=int(payload["x"]),
            y=int(payload["y"]),
            base_terrain=str(payload["base_terrain"]),
            occupant=str(payload["occupant"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "x": self.x,
            "y": self.y,
            "base_terrain": self.base_terrain,
            "occupant": self.occupant,
        }


@dataclass(slots=True, frozen=True)
class RecordCitySnapshot:
    """Serializable snapshot of a final city."""

    city_id: int
    x: int
    y: int
    founded_turn: int
    network_id: int
    farm: int
    lumber_mill: int
    mine: int
    library: int
    total_buildings: int

    @classmethod
    def from_city(cls, city: City) -> RecordCitySnapshot:
        return cls(
            city_id=city.city_id,
            x=city.coord[0],
            y=city.coord[1],
            founded_turn=city.founded_turn,
            network_id=city.network_id,
            farm=city.buildings.farm,
            lumber_mill=city.buildings.lumber_mill,
            mine=city.buildings.mine,
            library=city.buildings.library,
            total_buildings=city.total_buildings,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordCitySnapshot:
        return cls(
            city_id=int(payload["city_id"]),
            x=int(payload["x"]),
            y=int(payload["y"]),
            founded_turn=int(payload["founded_turn"]),
            network_id=int(payload["network_id"]),
            farm=int(payload["farm"]),
            lumber_mill=int(payload["lumber_mill"]),
            mine=int(payload["mine"]),
            library=int(payload["library"]),
            total_buildings=int(payload["total_buildings"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "city_id": self.city_id,
            "x": self.x,
            "y": self.y,
            "founded_turn": self.founded_turn,
            "network_id": self.network_id,
            "farm": self.farm,
            "lumber_mill": self.lumber_mill,
            "mine": self.mine,
            "library": self.library,
            "total_buildings": self.total_buildings,
        }


@dataclass(slots=True, frozen=True)
class RecordRoadSnapshot:
    """Serializable snapshot of a final road."""

    road_id: int
    x: int
    y: int
    built_turn: int

    @classmethod
    def from_road(cls, road: Road) -> RecordRoadSnapshot:
        return cls(
            road_id=road.road_id, x=road.coord[0], y=road.coord[1], built_turn=road.built_turn
        )

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordRoadSnapshot:
        return cls(
            road_id=int(payload["road_id"]),
            x=int(payload["x"]),
            y=int(payload["y"]),
            built_turn=int(payload["built_turn"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "road_id": self.road_id,
            "x": self.x,
            "y": self.y,
            "built_turn": self.built_turn,
        }


@dataclass(slots=True, frozen=True)
class RecordNetworkSnapshot:
    """Serializable snapshot of a final network."""

    network_id: int
    city_ids: list[int]
    food: int
    wood: int
    ore: int
    science: int
    unlocked_techs: list[str]

    @classmethod
    def from_network(cls, network: Network) -> RecordNetworkSnapshot:
        return cls(
            network_id=network.network_id,
            city_ids=sorted(network.city_ids),
            food=network.resources.food,
            wood=network.resources.wood,
            ore=network.resources.ore,
            science=network.resources.science,
            unlocked_techs=sorted(tech.value for tech in network.unlocked_techs),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordNetworkSnapshot:
        return cls(
            network_id=int(payload["network_id"]),
            city_ids=[int(city_id) for city_id in payload["city_ids"]],
            food=int(payload["food"]),
            wood=int(payload["wood"]),
            ore=int(payload["ore"]),
            science=int(payload["science"]),
            unlocked_techs=[str(tech) for tech in payload["unlocked_techs"]],
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "network_id": self.network_id,
            "city_ids": self.city_ids,
            "food": self.food,
            "wood": self.wood,
            "ore": self.ore,
            "science": self.science,
            "unlocked_techs": self.unlocked_techs,
        }


@dataclass(slots=True)
class RecordEntry:
    """Persisted result for a completed match."""

    record_id: int
    timestamp: str
    game_version: str
    mode: str
    ai_type: str
    custom_goal: str
    playback_mode: str
    seed: int
    map_size: int
    map_difficulty: str
    turn_limit: int
    actual_turns: int
    final_score: int
    city_count: int
    building_count: int
    tech_count: int
    food: int
    wood: int
    ore: int
    science: int
    build_city_count: int
    build_road_count: int
    build_farm_count: int
    build_lumber_mill_count: int
    build_mine_count: int
    build_library_count: int
    research_agriculture_count: int
    research_logging_count: int
    research_mining_count: int
    research_education_count: int
    skip_count: int
    decision_count: int
    decision_time_ms_total: int
    decision_time_ms_avg: int
    decision_time_ms_max: int
    turn_elapsed_ms_total: int
    turn_elapsed_ms_avg: int
    turn_elapsed_ms_max: int
    session_elapsed_ms: int
    final_map: list[RecordTileSnapshot] = field(default_factory=list)
    cities: list[RecordCitySnapshot] = field(default_factory=list)
    roads: list[RecordRoadSnapshot] = field(default_factory=list)
    networks: list[RecordNetworkSnapshot] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.record_id < 1:
            raise ValueError("record_id must be positive.")

    @classmethod
    def from_game_state(
        cls,
        *,
        record_id: int,
        timestamp: str,
        state: GameState,
        game_version: str = PROJECT_VERSION,
    ) -> RecordEntry:
        resources = total_resources(state)
        return cls(
            record_id=record_id,
            timestamp=timestamp,
            game_version=game_version,
            mode=state.config.mode.value,
            ai_type=_ai_type_label(state),
            custom_goal="",
            playback_mode=""
            if state.config.mode is Mode.PLAY
            else state.config.playback_mode.value,
            seed=state.config.seed,
            map_size=state.config.map_size,
            map_difficulty=state.config.map_difficulty.value,
            turn_limit=state.config.turn_limit,
            actual_turns=state.turn,
            final_score=calculate_score(state),
            city_count=city_count(state),
            building_count=building_count(state),
            tech_count=tech_count(state),
            food=resources.food,
            wood=resources.wood,
            ore=resources.ore,
            science=resources.science,
            build_city_count=state.stats.build_city_count,
            build_road_count=state.stats.build_road_count,
            build_farm_count=state.stats.build_farm_count,
            build_lumber_mill_count=state.stats.build_lumber_mill_count,
            build_mine_count=state.stats.build_mine_count,
            build_library_count=state.stats.build_library_count,
            research_agriculture_count=state.stats.research_agriculture_count,
            research_logging_count=state.stats.research_logging_count,
            research_mining_count=state.stats.research_mining_count,
            research_education_count=state.stats.research_education_count,
            skip_count=state.stats.skip_count,
            decision_count=state.stats.decision_count,
            decision_time_ms_total=state.stats.decision_time_ms_total,
            decision_time_ms_avg=state.stats.decision_time_ms_avg,
            decision_time_ms_max=state.stats.decision_time_ms_max,
            turn_elapsed_ms_total=state.stats.turn_elapsed_ms_total,
            turn_elapsed_ms_avg=state.stats.turn_elapsed_ms_avg,
            turn_elapsed_ms_max=state.stats.turn_elapsed_ms_max,
            session_elapsed_ms=state.stats.session_elapsed_ms,
            final_map=_board_snapshots(state),
            cities=_city_snapshots(state),
            roads=_road_snapshots(state),
            networks=_network_snapshots(state),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordEntry:
        return cls(
            record_id=int(payload["record_id"]),
            timestamp=str(payload["timestamp"]),
            game_version=str(payload["game_version"]),
            mode=str(payload["mode"]),
            ai_type=str(payload["ai_type"]),
            custom_goal=str(payload["custom_goal"]),
            playback_mode=str(payload["playback_mode"]),
            seed=int(payload["seed"]),
            map_size=int(payload["map_size"]),
            map_difficulty=str(payload["map_difficulty"]),
            turn_limit=int(payload["turn_limit"]),
            actual_turns=int(payload["actual_turns"]),
            final_score=int(payload["final_score"]),
            city_count=int(payload["city_count"]),
            building_count=int(payload["building_count"]),
            tech_count=int(payload["tech_count"]),
            food=int(payload["food"]),
            wood=int(payload["wood"]),
            ore=int(payload["ore"]),
            science=int(payload["science"]),
            build_city_count=int(payload["build_city_count"]),
            build_road_count=int(payload["build_road_count"]),
            build_farm_count=int(payload["build_farm_count"]),
            build_lumber_mill_count=int(payload["build_lumber_mill_count"]),
            build_mine_count=int(payload["build_mine_count"]),
            build_library_count=int(payload["build_library_count"]),
            research_agriculture_count=int(payload["research_agriculture_count"]),
            research_logging_count=int(payload["research_logging_count"]),
            research_mining_count=int(payload["research_mining_count"]),
            research_education_count=int(payload["research_education_count"]),
            skip_count=int(payload["skip_count"]),
            decision_count=int(payload["decision_count"]),
            decision_time_ms_total=int(payload["decision_time_ms_total"]),
            decision_time_ms_avg=int(payload["decision_time_ms_avg"]),
            decision_time_ms_max=int(payload["decision_time_ms_max"]),
            turn_elapsed_ms_total=int(payload["turn_elapsed_ms_total"]),
            turn_elapsed_ms_avg=int(payload["turn_elapsed_ms_avg"]),
            turn_elapsed_ms_max=int(payload["turn_elapsed_ms_max"]),
            session_elapsed_ms=int(payload["session_elapsed_ms"]),
            final_map=[RecordTileSnapshot.from_dict(item) for item in payload.get("final_map", [])],
            cities=[RecordCitySnapshot.from_dict(item) for item in payload.get("cities", [])],
            roads=[RecordRoadSnapshot.from_dict(item) for item in payload.get("roads", [])],
            networks=[
                RecordNetworkSnapshot.from_dict(item) for item in payload.get("networks", [])
            ],
        )

    def to_csv_row(self) -> dict[str, object]:
        return {field_name: getattr(self, field_name) for field_name in CSV_FIELD_ORDER}

    def to_dict(self) -> dict[str, object]:
        payload = self.to_csv_row()
        payload.update(
            {
                "final_map": [tile.to_dict() for tile in self.final_map],
                "cities": [city.to_dict() for city in self.cities],
                "roads": [road.to_dict() for road in self.roads],
                "networks": [network.to_dict() for network in self.networks],
            }
        )
        return payload


@dataclass(slots=True)
class RecordDatabase:
    """Top-level persisted records payload."""

    schema_version: int = RECORDS_SCHEMA_VERSION
    next_record_id: int = 1
    records: list[RecordEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.next_record_id < 1:
            raise ValueError("next_record_id must be positive.")

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordDatabase:
        return cls(
            schema_version=int(payload.get("schema_version", RECORDS_SCHEMA_VERSION)),
            next_record_id=int(payload.get("next_record_id", 1)),
            records=[RecordEntry.from_dict(item) for item in payload.get("records", [])],
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "next_record_id": self.next_record_id,
            "records": [record.to_dict() for record in self.records],
        }


def _board_snapshots(state: GameState) -> list[RecordTileSnapshot]:
    return [
        RecordTileSnapshot.from_tile(coord, tile)
        for coord, tile in sorted(state.board.items(), key=lambda item: coord_sort_key(item[0]))
    ]


def _city_snapshots(state: GameState) -> list[RecordCitySnapshot]:
    return [
        RecordCitySnapshot.from_city(city)
        for city in sorted(
            state.cities.values(), key=lambda city: (coord_sort_key(city.coord), city.city_id)
        )
    ]


def _road_snapshots(state: GameState) -> list[RecordRoadSnapshot]:
    return [
        RecordRoadSnapshot.from_road(road)
        for road in sorted(
            state.roads.values(), key=lambda road: (coord_sort_key(road.coord), road.road_id)
        )
    ]


def _network_snapshots(state: GameState) -> list[RecordNetworkSnapshot]:
    return [
        RecordNetworkSnapshot.from_network(network)
        for network in sorted(state.networks.values(), key=lambda network: network.network_id)
    ]


def _ai_type_label(state: GameState) -> str:
    if state.config.mode is Mode.PLAY:
        return "Human"
    if state.config.policy_type is PolicyType.BASELINE:
        return "Baseline"
    if state.config.policy_type is PolicyType.RANDOM:
        return "Random"
    return state.config.policy_type.value.title()
