"""Action models and validation entrypoints."""

from __future__ import annotations

from dataclasses import dataclass

from microciv.constants import BUILDING_COSTS, BUILDING_LIMIT_PER_CITY, TECH_COSTS, TECH_UNLOCKS
from microciv.game.enums import ActionType, BuildingType, OccupantType, TechType, TerrainType
from microciv.game.models import GameState
from microciv.game.resources import choose_river_road_payment_network
from microciv.utils.grid import Coord, cardinal_neighbors, coord_sort_key

BUILDING_REQUIRED_TECH: dict[BuildingType, TechType] = {
    building_type: tech_type for tech_type, building_type in TECH_UNLOCKS.items()
}


@dataclass(frozen=True, slots=True)
class Action:
    """A user or AI-selected action."""

    action_type: ActionType
    coord: Coord | None = None
    city_id: int | None = None
    building_type: BuildingType | None = None
    tech_type: TechType | None = None

    @classmethod
    def build_city(cls, coord: Coord) -> Action:
        return cls(action_type=ActionType.BUILD_CITY, coord=coord)

    @classmethod
    def build_road(cls, coord: Coord) -> Action:
        return cls(action_type=ActionType.BUILD_ROAD, coord=coord)

    @classmethod
    def build_building(cls, city_id: int, building_type: BuildingType) -> Action:
        return cls(
            action_type=ActionType.BUILD_BUILDING, city_id=city_id, building_type=building_type
        )

    @classmethod
    def research_tech(cls, city_id: int, tech_type: TechType) -> Action:
        return cls(action_type=ActionType.RESEARCH_TECH, city_id=city_id, tech_type=tech_type)

    @classmethod
    def skip(cls) -> Action:
        return cls(action_type=ActionType.SKIP)


@dataclass(frozen=True, slots=True)
class ActionValidation:
    """Validation result for a proposed action."""

    is_valid: bool
    message: str = ""


def validate_action(state: GameState, action: Action) -> ActionValidation:
    """Validate an action against the current game state."""
    if state.is_game_over:
        return ActionValidation(False, "Game is already over")

    if action.action_type is ActionType.SKIP:
        return ActionValidation(True)
    if action.action_type is ActionType.BUILD_CITY:
        return _validate_build_city(state, action)
    if action.action_type is ActionType.BUILD_ROAD:
        return _validate_build_road(state, action)
    if action.action_type is ActionType.BUILD_BUILDING:
        return _validate_build_building(state, action)
    if action.action_type is ActionType.RESEARCH_TECH:
        return _validate_research_tech(state, action)
    return ActionValidation(False, "Unsupported action")


def list_legal_actions(state: GameState, *, include_skip: bool = True) -> list[Action]:
    """Return all currently legal actions in a deterministic order."""
    if state.is_game_over:
        return []

    actions: list[Action] = []

    for coord in sorted(state.board, key=coord_sort_key):
        action = Action.build_city(coord)
        if validate_action(state, action).is_valid:
            actions.append(action)

    for coord in sorted(state.board, key=coord_sort_key):
        action = Action.build_road(coord)
        if validate_action(state, action).is_valid:
            actions.append(action)

    for city_id in state.sorted_city_ids():
        for building_type in BuildingType:
            action = Action.build_building(city_id, building_type)
            if validate_action(state, action).is_valid:
                actions.append(action)

    for city_id in state.sorted_city_ids():
        for tech_type in TechType:
            action = Action.research_tech(city_id, tech_type)
            if validate_action(state, action).is_valid:
                actions.append(action)

    if include_skip:
        actions.append(Action.skip())

    return actions


def _validate_build_city(state: GameState, action: Action) -> ActionValidation:
    if action.coord is None:
        return ActionValidation(False, "Cannot build city here")
    tile = state.board.get(action.coord)
    if tile is None:
        return ActionValidation(False, "Cannot build city here")
    if tile.occupant is not OccupantType.NONE:
        return ActionValidation(False, "Cannot build city here")
    if tile.base_terrain in {TerrainType.RIVER, TerrainType.WASTELAND}:
        return ActionValidation(False, "Cannot build city here")
    return ActionValidation(True)


def _validate_build_road(state: GameState, action: Action) -> ActionValidation:
    if action.coord is None:
        return ActionValidation(False, "Cannot build road here")
    tile = state.board.get(action.coord)
    if tile is None or tile.occupant is not OccupantType.NONE:
        return ActionValidation(False, "Cannot build road here")

    if not any(
        (neighbor_tile := state.board.get(neighbor)) is not None
        and neighbor_tile.occupant in {OccupantType.CITY, OccupantType.ROAD}
        for neighbor in cardinal_neighbors(action.coord)
    ):
        return ActionValidation(False, "Road must connect to an existing city or road")

    if (
        tile.base_terrain is TerrainType.RIVER
        and choose_river_road_payment_network(state, action.coord) is None
    ):
        return ActionValidation(False, "Not enough resources")
    return ActionValidation(True)


def _validate_build_building(state: GameState, action: Action) -> ActionValidation:
    if action.city_id is None or action.building_type is None:
        return ActionValidation(False, "Cannot build here")
    city = state.cities.get(action.city_id)
    if city is None:
        return ActionValidation(False, "Cannot build here")
    network = state.networks.get(city.network_id)
    if network is None:
        return ActionValidation(False, "Cannot build here")
    if city.total_buildings >= BUILDING_LIMIT_PER_CITY:
        return ActionValidation(False, "Building limit reached")

    required_tech = BUILDING_REQUIRED_TECH[action.building_type]
    if required_tech not in network.unlocked_techs:
        return ActionValidation(False, "Technology not unlocked")
    if not network.resources.can_afford(BUILDING_COSTS[action.building_type]):
        return ActionValidation(False, "Not enough resources")
    return ActionValidation(True)


def _validate_research_tech(state: GameState, action: Action) -> ActionValidation:
    if action.city_id is None or action.tech_type is None:
        return ActionValidation(False, "Cannot research here")
    city = state.cities.get(action.city_id)
    if city is None:
        return ActionValidation(False, "Cannot research here")
    network = state.networks.get(city.network_id)
    if network is None:
        return ActionValidation(False, "Cannot research here")
    if action.tech_type in network.unlocked_techs:
        return ActionValidation(False, "Already researched")
    if network.resources.science < TECH_COSTS[action.tech_type]:
        return ActionValidation(False, "Not enough science")
    return ActionValidation(True)
