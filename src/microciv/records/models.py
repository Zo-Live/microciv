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

RECORDS_SCHEMA_VERSION = 4

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


@dataclass(slots=True, frozen=True)
class RecordActionLogEntry:
    """Serializable action taken during a match."""

    turn: int
    action_type: str
    x: int | None = None
    y: int | None = None
    city_id: int | None = None
    building_type: str | None = None
    tech_type: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordActionLogEntry:
        return cls(
            turn=int(payload["turn"]),
            action_type=str(payload["action_type"]),
            x=int(payload["x"]) if "x" in payload else None,
            y=int(payload["y"]) if "y" in payload else None,
            city_id=int(payload["city_id"]) if "city_id" in payload else None,
            building_type=str(payload["building_type"]) if "building_type" in payload else None,
            tech_type=str(payload["tech_type"]) if "tech_type" in payload else None,
        )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "turn": self.turn,
            "action_type": self.action_type,
        }
        if self.x is not None:
            result["x"] = self.x
        if self.y is not None:
            result["y"] = self.y
        if self.city_id is not None:
            result["city_id"] = self.city_id
        if self.building_type is not None:
            result["building_type"] = self.building_type
        if self.tech_type is not None:
            result["tech_type"] = self.tech_type
        return result


@dataclass(slots=True, frozen=True)
class RecordTurnSnapshot:
    """Serializable snapshot of game state at the start of a turn."""

    turn: int
    score: int
    food: int
    wood: int
    ore: int
    science: int
    city_count: int
    building_count: int
    tech_count: int
    road_count: int
    network_count: int
    connected_city_count: int
    isolated_city_count: int
    largest_network_size: int
    starving_network_count: int
    legal_actions_count: int

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordTurnSnapshot:
        return cls(
            turn=int(payload["turn"]),
            score=int(payload["score"]),
            food=int(payload["food"]),
            wood=int(payload["wood"]),
            ore=int(payload["ore"]),
            science=int(payload["science"]),
            city_count=int(payload["city_count"]),
            building_count=int(payload["building_count"]),
            tech_count=int(payload["tech_count"]),
            road_count=int(payload["road_count"]),
            network_count=int(payload["network_count"]),
            connected_city_count=int(payload.get("connected_city_count", 0)),
            isolated_city_count=int(payload.get("isolated_city_count", 0)),
            largest_network_size=int(payload.get("largest_network_size", 0)),
            starving_network_count=int(payload.get("starving_network_count", 0)),
            legal_actions_count=int(payload["legal_actions_count"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "turn": self.turn,
            "score": self.score,
            "food": self.food,
            "wood": self.wood,
            "ore": self.ore,
            "science": self.science,
            "city_count": self.city_count,
            "building_count": self.building_count,
            "tech_count": self.tech_count,
            "road_count": self.road_count,
            "network_count": self.network_count,
            "connected_city_count": self.connected_city_count,
            "isolated_city_count": self.isolated_city_count,
            "largest_network_size": self.largest_network_size,
            "starving_network_count": self.starving_network_count,
            "legal_actions_count": self.legal_actions_count,
        }


@dataclass(slots=True, frozen=True)
class RecordDecisionContext:
    """Serializable decision context for a single turn."""

    turn: int
    legal_actions_count: int
    legal_build_city_count: int
    legal_build_road_count: int
    legal_build_building_count: int
    legal_research_tech_count: int
    legal_skip_count: int
    chosen_action_type: str | None = None
    greedy_priority: str | None = None
    greedy_best_action_type: str | None = None
    greedy_best_score: float | None = None
    random_type_weights: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordDecisionContext:
        return cls(
            turn=int(payload["turn"]),
            legal_actions_count=int(payload["legal_actions_count"]),
            legal_build_city_count=int(payload.get("legal_build_city_count", 0)),
            legal_build_road_count=int(payload.get("legal_build_road_count", 0)),
            legal_build_building_count=int(payload.get("legal_build_building_count", 0)),
            legal_research_tech_count=int(payload.get("legal_research_tech_count", 0)),
            legal_skip_count=int(payload.get("legal_skip_count", 0)),
            chosen_action_type=(
                str(payload["chosen_action_type"]) if "chosen_action_type" in payload else None
            ),
            greedy_priority=(
                str(payload["greedy_priority"]) if "greedy_priority" in payload else None
            ),
            greedy_best_action_type=(
                str(payload["greedy_best_action_type"])
                if "greedy_best_action_type" in payload
                else None
            ),
            greedy_best_score=(
                float(payload["greedy_best_score"]) if "greedy_best_score" in payload else None
            ),
            random_type_weights={
                str(key): float(value)
                for key, value in dict(payload.get("random_type_weights", {})).items()
            },
        )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "turn": self.turn,
            "legal_actions_count": self.legal_actions_count,
            "legal_build_city_count": self.legal_build_city_count,
            "legal_build_road_count": self.legal_build_road_count,
            "legal_build_building_count": self.legal_build_building_count,
            "legal_research_tech_count": self.legal_research_tech_count,
            "legal_skip_count": self.legal_skip_count,
        }
        if self.chosen_action_type is not None:
            result["chosen_action_type"] = self.chosen_action_type
        if self.greedy_priority is not None:
            result["greedy_priority"] = self.greedy_priority
        if self.greedy_best_action_type is not None:
            result["greedy_best_action_type"] = self.greedy_best_action_type
        if self.greedy_best_score is not None:
            result["greedy_best_score"] = self.greedy_best_score
        if self.random_type_weights:
            result["random_type_weights"] = self.random_type_weights
        return result


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
    decision_time_ms_total: float
    decision_time_ms_avg: float
    decision_time_ms_max: float
    turn_elapsed_ms_total: float
    turn_elapsed_ms_avg: float
    turn_elapsed_ms_max: float
    session_elapsed_ms: float
    final_map: list[RecordTileSnapshot] = field(default_factory=list)
    cities: list[RecordCitySnapshot] = field(default_factory=list)
    roads: list[RecordRoadSnapshot] = field(default_factory=list)
    networks: list[RecordNetworkSnapshot] = field(default_factory=list)
    action_log: list[RecordActionLogEntry] = field(default_factory=list)
    turn_snapshots: list[RecordTurnSnapshot] = field(default_factory=list)
    decision_contexts: list[RecordDecisionContext] = field(default_factory=list)

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
            action_log=[
                RecordActionLogEntry.from_dict(item) for item in state.stats.action_log
            ],
            turn_snapshots=[
                RecordTurnSnapshot.from_dict(item) for item in state.stats.turn_snapshots
            ],
            decision_contexts=[
                RecordDecisionContext.from_dict(item)
                for item in state.stats.decision_contexts
            ],
        )

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordEntry:
        mode = str(payload["mode"])
        if mode not in {"play", "autoplay"}:
            raise ValueError(f"Invalid mode: {mode}")
        ai_type = str(payload["ai_type"])
        if ai_type not in {"Human", "Greedy", "Random"}:
            raise ValueError(f"Invalid ai_type: {ai_type}")
        playback_mode = str(payload["playback_mode"])
        if playback_mode not in {"", "normal", "speed"}:
            raise ValueError(f"Invalid playback_mode: {playback_mode}")
        return cls(
            record_id=int(payload["record_id"]),
            timestamp=str(payload["timestamp"]),
            game_version=str(payload["game_version"]),
            mode=mode,
            ai_type=ai_type,
            custom_goal=str(payload["custom_goal"]),
            playback_mode=playback_mode,
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
            decision_time_ms_total=float(payload["decision_time_ms_total"]),
            decision_time_ms_avg=float(payload["decision_time_ms_avg"]),
            decision_time_ms_max=float(payload["decision_time_ms_max"]),
            turn_elapsed_ms_total=float(payload["turn_elapsed_ms_total"]),
            turn_elapsed_ms_avg=float(payload["turn_elapsed_ms_avg"]),
            turn_elapsed_ms_max=float(payload["turn_elapsed_ms_max"]),
            session_elapsed_ms=float(payload["session_elapsed_ms"]),
            final_map=[RecordTileSnapshot.from_dict(item) for item in payload.get("final_map", [])],
            cities=[RecordCitySnapshot.from_dict(item) for item in payload.get("cities", [])],
            roads=[RecordRoadSnapshot.from_dict(item) for item in payload.get("roads", [])],
            networks=[
                RecordNetworkSnapshot.from_dict(item) for item in payload.get("networks", [])
            ],
            action_log=[
                RecordActionLogEntry.from_dict(item) for item in payload.get("action_log", [])
            ],
            turn_snapshots=[
                RecordTurnSnapshot.from_dict(item) for item in payload.get("turn_snapshots", [])
            ],
            decision_contexts=[
                RecordDecisionContext.from_dict(item)
                for item in payload.get("decision_contexts", [])
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
                "action_log": [entry.to_dict() for entry in self.action_log],
                "turn_snapshots": [snapshot.to_dict() for snapshot in self.turn_snapshots],
                "decision_contexts": [ctx.to_dict() for ctx in self.decision_contexts],
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
        if "schema_version" not in payload or "next_record_id" not in payload:
            raise ValueError("Missing schema_version or next_record_id")
        return cls(
            schema_version=int(payload["schema_version"]),
            next_record_id=int(payload["next_record_id"]),
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
    if state.config.policy_type is PolicyType.GREEDY:
        return "Greedy"
    if state.config.policy_type is PolicyType.RANDOM:
        return "Random"
    return state.config.policy_type.value.title()
