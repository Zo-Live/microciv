"""Deterministic phase-one baseline policy."""

from __future__ import annotations

from collections.abc import Iterable

from microciv.ai.policy import Policy, get_legal_actions, simulate_action
from microciv.constants import BASELINE_TARGET_BUFFERS, BUILDING_COSTS
from microciv.game.actions import Action
from microciv.game.enums import ActionType, BuildingType, OccupantType, ResourceType, TechType, TerrainType
from microciv.game.models import City, GameState, Network
from microciv.game.networks import map_passable_coords_to_networks
from microciv.utils.hexgrid import Coord, coord_sort_key, neighbors


BUILDING_RESOURCE_TYPE: dict[BuildingType, ResourceType] = {
    BuildingType.FARM: ResourceType.FOOD,
    BuildingType.LUMBER_MILL: ResourceType.WOOD,
    BuildingType.MINE: ResourceType.ORE,
    BuildingType.LIBRARY: ResourceType.SCIENCE,
}

BUILDING_RESOURCE_PRIORITY: dict[BuildingType, int] = {
    BuildingType.FARM: 4,
    BuildingType.LUMBER_MILL: 3,
    BuildingType.LIBRARY: 2,
    BuildingType.MINE: 1,
}

BUILDING_RESOURCE_TERRAINS: dict[BuildingType, tuple[TerrainType, ...]] = {
    BuildingType.FARM: (TerrainType.PLAIN, TerrainType.RIVER),
    BuildingType.LUMBER_MILL: (TerrainType.FOREST,),
    BuildingType.MINE: (TerrainType.MOUNTAIN,),
    BuildingType.LIBRARY: (TerrainType.RIVER,),
}

TECH_PRIORITY: tuple[TechType, ...] = (
    TechType.AGRICULTURE,
    TechType.EDUCATION,
    TechType.LOGGING,
    TechType.MINING,
)


class BaselinePolicy(Policy):
    """Phase-one rule-based baseline policy."""

    def select_action(self, state: GameState) -> Action:
        legal_actions = get_legal_actions(state)
        if not legal_actions:
            return Action.skip()

        dangerous_network_ids = _dangerous_network_ids(state)

        food_rescue_action = self._select_food_rescue_action(state, legal_actions, dangerous_network_ids)
        if food_rescue_action is not None:
            return food_rescue_action

        road_action = self._select_connective_road_action(state, legal_actions, dangerous_network_ids)
        if road_action is not None:
            return road_action

        city_action = self._select_city_action(state, legal_actions)
        if city_action is not None:
            return city_action

        tech_action = self._select_tech_action(state, legal_actions)
        if tech_action is not None:
            return tech_action

        building_action = self._select_gap_building_action(state, legal_actions)
        if building_action is not None:
            return building_action

        other_building_action = self._select_other_building_action(state, legal_actions)
        if other_building_action is not None:
            return other_building_action

        return Action.skip()

    def _select_food_rescue_action(
        self,
        state: GameState,
        legal_actions: list[Action],
        dangerous_network_ids: set[int],
    ) -> Action | None:
        if not dangerous_network_ids:
            return None

        road_action = self._select_connective_road_action(
            state,
            legal_actions,
            dangerous_network_ids,
            require_danger_connection=True,
        )
        if road_action is not None:
            return road_action

        farm_actions = [
            action
            for action in legal_actions
            if action.action_type is ActionType.BUILD_BUILDING
            and action.building_type is BuildingType.FARM
            and action.city_id is not None
            and state.cities[action.city_id].network_id in dangerous_network_ids
        ]
        best_farm = _select_building_action_by_city_order(state, farm_actions)
        if best_farm is not None:
            return best_farm

        connected_city_actions = [
            action
            for action in legal_actions
            if action.action_type is ActionType.BUILD_CITY
            and action.coord is not None
            and _build_city_connects_to_any_network(state, action.coord, dangerous_network_ids)
            and _city_food_potential(state, action.coord) > 0
        ]
        if connected_city_actions:
            return min(
                connected_city_actions,
                key=lambda action: _food_rescue_city_key(state, action.coord),  # type: ignore[arg-type]
            )

        agriculture_actions = [
            action
            for action in legal_actions
            if action.action_type is ActionType.RESEARCH_TECH
            and action.tech_type is TechType.AGRICULTURE
            and action.city_id is not None
            and state.cities[action.city_id].network_id in dangerous_network_ids
        ]
        if agriculture_actions:
            return min(agriculture_actions, key=lambda action: _research_action_key(state, action))

        return None

    def _select_connective_road_action(
        self,
        state: GameState,
        legal_actions: list[Action],
        dangerous_network_ids: set[int],
        *,
        require_danger_connection: bool = False,
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
        best_key: tuple[int, tuple[int, int]] | None = None

        for action in road_candidates:
            assert action.coord is not None
            adjacent_network_ids = {
                passable_network_map[neighbor]
                for neighbor in neighbors(action.coord)
                if neighbor in passable_network_map
            }
            if len(adjacent_network_ids) < 2:
                continue

            danger_bonus = (
                120
                if adjacent_network_ids & dangerous_network_ids
                and any(
                    network_id not in dangerous_network_ids and state.networks[network_id].resources.food >= 8
                    for network_id in adjacent_network_ids
                )
                else 0
            )
            if require_danger_connection and danger_bonus <= 0:
                continue

            merge_bonus = 60
            terrain_bonus = (
                3 * _count_adjacent_terrain(state, action.coord, TerrainType.PLAIN)
                + 2 * _count_adjacent_terrain(state, action.coord, TerrainType.RIVER)
            )
            cost_penalty = 4 if state.board[action.coord].base_terrain is TerrainType.RIVER else 0
            road_score = danger_bonus + merge_bonus + terrain_bonus - cost_penalty
            candidate_key = (-road_score, coord_sort_key(action.coord))
            if best_key is None or candidate_key < best_key:
                best_key = candidate_key
                best_action = action

        return best_action

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

        skip_state = simulate_action(state, Action.skip())
        forecast_delta = _forecast_network_deltas(state, turns=3)

        for tech_type in TECH_PRIORITY:
            candidates: list[Action] = []
            for action in research_actions:
                assert action.city_id is not None
                assert action.tech_type is not None
                if action.tech_type is not tech_type:
                    continue
                network_id = state.cities[action.city_id].network_id
                network = state.networks[network_id]
                if tech_type is TechType.AGRICULTURE and _needs_food_growth(state, skip_state, network_id):
                    candidates.append(action)
                elif tech_type is TechType.EDUCATION and _prefers_education(state, skip_state, network_id):
                    candidates.append(action)
                elif tech_type is TechType.LOGGING and _has_long_term_shortage(
                    network,
                    forecast_delta,
                    network_id,
                    ResourceType.WOOD,
                    BUILDING_COSTS[BuildingType.LUMBER_MILL][ResourceType.WOOD],
                ):
                    candidates.append(action)
                elif tech_type is TechType.MINING and _has_long_term_shortage(
                    network,
                    forecast_delta,
                    network_id,
                    ResourceType.ORE,
                    BUILDING_COSTS[BuildingType.MINE][ResourceType.ORE],
                ):
                    candidates.append(action)

            if candidates:
                return min(candidates, key=lambda action: _research_action_key(state, action))

        return None

    def _select_gap_building_action(self, state: GameState, legal_actions: list[Action]) -> Action | None:
        building_actions = [
            action
            for action in legal_actions
            if action.action_type is ActionType.BUILD_BUILDING
            and action.city_id is not None
            and action.building_type is not None
        ]
        positive_gap_actions = [
            action for action in building_actions if _building_gap_score(state, action) > 0
        ]
        return _select_building_action_by_gap(state, positive_gap_actions)

    def _select_other_building_action(self, state: GameState, legal_actions: list[Action]) -> Action | None:
        building_actions = [
            action
            for action in legal_actions
            if action.action_type is ActionType.BUILD_BUILDING
            and action.city_id is not None
            and action.building_type is not None
        ]
        return _select_building_action_by_gap(state, building_actions)


def _dangerous_network_ids(state: GameState) -> set[int]:
    skip_state = simulate_action(state, Action.skip())
    dangerous: set[int] = set()
    for network_id, network in state.networks.items():
        if network.resources.food < 8:
            dangerous.add(network_id)
            continue
        if skip_state.networks[network_id].resources.food < 4:
            dangerous.add(network_id)
    return dangerous


def _city_action_key(state: GameState, coord: Coord) -> tuple[int, int, int, tuple[int, int]]:
    score, food, science = _city_score_components(state, coord)
    return (-score, -food, -science, coord_sort_key(coord))


def _food_rescue_city_key(state: GameState, coord: Coord) -> tuple[int, int, tuple[int, int]]:
    food = _city_food_potential(state, coord)
    science = _city_science_potential(state, coord)
    return (-food, -science, coord_sort_key(coord))


def _city_score_components(state: GameState, coord: Coord) -> tuple[int, int, int]:
    food = 0
    wood = 0
    ore = 0
    science = 0

    for neighbor in neighbors(coord):
        tile = state.board.get(neighbor)
        if tile is None or tile.occupant is not OccupantType.NONE:
            continue
        if tile.base_terrain is TerrainType.PLAIN:
            food += 3
        elif tile.base_terrain is TerrainType.FOREST:
            wood += 2
        elif tile.base_terrain is TerrainType.MOUNTAIN:
            ore += 2
        elif tile.base_terrain is TerrainType.RIVER:
            food += 2
            science += 1

    return (3 * food + 2 * wood + 2 * ore + science, food, science)


def _city_food_potential(state: GameState, coord: Coord) -> int:
    return _city_score_components(state, coord)[1]


def _city_science_potential(state: GameState, coord: Coord) -> int:
    return _city_score_components(state, coord)[2]


def _build_city_connects_to_any_network(
    state: GameState, coord: Coord, target_network_ids: set[int]
) -> bool:
    passable_network_map = map_passable_coords_to_networks(state)
    adjacent_network_ids = {
        passable_network_map[neighbor]
        for neighbor in neighbors(coord)
        if neighbor in passable_network_map
    }
    return bool(adjacent_network_ids & target_network_ids)


def _count_adjacent_terrain(state: GameState, coord: Coord, terrain_type: TerrainType) -> int:
    return sum(
        1
        for neighbor in neighbors(coord)
        if (tile := state.board.get(neighbor)) is not None and tile.base_terrain is terrain_type
    )


def _network_priority_key(state: GameState, network_id: int) -> tuple[int, tuple[int, int], int]:
    cities = sorted(
        (state.cities[city_id] for city_id in state.networks[network_id].city_ids),
        key=lambda city: (city.founded_turn, coord_sort_key(city.coord), city.city_id),
    )
    first_city = cities[0]
    return (first_city.founded_turn, coord_sort_key(first_city.coord), network_id)


def _research_action_key(state: GameState, action: Action) -> tuple[tuple[int, tuple[int, int], int], int]:
    assert action.city_id is not None
    city = state.cities[action.city_id]
    return (_network_priority_key(state, city.network_id), city.city_id)


def _forecast_network_deltas(state: GameState, turns: int) -> dict[int, dict[ResourceType, float]]:
    if turns <= 0:
        raise ValueError("turns must be positive.")

    simulated = state
    start_resources = {
        network_id: {
            resource_type: network.resources.get(resource_type)
            for resource_type in ResourceType
        }
        for network_id, network in state.networks.items()
    }

    simulated_turns = 0
    while simulated_turns < turns and not simulated.is_game_over:
        simulated = simulate_action(simulated, Action.skip())
        simulated_turns += 1

    if simulated_turns == 0:
        return {
            network_id: {resource_type: 0.0 for resource_type in ResourceType}
            for network_id in state.networks
        }

    deltas: dict[int, dict[ResourceType, float]] = {}
    for network_id, baseline_values in start_resources.items():
        network = simulated.networks[network_id]
        deltas[network_id] = {
            resource_type: (network.resources.get(resource_type) - baseline_values[resource_type]) / simulated_turns
            for resource_type in ResourceType
        }
    return deltas


def _needs_food_growth(state: GameState, skip_state: GameState, network_id: int) -> bool:
    network = state.networks[network_id]
    return network.resources.food < 12 or skip_state.networks[network_id].resources.food < 8


def _prefers_education(state: GameState, skip_state: GameState, network_id: int) -> bool:
    network = state.networks[network_id]
    skip_network = skip_state.networks[network_id]
    science_delta = skip_network.resources.science - network.resources.science
    return (
        network.resources.food >= 12
        and skip_network.resources.food >= 8
        and network.resources.science < 10
        and science_delta <= 1
    )


def _has_long_term_shortage(
    network: Network,
    forecast_delta: dict[int, dict[ResourceType, float]],
    network_id: int,
    resource_type: ResourceType,
    next_cost: int,
) -> bool:
    return (
        network.resources.get(resource_type) < next_cost
        and forecast_delta[network_id][resource_type] <= 0
    )


def _building_gap_score(state: GameState, action: Action) -> int:
    assert action.city_id is not None
    assert action.building_type is not None
    network = state.networks[state.cities[action.city_id].network_id]
    resource_type = BUILDING_RESOURCE_TYPE[action.building_type]
    return BASELINE_TARGET_BUFFERS[resource_type] - network.resources.get(resource_type)


def _select_building_action_by_gap(state: GameState, actions: Iterable[Action]) -> Action | None:
    materialized = list(actions)
    if not materialized:
        return None
    return min(materialized, key=lambda action: _building_action_key(state, action))


def _select_building_action_by_city_order(state: GameState, actions: Iterable[Action]) -> Action | None:
    materialized = list(actions)
    if not materialized:
        return None
    return min(materialized, key=lambda action: _building_city_order_key(state, action))


def _building_action_key(
    state: GameState, action: Action
) -> tuple[int, int, int, int, int, tuple[int, int], int]:
    assert action.city_id is not None
    assert action.building_type is not None
    city = state.cities[action.city_id]
    gap_score = _building_gap_score(state, action)
    adjacent_count = _adjacent_resource_tile_count(state, city, action.building_type)
    return (
        -gap_score,
        -BUILDING_RESOURCE_PRIORITY[action.building_type],
        -adjacent_count,
        city.buildings.for_type(action.building_type),
        city.founded_turn,
        coord_sort_key(city.coord),
        city.city_id,
    )


def _building_city_order_key(
    state: GameState, action: Action
) -> tuple[int, int, int, tuple[int, int], int]:
    assert action.city_id is not None
    assert action.building_type is not None
    city = state.cities[action.city_id]
    return (
        -_adjacent_resource_tile_count(state, city, action.building_type),
        city.buildings.for_type(action.building_type),
        city.founded_turn,
        coord_sort_key(city.coord),
        city.city_id,
    )


def _adjacent_resource_tile_count(state: GameState, city: City, building_type: BuildingType) -> int:
    allowed_terrains = BUILDING_RESOURCE_TERRAINS[building_type]
    return sum(
        1
        for neighbor in neighbors(city.coord)
        if (tile := state.board.get(neighbor)) is not None
        and tile.occupant is OccupantType.NONE
        and tile.base_terrain in allowed_terrains
    )
