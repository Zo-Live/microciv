"""Deterministic square-grid greedy policy."""

from __future__ import annotations

from microciv.ai.policy import Policy, get_legal_actions
from microciv.constants import BUILDING_COSTS, FOOD_CONSUMPTION_PER_CITY
from microciv.game.actions import Action
from microciv.game.enums import ActionType, BuildingType, ResourceType, TechType, TerrainType
from microciv.game.models import GameState
from microciv.game.networks import map_passable_coords_to_networks
from microciv.utils.grid import cardinal_neighbors, coord_sort_key, moore_neighbors

BUILDING_RESOURCE_TYPE: dict[BuildingType, ResourceType] = {
    BuildingType.FARM: ResourceType.FOOD,
    BuildingType.LUMBER_MILL: ResourceType.WOOD,
    BuildingType.MINE: ResourceType.ORE,
    BuildingType.LIBRARY: ResourceType.SCIENCE,
}

TECH_PRIORITY: tuple[TechType, ...] = (
    TechType.AGRICULTURE,
    TechType.EDUCATION,
    TechType.LOGGING,
    TechType.MINING,
)


class GreedyPolicy(Policy):
    """A deterministic rule-based policy used as the default benchmark."""

    def select_action(self, state: GameState) -> Action:
        legal_actions = get_legal_actions(state)
        if not legal_actions:
            return Action.skip()

        food_rescue = self._select_food_rescue_action(state, legal_actions)
        if food_rescue is not None:
            return food_rescue

        building_action = self._select_building_action(state, legal_actions)
        if building_action is not None:
            return building_action

        tech_action = self._select_tech_action(state, legal_actions)
        if tech_action is not None:
            return tech_action

        city_action = self._select_city_action(state, legal_actions)
        if city_action is not None:
            return city_action

        connective_road = self._select_connective_road_action(state, legal_actions)
        if connective_road is not None:
            return connective_road

        return Action.skip()

    def _select_food_rescue_action(
        self, state: GameState, legal_actions: list[Action]
    ) -> Action | None:
        dangerous_network_ids = {
            network_id
            for network_id, network in state.networks.items()
            if network.resources.food <= len(network.city_ids) * FOOD_CONSUMPTION_PER_CITY
        }
        if not dangerous_network_ids:
            return None

        farm_actions = [
            action
            for action in legal_actions
            if action.action_type is ActionType.BUILD_BUILDING
            and action.building_type is BuildingType.FARM
            and action.city_id is not None
            and state.cities[action.city_id].network_id in dangerous_network_ids
        ]
        if farm_actions:
            return min(farm_actions, key=lambda action: _building_action_key(state, action))

        rescue_city_actions = [
            action
            for action in legal_actions
            if action.action_type is ActionType.BUILD_CITY
            and action.coord is not None
            and _city_food_potential(state, action.coord) >= 4
        ]
        if rescue_city_actions:
            return min(
                rescue_city_actions, key=lambda action: _city_action_key(state, action.coord)
            )  # type: ignore[arg-type]

        agriculture_actions = [
            action
            for action in legal_actions
            if action.action_type is ActionType.RESEARCH_TECH
            and action.tech_type is TechType.AGRICULTURE
        ]
        if agriculture_actions:
            return min(agriculture_actions, key=lambda action: _research_action_key(state, action))

        return None

    def _select_connective_road_action(
        self, state: GameState, legal_actions: list[Action]
    ) -> Action | None:
        road_candidates = [
            action
            for action in legal_actions
            if action.action_type is ActionType.BUILD_ROAD and action.coord is not None
        ]
        if not road_candidates:
            return None

        passable_network_map = map_passable_coords_to_networks(state)
        best_action: Action | None = None
        best_key: tuple[int, int, tuple[int, int]] | None = None
        for action in road_candidates:
            assert action.coord is not None
            adjacent_network_ids = {
                passable_network_map[neighbor]
                for neighbor in cardinal_neighbors(action.coord)
                if neighbor in passable_network_map
            }
            merge_bonus = 100 if len(adjacent_network_ids) >= 2 else 0
            river_penalty = 15 if state.board[action.coord].base_terrain is TerrainType.RIVER else 0
            local_food = _count_adjacent_terrain(
                state, action.coord, TerrainType.PLAIN
            ) + _count_adjacent_terrain(state, action.coord, TerrainType.RIVER)
            road_score = merge_bonus + (local_food * 10) - river_penalty
            candidate_key = (-road_score, -len(adjacent_network_ids), coord_sort_key(action.coord))
            if best_key is None or candidate_key < best_key:
                best_key = candidate_key
                best_action = action
        if best_key is not None:
            return best_action
        return None

    def _select_city_action(self, state: GameState, legal_actions: list[Action]) -> Action | None:
        city_actions = [
            action
            for action in legal_actions
            if action.action_type is ActionType.BUILD_CITY and action.coord is not None
        ]
        if not city_actions:
            return None
        return min(city_actions, key=lambda action: _city_action_key(state, action.coord))  # type: ignore[arg-type]

    def _select_tech_action(self, state: GameState, legal_actions: list[Action]) -> Action | None:
        research_actions = [
            action
            for action in legal_actions
            if action.action_type is ActionType.RESEARCH_TECH
            and action.city_id is not None
            and action.tech_type is not None
        ]
        if not research_actions:
            return None

        for tech_type in TECH_PRIORITY:
            candidates = [action for action in research_actions if action.tech_type is tech_type]
            if candidates:
                return min(candidates, key=lambda action: _research_action_key(state, action))
        return None

    def _select_building_action(
        self, state: GameState, legal_actions: list[Action]
    ) -> Action | None:
        building_actions = [
            action
            for action in legal_actions
            if action.action_type is ActionType.BUILD_BUILDING
            and action.city_id is not None
            and action.building_type is not None
        ]
        if not building_actions:
            return None

        def action_key(action: Action) -> tuple[int, int, tuple[int, int]]:
            assert action.city_id is not None
            assert action.building_type is not None
            city = state.cities[action.city_id]
            network = state.networks[city.network_id]
            resource_type = BUILDING_RESOURCE_TYPE[action.building_type]
            shortage = network.resources.get(resource_type) - _building_shortage_budget(
                action.building_type
            )
            return (shortage, city.total_buildings, coord_sort_key(city.coord))

        return min(building_actions, key=action_key)


def _city_action_key(
    state: GameState, coord: tuple[int, int]
) -> tuple[int, int, int, tuple[int, int]]:
    food = _city_food_potential(state, coord)
    wood = _city_resource_potential(state, coord, TerrainType.FOREST)
    ore = _city_resource_potential(state, coord, TerrainType.MOUNTAIN)
    science = _city_resource_potential(state, coord, TerrainType.RIVER)
    connection_bonus = (
        1
        if any(
            state.board.get(neighbor) is not None
            and state.board[neighbor].occupant.value in {"city", "road"}
            for neighbor in cardinal_neighbors(coord)
        )
        else 0
    )
    score = (food * 4) + (wood * 3) + (ore * 2) + (science * 2) + (connection_bonus * 5)
    return (-score, -food, -wood, coord_sort_key(coord))


def _city_food_potential(state: GameState, coord: tuple[int, int]) -> int:
    score = 0
    for neighbor in moore_neighbors(coord):
        tile = state.board.get(neighbor)
        if tile is None or tile.occupant.value != "none":
            continue
        if tile.base_terrain is TerrainType.PLAIN:
            score += 2
        elif tile.base_terrain is TerrainType.RIVER:
            score += 1
    return score


def _city_resource_potential(state: GameState, coord: tuple[int, int], terrain: TerrainType) -> int:
    return sum(
        1
        for neighbor in moore_neighbors(coord)
        if (tile := state.board.get(neighbor)) is not None
        and tile.occupant.value == "none"
        and tile.base_terrain is terrain
    )


def _count_adjacent_terrain(
    state: GameState, coord: tuple[int, int], terrain_type: TerrainType
) -> int:
    return sum(
        1
        for neighbor in cardinal_neighbors(coord)
        if (tile := state.board.get(neighbor)) and tile.base_terrain is terrain_type
    )


def _research_action_key(state: GameState, action: Action) -> tuple[int, tuple[int, int], int]:
    assert action.city_id is not None
    city = state.cities[action.city_id]
    return (city.founded_turn, coord_sort_key(city.coord), city.city_id)


def _building_action_key(state: GameState, action: Action) -> tuple[int, tuple[int, int], int]:
    assert action.city_id is not None
    city = state.cities[action.city_id]
    return (city.total_buildings, coord_sort_key(city.coord), city.city_id)


def _building_shortage_budget(building_type: BuildingType) -> int:
    costs = BUILDING_COSTS[building_type]
    primary_type = BUILDING_RESOURCE_TYPE[building_type]
    return costs.get(primary_type, 0) * 2
