"""Data models for persisted match records."""

from __future__ import annotations

from collections.abc import Mapping
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

RECORDS_SCHEMA_VERSION = 10

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


def _require_dict(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object.")
    return {str(key): item for key, item in value.items()}


def _require_int(payload: Mapping[str, object], field_name: str) -> int:
    value = payload[field_name]
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise ValueError(f"{field_name} must be an integer.")


def _optional_int(payload: Mapping[str, object], field_name: str) -> int | None:
    if field_name not in payload:
        return None
    if payload[field_name] is None:
        return None
    return _require_int(payload, field_name)


def _int_with_default(payload: Mapping[str, object], field_name: str, default: int) -> int:
    value = _optional_int(payload, field_name)
    return default if value is None else value


def _require_bool(payload: Mapping[str, object], field_name: str) -> bool:
    value = payload[field_name]
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1"}:
            return True
        if lowered in {"false", "0"}:
            return False
    raise ValueError(f"{field_name} must be a boolean.")


def _optional_bool(payload: Mapping[str, object], field_name: str) -> bool | None:
    if field_name not in payload:
        return None
    if payload[field_name] is None:
        return None
    return _require_bool(payload, field_name)


def _require_float(payload: Mapping[str, object], field_name: str) -> float:
    value = payload[field_name]
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise ValueError(f"{field_name} must be a number.")


def _optional_float(payload: Mapping[str, object], field_name: str) -> float | None:
    if field_name not in payload:
        return None
    if payload[field_name] is None:
        return None
    return _require_float(payload, field_name)


def _require_str(payload: Mapping[str, object], field_name: str) -> str:
    value = payload[field_name]
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    return value


def _optional_str(payload: Mapping[str, object], field_name: str) -> str | None:
    if field_name not in payload:
        return None
    if payload[field_name] is None:
        return None
    return _require_str(payload, field_name)


def _list_field(payload: Mapping[str, object], field_name: str) -> list[object]:
    value = payload.get(field_name, [])
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    return value


def _list_of_dicts(payload: Mapping[str, object], field_name: str) -> list[dict[str, object]]:
    return [
        _require_dict(item, f"{field_name}[{index}]")
        for index, item in enumerate(_list_field(payload, field_name))
    ]


def _mapping_field(payload: Mapping[str, object], field_name: str) -> dict[str, object]:
    value = payload.get(field_name, {})
    return _require_dict(value, field_name)


def _list_of_ints(payload: Mapping[str, object], field_name: str) -> list[int]:
    values: list[int] = []
    for index, item in enumerate(_list_field(payload, field_name)):
        if isinstance(item, int):
            values.append(item)
            continue
        if isinstance(item, str):
            values.append(int(item))
            continue
        raise ValueError(f"{field_name}[{index}] must be an integer.")
    return values


def _mapping_of_floats(payload: Mapping[str, object], field_name: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for key, value in _mapping_field(payload, field_name).items():
        if isinstance(value, int | float):
            values[str(key)] = float(value)
            continue
        if isinstance(value, str):
            values[str(key)] = float(value)
            continue
        raise ValueError(f"{field_name}[{key!r}] must be numeric.")
    return values


def _mapping_of_ints(payload: Mapping[str, object], field_name: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for key, value in _mapping_field(payload, field_name).items():
        if isinstance(value, bool):
            values[str(key)] = int(value)
            continue
        if isinstance(value, int):
            values[str(key)] = value
            continue
        if isinstance(value, str):
            values[str(key)] = int(value)
            continue
        raise ValueError(f"{field_name}[{key!r}] must be integer-like.")
    return values


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
            x=_require_int(payload, "x"),
            y=_require_int(payload, "y"),
            base_terrain=_require_str(payload, "base_terrain"),
            occupant=_require_str(payload, "occupant"),
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
            city_id=_require_int(payload, "city_id"),
            x=_require_int(payload, "x"),
            y=_require_int(payload, "y"),
            founded_turn=_require_int(payload, "founded_turn"),
            network_id=_require_int(payload, "network_id"),
            farm=_require_int(payload, "farm"),
            lumber_mill=_require_int(payload, "lumber_mill"),
            mine=_require_int(payload, "mine"),
            library=_require_int(payload, "library"),
            total_buildings=_require_int(payload, "total_buildings"),
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
            road_id=_require_int(payload, "road_id"),
            x=_require_int(payload, "x"),
            y=_require_int(payload, "y"),
            built_turn=_require_int(payload, "built_turn"),
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
    consecutive_starving_turns: int
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
            consecutive_starving_turns=network.consecutive_starving_turns,
            unlocked_techs=sorted(tech.value for tech in network.unlocked_techs),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordNetworkSnapshot:
        return cls(
            network_id=_require_int(payload, "network_id"),
            city_ids=_list_of_ints(payload, "city_ids"),
            food=_require_int(payload, "food"),
            wood=_require_int(payload, "wood"),
            ore=_require_int(payload, "ore"),
            science=_require_int(payload, "science"),
            consecutive_starving_turns=_int_with_default(payload, "consecutive_starving_turns", 0),
            unlocked_techs=[str(tech) for tech in _list_field(payload, "unlocked_techs")],
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "network_id": self.network_id,
            "city_ids": self.city_ids,
            "food": self.food,
            "wood": self.wood,
            "ore": self.ore,
            "science": self.science,
            "consecutive_starving_turns": self.consecutive_starving_turns,
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
            turn=_require_int(payload, "turn"),
            action_type=_require_str(payload, "action_type"),
            x=_optional_int(payload, "x"),
            y=_optional_int(payload, "y"),
            city_id=_optional_int(payload, "city_id"),
            building_type=_optional_str(payload, "building_type"),
            tech_type=_optional_str(payload, "tech_type"),
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
class RecordSearchActionSnapshot:
    """Serializable planned action used in search diagnostics."""

    action_type: str
    x: int | None = None
    y: int | None = None
    city_id: int | None = None
    building_type: str | None = None
    tech_type: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordSearchActionSnapshot:
        return cls(
            action_type=_require_str(payload, "action_type"),
            x=_optional_int(payload, "x"),
            y=_optional_int(payload, "y"),
            city_id=_optional_int(payload, "city_id"),
            building_type=_optional_str(payload, "building_type"),
            tech_type=_optional_str(payload, "tech_type"),
        )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"action_type": self.action_type}
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
    score_breakdown: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordTurnSnapshot:
        return cls(
            turn=_require_int(payload, "turn"),
            score=_require_int(payload, "score"),
            food=_require_int(payload, "food"),
            wood=_require_int(payload, "wood"),
            ore=_require_int(payload, "ore"),
            science=_require_int(payload, "science"),
            city_count=_require_int(payload, "city_count"),
            building_count=_require_int(payload, "building_count"),
            tech_count=_require_int(payload, "tech_count"),
            road_count=_require_int(payload, "road_count"),
            network_count=_require_int(payload, "network_count"),
            connected_city_count=_int_with_default(payload, "connected_city_count", 0),
            isolated_city_count=_int_with_default(payload, "isolated_city_count", 0),
            largest_network_size=_int_with_default(payload, "largest_network_size", 0),
            starving_network_count=_int_with_default(payload, "starving_network_count", 0),
            legal_actions_count=_require_int(payload, "legal_actions_count"),
            score_breakdown=_mapping_of_ints(payload, "score_breakdown"),
        )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
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
        if self.score_breakdown:
            result["score_breakdown"] = self.score_breakdown
        return result


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
    decision_time_ms: float | None = None
    greedy_stage: str | None = None
    greedy_priority: str | None = None
    greedy_best_action_type: str | None = None
    greedy_best_score: float | None = None
    greedy_best_delta_score: int | None = None
    greedy_food_pressure: int | None = None
    greedy_starving_networks: int | None = None
    greedy_connected_cities: int | None = None
    greedy_total_food: int | None = None
    greedy_network_count: int | None = None
    greedy_global_starving_delta: int | None = None
    greedy_global_network_delta: int | None = None
    greedy_global_isolation_delta: int | None = None
    greedy_rescue_effective: bool | None = None
    greedy_escape_mode: bool | None = None
    greedy_escape_reason: str | None = None
    greedy_food_rescue_stalled: bool | None = None
    greedy_food_rescue_chain: int | None = None
    greedy_fill_reopen_reason: str | None = None
    greedy_best_connection_steps: int | None = None
    greedy_best_future_network_starving: bool | None = None
    greedy_score_breakdown: dict[str, int] = field(default_factory=dict)
    greedy_best_site_budget: dict[str, int] = field(default_factory=dict)
    greedy_best_future_network_budget: dict[str, int] = field(default_factory=dict)
    random_type_weights: dict[str, float] = field(default_factory=dict)
    search_mode: str | None = None
    search_depth: int | None = None
    search_actual_depth: int | None = None
    search_base_depth: int | None = None
    search_max_depth: int | None = None
    search_depth_reason: str | None = None
    search_deep_search_enabled: bool | None = None
    search_planning_mode: str | None = None
    search_planning_reason: str | None = None
    search_overrode_greedy: bool | None = None
    search_intervention_trigger: str | None = None
    search_probe_accepted_reason: str | None = None
    search_probe_rejected_reason: str | None = None
    search_beam_width: int | None = None
    search_candidate_limit: int | None = None
    search_root_legal_build_city_count: int | None = None
    search_root_legal_build_road_count: int | None = None
    search_root_legal_build_building_count: int | None = None
    search_root_legal_research_tech_count: int | None = None
    search_root_legal_skip_count: int | None = None
    search_root_candidate_build_city_count: int | None = None
    search_root_candidate_build_road_count: int | None = None
    search_root_candidate_build_building_count: int | None = None
    search_root_candidate_research_tech_count: int | None = None
    search_root_candidate_skip_count: int | None = None
    search_nodes_expanded: int | None = None
    search_candidates_considered: int | None = None
    search_leaf_count: int | None = None
    search_best_value: int | None = None
    search_value_components: dict[str, int] = field(default_factory=dict)
    search_sequence_adjustment: int | None = None
    search_dominant_pressure: str | None = None
    search_dominant_pressure_value: int | None = None
    search_risk_pressure_total: int | None = None
    search_is_risk_dominated: bool | None = None
    search_is_sequence_adjusted: bool | None = None
    search_best_score_total: int | None = None
    search_best_connected_city_count: int | None = None
    search_best_isolated_city_count: int | None = None
    search_best_starving_network_count: int | None = None
    search_best_network_count: int | None = None
    search_best_largest_network_size: int | None = None
    search_best_total_food: int | None = None
    search_best_total_wood: int | None = None
    search_best_total_ore: int | None = None
    search_best_total_science: int | None = None
    search_best_food_pressure: int | None = None
    search_best_starving_turns: int | None = None
    search_best_sequence: list[RecordSearchActionSnapshot] = field(default_factory=list)
    search_root_chosen_rank: int | None = None
    search_root_chosen_value: int | None = None
    search_root_best_value: int | None = None
    search_root_value_margin: int | None = None
    search_root_best_action_type: str | None = None
    search_root_chosen_action_type: str | None = None
    search_root_best_build_city_value: int | None = None
    search_root_best_build_road_value: int | None = None
    search_root_best_build_building_value: int | None = None
    search_root_best_research_tech_value: int | None = None
    search_root_best_skip_value: int | None = None
    search_root_candidate_cut_ratio: float | None = None
    search_root_safe_city_candidate_count: int | None = None
    search_root_effective_connection_road_candidate_count: int | None = None
    search_root_rescue_candidate_count: int | None = None
    search_root_effective_city_candidate_count: int | None = None
    search_root_redundant_road_candidate_count: int | None = None
    search_root_high_roi_building_candidate_count: int | None = None
    search_root_gated_candidate_count: int | None = None
    search_bridge_candidate_count: int | None = None
    search_bridge_min_steps: int | None = None
    search_bridge_progress_after_first_step: int | None = None
    search_delta_starving_network_count: int | None = None
    search_delta_food_pressure: int | None = None
    search_delta_isolated_city_count: int | None = None
    search_delta_network_count: int | None = None
    search_delta_connected_city_count: int | None = None
    search_delta_road_overbuild: int | None = None
    search_delta_worst_network_food_pressure: int | None = None
    search_delta_min_network_food: int | None = None
    search_road_merges_networks: bool | None = None
    search_road_connected_city_delta: int | None = None
    search_road_is_redundant: bool | None = None
    search_road_after_full_connectivity: bool | None = None
    search_greedy_action_type: str | None = None
    search_matches_greedy_action: bool | None = None
    search_greedy_action_in_root_candidates: bool | None = None
    search_greedy_action_root_rank: int | None = None
    search_greedy_action_root_value: int | None = None
    search_greedy_action_root_value_margin: int | None = None
    search_chosen_value_delta_vs_greedy_action: int | None = None
    search_chosen_city_site_score: int | None = None
    search_greedy_city_site_score: int | None = None
    search_chosen_city_site_score_delta_vs_greedy: int | None = None
    search_chosen_city_resource_ring_bonus: int | None = None
    search_chosen_city_food_balance: int | None = None
    search_chosen_city_total_yield: int | None = None
    search_chosen_city_river_access: bool | None = None
    search_chosen_city_forest_neighbors: int | None = None
    search_chosen_city_mountain_neighbors: int | None = None
    search_chosen_city_river_neighbors: int | None = None
    search_chosen_city_plain_neighbors: int | None = None
    search_chosen_city_occupied_neighbors: int | None = None
    search_chosen_city_distance_to_network: int | None = None
    search_greedy_city_food_balance: int | None = None
    search_greedy_city_total_yield: int | None = None
    search_greedy_city_river_access: bool | None = None
    search_greedy_city_forest_neighbors: int | None = None
    search_greedy_city_mountain_neighbors: int | None = None
    search_greedy_city_river_neighbors: int | None = None
    search_greedy_city_plain_neighbors: int | None = None
    search_greedy_city_occupied_neighbors: int | None = None
    search_greedy_city_distance_to_network: int | None = None
    search_greedy_city_resource_ring_bonus: int | None = None
    search_min_network_food_after_action: int | None = None
    search_worst_network_food_pressure_after_action: int | None = None
    search_food_surplus_network_count_after_action: int | None = None
    search_food_deficit_network_count_after_action: int | None = None
    search_greedy_after_score_total: int | None = None
    search_greedy_after_starving_network_count: int | None = None
    search_greedy_after_food_pressure: int | None = None
    search_greedy_after_min_network_food: int | None = None
    search_greedy_after_network_count: int | None = None
    search_greedy_after_connected_city_count: int | None = None
    search_greedy_after_isolated_city_count: int | None = None
    search_selected_after_score_total: int | None = None
    search_selected_after_starving_network_count: int | None = None
    search_selected_after_food_pressure: int | None = None
    search_selected_after_min_network_food: int | None = None
    search_selected_after_network_count: int | None = None
    search_selected_after_connected_city_count: int | None = None
    search_selected_after_isolated_city_count: int | None = None
    search_simulation_cache_hits: int | None = None
    search_simulation_cache_misses: int | None = None
    search_profile_city_count: int | None = None
    search_profile_target_city_count: int | None = None
    search_profile_expansion_deficit: int | None = None
    search_profile_safe_expansion_deficit: int | None = None
    search_profile_network_count: int | None = None
    search_profile_connected_city_count: int | None = None
    search_profile_isolated_city_count: int | None = None
    search_profile_starving_network_count: int | None = None
    search_profile_food_pressure: int | None = None
    search_profile_road_overbuild: int | None = None
    search_profile_fill_count: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordDecisionContext:
        return cls(
            turn=_require_int(payload, "turn"),
            legal_actions_count=_require_int(payload, "legal_actions_count"),
            legal_build_city_count=_int_with_default(payload, "legal_build_city_count", 0),
            legal_build_road_count=_int_with_default(payload, "legal_build_road_count", 0),
            legal_build_building_count=_int_with_default(payload, "legal_build_building_count", 0),
            legal_research_tech_count=_int_with_default(payload, "legal_research_tech_count", 0),
            legal_skip_count=_int_with_default(payload, "legal_skip_count", 0),
            chosen_action_type=_optional_str(payload, "chosen_action_type"),
            decision_time_ms=_optional_float(payload, "decision_time_ms"),
            greedy_stage=_optional_str(payload, "greedy_stage"),
            greedy_priority=_optional_str(payload, "greedy_priority"),
            greedy_best_action_type=_optional_str(payload, "greedy_best_action_type"),
            greedy_best_score=(
                _require_float(payload, "greedy_best_score")
                if "greedy_best_score" in payload
                else None
            ),
            greedy_best_delta_score=_optional_int(payload, "greedy_best_delta_score"),
            greedy_food_pressure=_optional_int(payload, "greedy_food_pressure"),
            greedy_starving_networks=_optional_int(payload, "greedy_starving_networks"),
            greedy_connected_cities=_optional_int(payload, "greedy_connected_cities"),
            greedy_total_food=_optional_int(payload, "greedy_total_food"),
            greedy_network_count=_optional_int(payload, "greedy_network_count"),
            greedy_global_starving_delta=_optional_int(payload, "greedy_global_starving_delta"),
            greedy_global_network_delta=_optional_int(payload, "greedy_global_network_delta"),
            greedy_global_isolation_delta=_optional_int(payload, "greedy_global_isolation_delta"),
            greedy_rescue_effective=_optional_bool(payload, "greedy_rescue_effective"),
            greedy_escape_mode=_optional_bool(payload, "greedy_escape_mode"),
            greedy_escape_reason=_optional_str(payload, "greedy_escape_reason"),
            greedy_food_rescue_stalled=_optional_bool(payload, "greedy_food_rescue_stalled"),
            greedy_food_rescue_chain=_optional_int(payload, "greedy_food_rescue_chain"),
            greedy_fill_reopen_reason=_optional_str(payload, "greedy_fill_reopen_reason"),
            greedy_best_connection_steps=_optional_int(payload, "greedy_best_connection_steps"),
            greedy_best_future_network_starving=_optional_bool(
                payload, "greedy_best_future_network_starving"
            ),
            greedy_score_breakdown=_mapping_of_ints(payload, "greedy_score_breakdown"),
            greedy_best_site_budget=_mapping_of_ints(payload, "greedy_best_site_budget"),
            greedy_best_future_network_budget=_mapping_of_ints(
                payload, "greedy_best_future_network_budget"
            ),
            random_type_weights=_mapping_of_floats(payload, "random_type_weights"),
            search_mode=_optional_str(payload, "search_mode"),
            search_depth=_optional_int(payload, "search_depth"),
            search_actual_depth=_optional_int(payload, "search_actual_depth"),
            search_base_depth=_optional_int(payload, "search_base_depth"),
            search_max_depth=_optional_int(payload, "search_max_depth"),
            search_depth_reason=_optional_str(payload, "search_depth_reason"),
            search_deep_search_enabled=_optional_bool(payload, "search_deep_search_enabled"),
            search_planning_mode=_optional_str(payload, "search_planning_mode"),
            search_planning_reason=_optional_str(payload, "search_planning_reason"),
            search_overrode_greedy=_optional_bool(payload, "search_overrode_greedy"),
            search_intervention_trigger=_optional_str(payload, "search_intervention_trigger"),
            search_probe_accepted_reason=_optional_str(payload, "search_probe_accepted_reason"),
            search_probe_rejected_reason=_optional_str(payload, "search_probe_rejected_reason"),
            search_beam_width=_optional_int(payload, "search_beam_width"),
            search_candidate_limit=_optional_int(payload, "search_candidate_limit"),
            search_root_legal_build_city_count=_optional_int(
                payload, "search_root_legal_build_city_count"
            ),
            search_root_legal_build_road_count=_optional_int(
                payload, "search_root_legal_build_road_count"
            ),
            search_root_legal_build_building_count=_optional_int(
                payload, "search_root_legal_build_building_count"
            ),
            search_root_legal_research_tech_count=_optional_int(
                payload, "search_root_legal_research_tech_count"
            ),
            search_root_legal_skip_count=_optional_int(payload, "search_root_legal_skip_count"),
            search_root_candidate_build_city_count=_optional_int(
                payload, "search_root_candidate_build_city_count"
            ),
            search_root_candidate_build_road_count=_optional_int(
                payload, "search_root_candidate_build_road_count"
            ),
            search_root_candidate_build_building_count=_optional_int(
                payload, "search_root_candidate_build_building_count"
            ),
            search_root_candidate_research_tech_count=_optional_int(
                payload, "search_root_candidate_research_tech_count"
            ),
            search_root_candidate_skip_count=_optional_int(
                payload, "search_root_candidate_skip_count"
            ),
            search_nodes_expanded=_optional_int(payload, "search_nodes_expanded"),
            search_candidates_considered=_optional_int(payload, "search_candidates_considered"),
            search_leaf_count=_optional_int(payload, "search_leaf_count"),
            search_best_value=_optional_int(payload, "search_best_value"),
            search_value_components=_mapping_of_ints(payload, "search_value_components"),
            search_sequence_adjustment=_optional_int(payload, "search_sequence_adjustment"),
            search_dominant_pressure=_optional_str(payload, "search_dominant_pressure"),
            search_dominant_pressure_value=_optional_int(payload, "search_dominant_pressure_value"),
            search_risk_pressure_total=_optional_int(payload, "search_risk_pressure_total"),
            search_is_risk_dominated=_optional_bool(payload, "search_is_risk_dominated"),
            search_is_sequence_adjusted=_optional_bool(payload, "search_is_sequence_adjusted"),
            search_best_score_total=_optional_int(payload, "search_best_score_total"),
            search_best_connected_city_count=_optional_int(
                payload, "search_best_connected_city_count"
            ),
            search_best_isolated_city_count=_optional_int(
                payload, "search_best_isolated_city_count"
            ),
            search_best_starving_network_count=_optional_int(
                payload, "search_best_starving_network_count"
            ),
            search_best_network_count=_optional_int(payload, "search_best_network_count"),
            search_best_largest_network_size=_optional_int(
                payload, "search_best_largest_network_size"
            ),
            search_best_total_food=_optional_int(payload, "search_best_total_food"),
            search_best_total_wood=_optional_int(payload, "search_best_total_wood"),
            search_best_total_ore=_optional_int(payload, "search_best_total_ore"),
            search_best_total_science=_optional_int(payload, "search_best_total_science"),
            search_best_food_pressure=_optional_int(payload, "search_best_food_pressure"),
            search_best_starving_turns=_optional_int(payload, "search_best_starving_turns"),
            search_best_sequence=[
                RecordSearchActionSnapshot.from_dict(item)
                for item in _list_of_dicts(payload, "search_best_sequence")
            ],
            search_root_chosen_rank=_optional_int(payload, "search_root_chosen_rank"),
            search_root_chosen_value=_optional_int(payload, "search_root_chosen_value"),
            search_root_best_value=_optional_int(payload, "search_root_best_value"),
            search_root_value_margin=_optional_int(payload, "search_root_value_margin"),
            search_root_best_action_type=_optional_str(payload, "search_root_best_action_type"),
            search_root_chosen_action_type=_optional_str(payload, "search_root_chosen_action_type"),
            search_root_best_build_city_value=_optional_int(
                payload, "search_root_best_build_city_value"
            ),
            search_root_best_build_road_value=_optional_int(
                payload, "search_root_best_build_road_value"
            ),
            search_root_best_build_building_value=_optional_int(
                payload, "search_root_best_build_building_value"
            ),
            search_root_best_research_tech_value=_optional_int(
                payload, "search_root_best_research_tech_value"
            ),
            search_root_best_skip_value=_optional_int(payload, "search_root_best_skip_value"),
            search_root_candidate_cut_ratio=_optional_float(
                payload, "search_root_candidate_cut_ratio"
            ),
            search_root_safe_city_candidate_count=_optional_int(
                payload, "search_root_safe_city_candidate_count"
            ),
            search_root_effective_connection_road_candidate_count=_optional_int(
                payload, "search_root_effective_connection_road_candidate_count"
            ),
            search_root_rescue_candidate_count=_optional_int(
                payload, "search_root_rescue_candidate_count"
            ),
            search_root_effective_city_candidate_count=_optional_int(
                payload, "search_root_effective_city_candidate_count"
            ),
            search_root_redundant_road_candidate_count=_optional_int(
                payload, "search_root_redundant_road_candidate_count"
            ),
            search_root_high_roi_building_candidate_count=_optional_int(
                payload, "search_root_high_roi_building_candidate_count"
            ),
            search_root_gated_candidate_count=_optional_int(
                payload, "search_root_gated_candidate_count"
            ),
            search_bridge_candidate_count=_optional_int(payload, "search_bridge_candidate_count"),
            search_bridge_min_steps=_optional_int(payload, "search_bridge_min_steps"),
            search_bridge_progress_after_first_step=_optional_int(
                payload, "search_bridge_progress_after_first_step"
            ),
            search_delta_starving_network_count=_optional_int(
                payload, "search_delta_starving_network_count"
            ),
            search_delta_food_pressure=_optional_int(payload, "search_delta_food_pressure"),
            search_delta_isolated_city_count=_optional_int(
                payload, "search_delta_isolated_city_count"
            ),
            search_delta_network_count=_optional_int(payload, "search_delta_network_count"),
            search_delta_connected_city_count=_optional_int(
                payload, "search_delta_connected_city_count"
            ),
            search_delta_road_overbuild=_optional_int(payload, "search_delta_road_overbuild"),
            search_delta_worst_network_food_pressure=_optional_int(
                payload, "search_delta_worst_network_food_pressure"
            ),
            search_delta_min_network_food=_optional_int(payload, "search_delta_min_network_food"),
            search_road_merges_networks=_optional_bool(payload, "search_road_merges_networks"),
            search_road_connected_city_delta=_optional_int(
                payload, "search_road_connected_city_delta"
            ),
            search_road_is_redundant=_optional_bool(payload, "search_road_is_redundant"),
            search_road_after_full_connectivity=_optional_bool(
                payload, "search_road_after_full_connectivity"
            ),
            search_greedy_action_type=_optional_str(payload, "search_greedy_action_type"),
            search_matches_greedy_action=_optional_bool(payload, "search_matches_greedy_action"),
            search_greedy_action_in_root_candidates=_optional_bool(
                payload, "search_greedy_action_in_root_candidates"
            ),
            search_greedy_action_root_rank=_optional_int(payload, "search_greedy_action_root_rank"),
            search_greedy_action_root_value=_optional_int(
                payload, "search_greedy_action_root_value"
            ),
            search_greedy_action_root_value_margin=_optional_int(
                payload, "search_greedy_action_root_value_margin"
            ),
            search_chosen_value_delta_vs_greedy_action=_optional_int(
                payload, "search_chosen_value_delta_vs_greedy_action"
            ),
            search_chosen_city_site_score=_optional_int(payload, "search_chosen_city_site_score"),
            search_greedy_city_site_score=_optional_int(payload, "search_greedy_city_site_score"),
            search_chosen_city_site_score_delta_vs_greedy=_optional_int(
                payload, "search_chosen_city_site_score_delta_vs_greedy"
            ),
            search_chosen_city_resource_ring_bonus=_optional_int(
                payload, "search_chosen_city_resource_ring_bonus"
            ),
            search_chosen_city_food_balance=_optional_int(
                payload, "search_chosen_city_food_balance"
            ),
            search_chosen_city_total_yield=_optional_int(payload, "search_chosen_city_total_yield"),
            search_chosen_city_river_access=_optional_bool(
                payload, "search_chosen_city_river_access"
            ),
            search_chosen_city_forest_neighbors=_optional_int(
                payload, "search_chosen_city_forest_neighbors"
            ),
            search_chosen_city_mountain_neighbors=_optional_int(
                payload, "search_chosen_city_mountain_neighbors"
            ),
            search_chosen_city_river_neighbors=_optional_int(
                payload, "search_chosen_city_river_neighbors"
            ),
            search_chosen_city_plain_neighbors=_optional_int(
                payload, "search_chosen_city_plain_neighbors"
            ),
            search_chosen_city_occupied_neighbors=_optional_int(
                payload, "search_chosen_city_occupied_neighbors"
            ),
            search_chosen_city_distance_to_network=_optional_int(
                payload, "search_chosen_city_distance_to_network"
            ),
            search_greedy_city_food_balance=_optional_int(
                payload, "search_greedy_city_food_balance"
            ),
            search_greedy_city_total_yield=_optional_int(payload, "search_greedy_city_total_yield"),
            search_greedy_city_river_access=_optional_bool(
                payload, "search_greedy_city_river_access"
            ),
            search_greedy_city_forest_neighbors=_optional_int(
                payload, "search_greedy_city_forest_neighbors"
            ),
            search_greedy_city_mountain_neighbors=_optional_int(
                payload, "search_greedy_city_mountain_neighbors"
            ),
            search_greedy_city_river_neighbors=_optional_int(
                payload, "search_greedy_city_river_neighbors"
            ),
            search_greedy_city_plain_neighbors=_optional_int(
                payload, "search_greedy_city_plain_neighbors"
            ),
            search_greedy_city_occupied_neighbors=_optional_int(
                payload, "search_greedy_city_occupied_neighbors"
            ),
            search_greedy_city_distance_to_network=_optional_int(
                payload, "search_greedy_city_distance_to_network"
            ),
            search_greedy_city_resource_ring_bonus=_optional_int(
                payload, "search_greedy_city_resource_ring_bonus"
            ),
            search_min_network_food_after_action=_optional_int(
                payload, "search_min_network_food_after_action"
            ),
            search_worst_network_food_pressure_after_action=_optional_int(
                payload, "search_worst_network_food_pressure_after_action"
            ),
            search_food_surplus_network_count_after_action=_optional_int(
                payload, "search_food_surplus_network_count_after_action"
            ),
            search_food_deficit_network_count_after_action=_optional_int(
                payload, "search_food_deficit_network_count_after_action"
            ),
            search_greedy_after_score_total=_optional_int(
                payload, "search_greedy_after_score_total"
            ),
            search_greedy_after_starving_network_count=_optional_int(
                payload, "search_greedy_after_starving_network_count"
            ),
            search_greedy_after_food_pressure=_optional_int(
                payload, "search_greedy_after_food_pressure"
            ),
            search_greedy_after_min_network_food=_optional_int(
                payload, "search_greedy_after_min_network_food"
            ),
            search_greedy_after_network_count=_optional_int(
                payload, "search_greedy_after_network_count"
            ),
            search_greedy_after_connected_city_count=_optional_int(
                payload, "search_greedy_after_connected_city_count"
            ),
            search_greedy_after_isolated_city_count=_optional_int(
                payload, "search_greedy_after_isolated_city_count"
            ),
            search_selected_after_score_total=_optional_int(
                payload, "search_selected_after_score_total"
            ),
            search_selected_after_starving_network_count=_optional_int(
                payload, "search_selected_after_starving_network_count"
            ),
            search_selected_after_food_pressure=_optional_int(
                payload, "search_selected_after_food_pressure"
            ),
            search_selected_after_min_network_food=_optional_int(
                payload, "search_selected_after_min_network_food"
            ),
            search_selected_after_network_count=_optional_int(
                payload, "search_selected_after_network_count"
            ),
            search_selected_after_connected_city_count=_optional_int(
                payload, "search_selected_after_connected_city_count"
            ),
            search_selected_after_isolated_city_count=_optional_int(
                payload, "search_selected_after_isolated_city_count"
            ),
            search_simulation_cache_hits=_optional_int(payload, "search_simulation_cache_hits"),
            search_simulation_cache_misses=_optional_int(payload, "search_simulation_cache_misses"),
            search_profile_city_count=_optional_int(payload, "search_profile_city_count"),
            search_profile_target_city_count=_optional_int(
                payload, "search_profile_target_city_count"
            ),
            search_profile_expansion_deficit=_optional_int(
                payload, "search_profile_expansion_deficit"
            ),
            search_profile_safe_expansion_deficit=_optional_int(
                payload, "search_profile_safe_expansion_deficit"
            ),
            search_profile_network_count=_optional_int(payload, "search_profile_network_count"),
            search_profile_connected_city_count=_optional_int(
                payload, "search_profile_connected_city_count"
            ),
            search_profile_isolated_city_count=_optional_int(
                payload, "search_profile_isolated_city_count"
            ),
            search_profile_starving_network_count=_optional_int(
                payload, "search_profile_starving_network_count"
            ),
            search_profile_food_pressure=_optional_int(payload, "search_profile_food_pressure"),
            search_profile_road_overbuild=_optional_int(payload, "search_profile_road_overbuild"),
            search_profile_fill_count=_optional_int(payload, "search_profile_fill_count"),
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
        if self.decision_time_ms is not None:
            result["decision_time_ms"] = self.decision_time_ms
        if self.greedy_stage is not None:
            result["greedy_stage"] = self.greedy_stage
        if self.greedy_priority is not None:
            result["greedy_priority"] = self.greedy_priority
        if self.greedy_best_action_type is not None:
            result["greedy_best_action_type"] = self.greedy_best_action_type
        if self.greedy_best_score is not None:
            result["greedy_best_score"] = self.greedy_best_score
        if self.greedy_best_delta_score is not None:
            result["greedy_best_delta_score"] = self.greedy_best_delta_score
        if self.greedy_food_pressure is not None:
            result["greedy_food_pressure"] = self.greedy_food_pressure
        if self.greedy_starving_networks is not None:
            result["greedy_starving_networks"] = self.greedy_starving_networks
        if self.greedy_connected_cities is not None:
            result["greedy_connected_cities"] = self.greedy_connected_cities
        if self.greedy_total_food is not None:
            result["greedy_total_food"] = self.greedy_total_food
        if self.greedy_network_count is not None:
            result["greedy_network_count"] = self.greedy_network_count
        if self.greedy_global_starving_delta is not None:
            result["greedy_global_starving_delta"] = self.greedy_global_starving_delta
        if self.greedy_global_network_delta is not None:
            result["greedy_global_network_delta"] = self.greedy_global_network_delta
        if self.greedy_global_isolation_delta is not None:
            result["greedy_global_isolation_delta"] = self.greedy_global_isolation_delta
        if self.greedy_rescue_effective is not None:
            result["greedy_rescue_effective"] = self.greedy_rescue_effective
        if self.greedy_escape_mode is not None:
            result["greedy_escape_mode"] = self.greedy_escape_mode
        if self.greedy_escape_reason is not None:
            result["greedy_escape_reason"] = self.greedy_escape_reason
        if self.greedy_food_rescue_stalled is not None:
            result["greedy_food_rescue_stalled"] = self.greedy_food_rescue_stalled
        if self.greedy_food_rescue_chain is not None:
            result["greedy_food_rescue_chain"] = self.greedy_food_rescue_chain
        if self.greedy_fill_reopen_reason is not None:
            result["greedy_fill_reopen_reason"] = self.greedy_fill_reopen_reason
        if self.greedy_best_connection_steps is not None:
            result["greedy_best_connection_steps"] = self.greedy_best_connection_steps
        if self.greedy_best_future_network_starving is not None:
            result["greedy_best_future_network_starving"] = self.greedy_best_future_network_starving
        if self.greedy_score_breakdown:
            result["greedy_score_breakdown"] = self.greedy_score_breakdown
        if self.greedy_best_site_budget:
            result["greedy_best_site_budget"] = self.greedy_best_site_budget
        if self.greedy_best_future_network_budget:
            result["greedy_best_future_network_budget"] = self.greedy_best_future_network_budget
        if self.random_type_weights:
            result["random_type_weights"] = self.random_type_weights
        if self.search_mode is not None:
            result["search_mode"] = self.search_mode
        if self.search_depth is not None:
            result["search_depth"] = self.search_depth
        if self.search_actual_depth is not None:
            result["search_actual_depth"] = self.search_actual_depth
        if self.search_base_depth is not None:
            result["search_base_depth"] = self.search_base_depth
        if self.search_max_depth is not None:
            result["search_max_depth"] = self.search_max_depth
        if self.search_depth_reason is not None:
            result["search_depth_reason"] = self.search_depth_reason
        if self.search_deep_search_enabled is not None:
            result["search_deep_search_enabled"] = self.search_deep_search_enabled
        if self.search_planning_mode is not None:
            result["search_planning_mode"] = self.search_planning_mode
        if self.search_planning_reason is not None:
            result["search_planning_reason"] = self.search_planning_reason
        if self.search_overrode_greedy is not None:
            result["search_overrode_greedy"] = self.search_overrode_greedy
        if self.search_intervention_trigger is not None:
            result["search_intervention_trigger"] = self.search_intervention_trigger
        if self.search_probe_accepted_reason is not None:
            result["search_probe_accepted_reason"] = self.search_probe_accepted_reason
        if self.search_probe_rejected_reason is not None:
            result["search_probe_rejected_reason"] = self.search_probe_rejected_reason
        if self.search_beam_width is not None:
            result["search_beam_width"] = self.search_beam_width
        if self.search_candidate_limit is not None:
            result["search_candidate_limit"] = self.search_candidate_limit
        if self.search_root_legal_build_city_count is not None:
            result["search_root_legal_build_city_count"] = self.search_root_legal_build_city_count
        if self.search_root_legal_build_road_count is not None:
            result["search_root_legal_build_road_count"] = self.search_root_legal_build_road_count
        if self.search_root_legal_build_building_count is not None:
            result["search_root_legal_build_building_count"] = (
                self.search_root_legal_build_building_count
            )
        if self.search_root_legal_research_tech_count is not None:
            result["search_root_legal_research_tech_count"] = (
                self.search_root_legal_research_tech_count
            )
        if self.search_root_legal_skip_count is not None:
            result["search_root_legal_skip_count"] = self.search_root_legal_skip_count
        if self.search_root_candidate_build_city_count is not None:
            result["search_root_candidate_build_city_count"] = (
                self.search_root_candidate_build_city_count
            )
        if self.search_root_candidate_build_road_count is not None:
            result["search_root_candidate_build_road_count"] = (
                self.search_root_candidate_build_road_count
            )
        if self.search_root_candidate_build_building_count is not None:
            result["search_root_candidate_build_building_count"] = (
                self.search_root_candidate_build_building_count
            )
        if self.search_root_candidate_research_tech_count is not None:
            result["search_root_candidate_research_tech_count"] = (
                self.search_root_candidate_research_tech_count
            )
        if self.search_root_candidate_skip_count is not None:
            result["search_root_candidate_skip_count"] = self.search_root_candidate_skip_count
        if self.search_nodes_expanded is not None:
            result["search_nodes_expanded"] = self.search_nodes_expanded
        if self.search_candidates_considered is not None:
            result["search_candidates_considered"] = self.search_candidates_considered
        if self.search_leaf_count is not None:
            result["search_leaf_count"] = self.search_leaf_count
        if self.search_best_value is not None:
            result["search_best_value"] = self.search_best_value
        if self.search_value_components:
            result["search_value_components"] = self.search_value_components
        if self.search_sequence_adjustment is not None:
            result["search_sequence_adjustment"] = self.search_sequence_adjustment
        if self.search_dominant_pressure is not None:
            result["search_dominant_pressure"] = self.search_dominant_pressure
        if self.search_dominant_pressure_value is not None:
            result["search_dominant_pressure_value"] = self.search_dominant_pressure_value
        if self.search_risk_pressure_total is not None:
            result["search_risk_pressure_total"] = self.search_risk_pressure_total
        if self.search_is_risk_dominated is not None:
            result["search_is_risk_dominated"] = self.search_is_risk_dominated
        if self.search_is_sequence_adjusted is not None:
            result["search_is_sequence_adjusted"] = self.search_is_sequence_adjusted
        if self.search_best_score_total is not None:
            result["search_best_score_total"] = self.search_best_score_total
        if self.search_best_connected_city_count is not None:
            result["search_best_connected_city_count"] = self.search_best_connected_city_count
        if self.search_best_isolated_city_count is not None:
            result["search_best_isolated_city_count"] = self.search_best_isolated_city_count
        if self.search_best_starving_network_count is not None:
            result["search_best_starving_network_count"] = self.search_best_starving_network_count
        if self.search_best_network_count is not None:
            result["search_best_network_count"] = self.search_best_network_count
        if self.search_best_largest_network_size is not None:
            result["search_best_largest_network_size"] = self.search_best_largest_network_size
        if self.search_best_total_food is not None:
            result["search_best_total_food"] = self.search_best_total_food
        if self.search_best_total_wood is not None:
            result["search_best_total_wood"] = self.search_best_total_wood
        if self.search_best_total_ore is not None:
            result["search_best_total_ore"] = self.search_best_total_ore
        if self.search_best_total_science is not None:
            result["search_best_total_science"] = self.search_best_total_science
        if self.search_best_food_pressure is not None:
            result["search_best_food_pressure"] = self.search_best_food_pressure
        if self.search_best_starving_turns is not None:
            result["search_best_starving_turns"] = self.search_best_starving_turns
        if self.search_depth is not None or self.search_best_sequence:
            result["search_best_sequence"] = [
                action.to_dict() for action in self.search_best_sequence
            ]
        if self.search_root_chosen_rank is not None:
            result["search_root_chosen_rank"] = self.search_root_chosen_rank
        if self.search_root_chosen_value is not None:
            result["search_root_chosen_value"] = self.search_root_chosen_value
        if self.search_root_best_value is not None:
            result["search_root_best_value"] = self.search_root_best_value
        if self.search_root_value_margin is not None:
            result["search_root_value_margin"] = self.search_root_value_margin
        if self.search_root_best_action_type is not None:
            result["search_root_best_action_type"] = self.search_root_best_action_type
        if self.search_root_chosen_action_type is not None:
            result["search_root_chosen_action_type"] = self.search_root_chosen_action_type
        if self.search_root_best_build_city_value is not None:
            result["search_root_best_build_city_value"] = self.search_root_best_build_city_value
        if self.search_root_best_build_road_value is not None:
            result["search_root_best_build_road_value"] = self.search_root_best_build_road_value
        if self.search_root_best_build_building_value is not None:
            result["search_root_best_build_building_value"] = (
                self.search_root_best_build_building_value
            )
        if self.search_root_best_research_tech_value is not None:
            result["search_root_best_research_tech_value"] = (
                self.search_root_best_research_tech_value
            )
        if self.search_root_best_skip_value is not None:
            result["search_root_best_skip_value"] = self.search_root_best_skip_value
        if self.search_root_candidate_cut_ratio is not None:
            result["search_root_candidate_cut_ratio"] = self.search_root_candidate_cut_ratio
        if self.search_root_safe_city_candidate_count is not None:
            result["search_root_safe_city_candidate_count"] = (
                self.search_root_safe_city_candidate_count
            )
        if self.search_root_effective_connection_road_candidate_count is not None:
            result["search_root_effective_connection_road_candidate_count"] = (
                self.search_root_effective_connection_road_candidate_count
            )
        if self.search_root_rescue_candidate_count is not None:
            result["search_root_rescue_candidate_count"] = self.search_root_rescue_candidate_count
        if self.search_root_effective_city_candidate_count is not None:
            result["search_root_effective_city_candidate_count"] = (
                self.search_root_effective_city_candidate_count
            )
        if self.search_root_redundant_road_candidate_count is not None:
            result["search_root_redundant_road_candidate_count"] = (
                self.search_root_redundant_road_candidate_count
            )
        if self.search_root_high_roi_building_candidate_count is not None:
            result["search_root_high_roi_building_candidate_count"] = (
                self.search_root_high_roi_building_candidate_count
            )
        if self.search_root_gated_candidate_count is not None:
            result["search_root_gated_candidate_count"] = self.search_root_gated_candidate_count
        if self.search_bridge_candidate_count is not None:
            result["search_bridge_candidate_count"] = self.search_bridge_candidate_count
        if self.search_bridge_min_steps is not None:
            result["search_bridge_min_steps"] = self.search_bridge_min_steps
        if self.search_bridge_progress_after_first_step is not None:
            result["search_bridge_progress_after_first_step"] = (
                self.search_bridge_progress_after_first_step
            )
        if self.search_delta_starving_network_count is not None:
            result["search_delta_starving_network_count"] = self.search_delta_starving_network_count
        if self.search_delta_food_pressure is not None:
            result["search_delta_food_pressure"] = self.search_delta_food_pressure
        if self.search_delta_isolated_city_count is not None:
            result["search_delta_isolated_city_count"] = self.search_delta_isolated_city_count
        if self.search_delta_network_count is not None:
            result["search_delta_network_count"] = self.search_delta_network_count
        if self.search_delta_connected_city_count is not None:
            result["search_delta_connected_city_count"] = self.search_delta_connected_city_count
        if self.search_delta_road_overbuild is not None:
            result["search_delta_road_overbuild"] = self.search_delta_road_overbuild
        if self.search_delta_worst_network_food_pressure is not None:
            result["search_delta_worst_network_food_pressure"] = (
                self.search_delta_worst_network_food_pressure
            )
        if self.search_delta_min_network_food is not None:
            result["search_delta_min_network_food"] = self.search_delta_min_network_food
        if self.search_road_merges_networks is not None:
            result["search_road_merges_networks"] = self.search_road_merges_networks
        if self.search_road_connected_city_delta is not None:
            result["search_road_connected_city_delta"] = self.search_road_connected_city_delta
        if self.search_road_is_redundant is not None:
            result["search_road_is_redundant"] = self.search_road_is_redundant
        if self.search_road_after_full_connectivity is not None:
            result["search_road_after_full_connectivity"] = self.search_road_after_full_connectivity
        if self.search_greedy_action_type is not None:
            result["search_greedy_action_type"] = self.search_greedy_action_type
        if self.search_matches_greedy_action is not None:
            result["search_matches_greedy_action"] = self.search_matches_greedy_action
        if self.search_greedy_action_in_root_candidates is not None:
            result["search_greedy_action_in_root_candidates"] = (
                self.search_greedy_action_in_root_candidates
            )
        if self.search_greedy_action_root_rank is not None:
            result["search_greedy_action_root_rank"] = self.search_greedy_action_root_rank
        if self.search_greedy_action_root_value is not None:
            result["search_greedy_action_root_value"] = self.search_greedy_action_root_value
        if self.search_greedy_action_root_value_margin is not None:
            result["search_greedy_action_root_value_margin"] = (
                self.search_greedy_action_root_value_margin
            )
        if self.search_chosen_value_delta_vs_greedy_action is not None:
            result["search_chosen_value_delta_vs_greedy_action"] = (
                self.search_chosen_value_delta_vs_greedy_action
            )
        if self.search_chosen_city_site_score is not None:
            result["search_chosen_city_site_score"] = self.search_chosen_city_site_score
        if self.search_greedy_city_site_score is not None:
            result["search_greedy_city_site_score"] = self.search_greedy_city_site_score
        if self.search_chosen_city_site_score_delta_vs_greedy is not None:
            result["search_chosen_city_site_score_delta_vs_greedy"] = (
                self.search_chosen_city_site_score_delta_vs_greedy
            )
        if self.search_chosen_city_resource_ring_bonus is not None:
            result["search_chosen_city_resource_ring_bonus"] = (
                self.search_chosen_city_resource_ring_bonus
            )
        if self.search_chosen_city_food_balance is not None:
            result["search_chosen_city_food_balance"] = self.search_chosen_city_food_balance
        if self.search_chosen_city_total_yield is not None:
            result["search_chosen_city_total_yield"] = self.search_chosen_city_total_yield
        if self.search_chosen_city_river_access is not None:
            result["search_chosen_city_river_access"] = self.search_chosen_city_river_access
        if self.search_chosen_city_forest_neighbors is not None:
            result["search_chosen_city_forest_neighbors"] = self.search_chosen_city_forest_neighbors
        if self.search_chosen_city_mountain_neighbors is not None:
            result["search_chosen_city_mountain_neighbors"] = (
                self.search_chosen_city_mountain_neighbors
            )
        if self.search_chosen_city_river_neighbors is not None:
            result["search_chosen_city_river_neighbors"] = self.search_chosen_city_river_neighbors
        if self.search_chosen_city_plain_neighbors is not None:
            result["search_chosen_city_plain_neighbors"] = self.search_chosen_city_plain_neighbors
        if self.search_chosen_city_occupied_neighbors is not None:
            result["search_chosen_city_occupied_neighbors"] = (
                self.search_chosen_city_occupied_neighbors
            )
        if self.search_chosen_city_distance_to_network is not None:
            result["search_chosen_city_distance_to_network"] = (
                self.search_chosen_city_distance_to_network
            )
        if self.search_greedy_city_food_balance is not None:
            result["search_greedy_city_food_balance"] = self.search_greedy_city_food_balance
        if self.search_greedy_city_total_yield is not None:
            result["search_greedy_city_total_yield"] = self.search_greedy_city_total_yield
        if self.search_greedy_city_river_access is not None:
            result["search_greedy_city_river_access"] = self.search_greedy_city_river_access
        if self.search_greedy_city_forest_neighbors is not None:
            result["search_greedy_city_forest_neighbors"] = self.search_greedy_city_forest_neighbors
        if self.search_greedy_city_mountain_neighbors is not None:
            result["search_greedy_city_mountain_neighbors"] = (
                self.search_greedy_city_mountain_neighbors
            )
        if self.search_greedy_city_river_neighbors is not None:
            result["search_greedy_city_river_neighbors"] = self.search_greedy_city_river_neighbors
        if self.search_greedy_city_plain_neighbors is not None:
            result["search_greedy_city_plain_neighbors"] = self.search_greedy_city_plain_neighbors
        if self.search_greedy_city_occupied_neighbors is not None:
            result["search_greedy_city_occupied_neighbors"] = (
                self.search_greedy_city_occupied_neighbors
            )
        if self.search_greedy_city_distance_to_network is not None:
            result["search_greedy_city_distance_to_network"] = (
                self.search_greedy_city_distance_to_network
            )
        if self.search_greedy_city_resource_ring_bonus is not None:
            result["search_greedy_city_resource_ring_bonus"] = (
                self.search_greedy_city_resource_ring_bonus
            )
        if self.search_min_network_food_after_action is not None:
            result["search_min_network_food_after_action"] = (
                self.search_min_network_food_after_action
            )
        if self.search_worst_network_food_pressure_after_action is not None:
            result["search_worst_network_food_pressure_after_action"] = (
                self.search_worst_network_food_pressure_after_action
            )
        if self.search_food_surplus_network_count_after_action is not None:
            result["search_food_surplus_network_count_after_action"] = (
                self.search_food_surplus_network_count_after_action
            )
        if self.search_food_deficit_network_count_after_action is not None:
            result["search_food_deficit_network_count_after_action"] = (
                self.search_food_deficit_network_count_after_action
            )
        if self.search_greedy_after_score_total is not None:
            result["search_greedy_after_score_total"] = self.search_greedy_after_score_total
        if self.search_greedy_after_starving_network_count is not None:
            result["search_greedy_after_starving_network_count"] = (
                self.search_greedy_after_starving_network_count
            )
        if self.search_greedy_after_food_pressure is not None:
            result["search_greedy_after_food_pressure"] = self.search_greedy_after_food_pressure
        if self.search_greedy_after_min_network_food is not None:
            result["search_greedy_after_min_network_food"] = (
                self.search_greedy_after_min_network_food
            )
        if self.search_greedy_after_network_count is not None:
            result["search_greedy_after_network_count"] = self.search_greedy_after_network_count
        if self.search_greedy_after_connected_city_count is not None:
            result["search_greedy_after_connected_city_count"] = (
                self.search_greedy_after_connected_city_count
            )
        if self.search_greedy_after_isolated_city_count is not None:
            result["search_greedy_after_isolated_city_count"] = (
                self.search_greedy_after_isolated_city_count
            )
        if self.search_selected_after_score_total is not None:
            result["search_selected_after_score_total"] = self.search_selected_after_score_total
        if self.search_selected_after_starving_network_count is not None:
            result["search_selected_after_starving_network_count"] = (
                self.search_selected_after_starving_network_count
            )
        if self.search_selected_after_food_pressure is not None:
            result["search_selected_after_food_pressure"] = self.search_selected_after_food_pressure
        if self.search_selected_after_min_network_food is not None:
            result["search_selected_after_min_network_food"] = (
                self.search_selected_after_min_network_food
            )
        if self.search_selected_after_network_count is not None:
            result["search_selected_after_network_count"] = self.search_selected_after_network_count
        if self.search_selected_after_connected_city_count is not None:
            result["search_selected_after_connected_city_count"] = (
                self.search_selected_after_connected_city_count
            )
        if self.search_selected_after_isolated_city_count is not None:
            result["search_selected_after_isolated_city_count"] = (
                self.search_selected_after_isolated_city_count
            )
        if self.search_simulation_cache_hits is not None:
            result["search_simulation_cache_hits"] = self.search_simulation_cache_hits
        if self.search_simulation_cache_misses is not None:
            result["search_simulation_cache_misses"] = self.search_simulation_cache_misses
        if self.search_profile_city_count is not None:
            result["search_profile_city_count"] = self.search_profile_city_count
        if self.search_profile_target_city_count is not None:
            result["search_profile_target_city_count"] = self.search_profile_target_city_count
        if self.search_profile_expansion_deficit is not None:
            result["search_profile_expansion_deficit"] = self.search_profile_expansion_deficit
        if self.search_profile_safe_expansion_deficit is not None:
            result["search_profile_safe_expansion_deficit"] = (
                self.search_profile_safe_expansion_deficit
            )
        if self.search_profile_network_count is not None:
            result["search_profile_network_count"] = self.search_profile_network_count
        if self.search_profile_connected_city_count is not None:
            result["search_profile_connected_city_count"] = self.search_profile_connected_city_count
        if self.search_profile_isolated_city_count is not None:
            result["search_profile_isolated_city_count"] = self.search_profile_isolated_city_count
        if self.search_profile_starving_network_count is not None:
            result["search_profile_starving_network_count"] = (
                self.search_profile_starving_network_count
            )
        if self.search_profile_food_pressure is not None:
            result["search_profile_food_pressure"] = self.search_profile_food_pressure
        if self.search_profile_road_overbuild is not None:
            result["search_profile_road_overbuild"] = self.search_profile_road_overbuild
        if self.search_profile_fill_count is not None:
            result["search_profile_fill_count"] = self.search_profile_fill_count
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
            action_log=[RecordActionLogEntry.from_dict(item) for item in state.stats.action_log],
            turn_snapshots=[
                RecordTurnSnapshot.from_dict(item) for item in state.stats.turn_snapshots
            ],
            decision_contexts=[
                RecordDecisionContext.from_dict(item) for item in state.stats.decision_contexts
            ],
        )

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RecordEntry:
        mode = _require_str(payload, "mode")
        if mode not in {"play", "autoplay"}:
            raise ValueError(f"Invalid mode: {mode}")
        ai_type = _require_str(payload, "ai_type")
        if ai_type not in {"Human", "Greedy", "Random", "Search"}:
            raise ValueError(f"Invalid ai_type: {ai_type}")
        playback_mode = _require_str(payload, "playback_mode")
        if playback_mode not in {"", "normal", "speed"}:
            raise ValueError(f"Invalid playback_mode: {playback_mode}")
        return cls(
            record_id=_require_int(payload, "record_id"),
            timestamp=_require_str(payload, "timestamp"),
            game_version=_require_str(payload, "game_version"),
            mode=mode,
            ai_type=ai_type,
            custom_goal=_require_str(payload, "custom_goal"),
            playback_mode=playback_mode,
            seed=_require_int(payload, "seed"),
            map_size=_require_int(payload, "map_size"),
            map_difficulty=_require_str(payload, "map_difficulty"),
            turn_limit=_require_int(payload, "turn_limit"),
            actual_turns=_require_int(payload, "actual_turns"),
            final_score=_require_int(payload, "final_score"),
            city_count=_require_int(payload, "city_count"),
            building_count=_require_int(payload, "building_count"),
            tech_count=_require_int(payload, "tech_count"),
            food=_require_int(payload, "food"),
            wood=_require_int(payload, "wood"),
            ore=_require_int(payload, "ore"),
            science=_require_int(payload, "science"),
            build_city_count=_require_int(payload, "build_city_count"),
            build_road_count=_require_int(payload, "build_road_count"),
            build_farm_count=_require_int(payload, "build_farm_count"),
            build_lumber_mill_count=_require_int(payload, "build_lumber_mill_count"),
            build_mine_count=_require_int(payload, "build_mine_count"),
            build_library_count=_require_int(payload, "build_library_count"),
            research_agriculture_count=_require_int(payload, "research_agriculture_count"),
            research_logging_count=_require_int(payload, "research_logging_count"),
            research_mining_count=_require_int(payload, "research_mining_count"),
            research_education_count=_require_int(payload, "research_education_count"),
            skip_count=_require_int(payload, "skip_count"),
            decision_count=_require_int(payload, "decision_count"),
            decision_time_ms_total=_require_float(payload, "decision_time_ms_total"),
            decision_time_ms_avg=_require_float(payload, "decision_time_ms_avg"),
            decision_time_ms_max=_require_float(payload, "decision_time_ms_max"),
            turn_elapsed_ms_total=_require_float(payload, "turn_elapsed_ms_total"),
            turn_elapsed_ms_avg=_require_float(payload, "turn_elapsed_ms_avg"),
            turn_elapsed_ms_max=_require_float(payload, "turn_elapsed_ms_max"),
            session_elapsed_ms=_require_float(payload, "session_elapsed_ms"),
            final_map=[
                RecordTileSnapshot.from_dict(item) for item in _list_of_dicts(payload, "final_map")
            ],
            cities=[
                RecordCitySnapshot.from_dict(item) for item in _list_of_dicts(payload, "cities")
            ],
            roads=[RecordRoadSnapshot.from_dict(item) for item in _list_of_dicts(payload, "roads")],
            networks=[
                RecordNetworkSnapshot.from_dict(item)
                for item in _list_of_dicts(payload, "networks")
            ],
            action_log=[
                RecordActionLogEntry.from_dict(item)
                for item in _list_of_dicts(payload, "action_log")
            ],
            turn_snapshots=[
                RecordTurnSnapshot.from_dict(item)
                for item in _list_of_dicts(payload, "turn_snapshots")
            ],
            decision_contexts=[
                RecordDecisionContext.from_dict(item)
                for item in _list_of_dicts(payload, "decision_contexts")
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
            schema_version=_require_int(payload, "schema_version"),
            next_record_id=_require_int(payload, "next_record_id"),
            records=[RecordEntry.from_dict(item) for item in _list_of_dicts(payload, "records")],
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
    if state.config.policy_type is PolicyType.SEARCH:
        return "Search"
    return state.config.policy_type.value.title()
