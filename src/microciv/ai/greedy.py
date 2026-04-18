"""One-step lookahead greedy policy."""

from __future__ import annotations

from dataclasses import dataclass

from microciv.ai.heuristics import (
    TECH_UNLOCK_PRIORITY,
    building_action_score,
    city_expansion_score,
    city_key,
    city_network_pressure,
    city_site_score,
    city_terrain_counts,
    material_targets,
    partition_actions,
    research_action_score,
    resource_ring_counts,
    road_site_score,
)
from microciv.ai.policy import Policy, get_legal_actions, simulate_action
from microciv.constants import BUILDING_YIELDS, FOOD_CONSUMPTION_PER_CITY
from microciv.game.actions import Action
from microciv.game.enums import ActionType, BuildingType, OccupantType, TechType, TerrainType
from microciv.game.models import GameState
from microciv.game.networks import map_passable_coords_to_networks
from microciv.game.scoring import (
    building_count,
    connected_city_count,
    isolated_city_count,
    largest_network_size,
    score_breakdown,
    starving_network_count,
    tech_count,
    total_resources,
)
from microciv.utils.grid import cardinal_neighbors, moore_neighbors

MAX_CITY_CANDIDATES = 8
MAX_BUILDING_CANDIDATES = 8
MAX_RESOURCE_CITY_CANDIDATES = 8
LONG_GAME_BUILDING_BONUS_TURNS = 30
TARGET_INLAND_SHARE = 0.45


@dataclass(slots=True, frozen=True)
class PlannedDecision:
    action: Action
    context: dict[str, object]


class GreedyPolicy(Policy):
    """A deterministic one-ply greedy policy used as the default benchmark."""

    def __init__(self) -> None:
        self._cache_key: tuple[int, int, int, int, int, int] | None = None
        self._cached_decision: PlannedDecision | None = None

    def select_action(self, state: GameState) -> Action:
        return self._plan_action(state).action

    def explain_decision(self, state: GameState) -> dict[str, object]:
        return dict(self._plan_action(state).context)

    def _plan_action(self, state: GameState) -> PlannedDecision:
        cache_key = (
            id(state),
            state.turn,
            len(state.cities),
            len(state.roads),
            len(state.networks),
            state.score,
        )
        if self._cache_key == cache_key and self._cached_decision is not None:
            return self._cached_decision

        legal_actions = get_legal_actions(state)
        if not legal_actions:
            decision = PlannedDecision(
                action=Action.skip(),
                context={"greedy_priority": "no_legal_actions", "greedy_best_action_type": "skip"},
            )
            self._cache_key = cache_key
            self._cached_decision = decision
            return decision

        current_breakdown = score_breakdown(state)
        current_resources = total_resources(state)
        groups = partition_actions(legal_actions)
        candidates = self._candidate_actions(state, groups)

        best_action = Action.skip()
        best_value = -10**18
        best_priority = "skip"
        for action in candidates:
            value = self._evaluate_action(state, action, current_breakdown.total)
            priority = _priority_label(state, action)
            if value > best_value or (
                value == best_value
                and _action_tiebreak_key(state, action)
                < _action_tiebreak_key(state, best_action)
            ):
                best_action = action
                best_value = value
                best_priority = priority

        decision = PlannedDecision(
            action=best_action,
            context={
                "greedy_priority": best_priority,
                "greedy_best_action_type": best_action.action_type.value,
                "greedy_best_score": round(best_value / 10, 1),
                "greedy_food_pressure": max(
                    (city_network_pressure(network) for network in state.networks.values()),
                    default=0,
                ),
                "greedy_starving_networks": starving_network_count(state),
                "greedy_connected_cities": connected_city_count(state),
                "greedy_total_food": current_resources.food,
            },
        )
        self._cache_key = cache_key
        self._cached_decision = decision
        return decision

    def _candidate_actions(
        self,
        state: GameState,
        groups: dict[ActionType, list[Action]],
    ) -> list[Action]:
        candidates: list[Action] = []
        total_buildings = building_count(state)
        turns_remaining = max(0, state.config.turn_limit - state.turn + 1)
        resources = total_resources(state)
        terrain_counts = city_terrain_counts(state)
        wood_target, ore_target = material_targets(state)
        current_tech_count = tech_count(state)
        missing_unlocked_buildings = _has_missing_unlocked_buildings(state)
        current_connected_cities, current_connected_inland = _connected_city_mix(state)
        food_buffer_target = max(1, len(state.cities) * FOOD_CONSUMPTION_PER_CITY * 3)
        development_saturated = (
            len(state.cities) > 0
            and current_tech_count == len(TechType)
            and not missing_unlocked_buildings
            and total_buildings >= len(state.cities) * 3
            and resources.food >= food_buffer_target
        )
        pressure = max(
            (city_network_pressure(network) for network in state.networks.values()),
            default=0,
        )
        food_crisis = resources.food < -(len(state.cities) * FOOD_CONSUMPTION_PER_CITY) or (
            pressure > FOOD_CONSUMPTION_PER_CITY * 3
        )

        city_actions = sorted(
            (
                action
                for action in groups.get(ActionType.BUILD_CITY, [])
                if action.coord is not None
            ),
            key=lambda action: (
                -city_site_score(state, _action_coord(action)),
                _action_coord(action),
            ),
        )
        resource_city_actions = sorted(
            city_actions,
            key=lambda action: (
                -city_expansion_score(state, _action_coord(action)),
                _action_coord(action),
            ),
        )
        forest_city_actions = [
            action
            for action in resource_city_actions
            if action.coord is not None
            and state.board[action.coord].base_terrain is TerrainType.FOREST
        ]
        mountain_city_actions = [
            action
            for action in resource_city_actions
            if action.coord is not None
            and state.board[action.coord].base_terrain is TerrainType.MOUNTAIN
        ]
        plain_city_actions = [
            action
            for action in resource_city_actions
            if action.coord is not None
            and state.board[action.coord].base_terrain is TerrainType.PLAIN
        ]
        interior_gem_actions = [
            action
            for action in city_actions
            if action.coord is not None
            and state.board[action.coord].base_terrain in {
                TerrainType.FOREST, TerrainType.MOUNTAIN
            }
            and city_site_score(state, action.coord) >= 100
        ]
        inland_city_actions = [
            action
            for action in resource_city_actions
            if action.coord is not None
            and not _is_river_adjacent_site(state, action.coord)
        ]
        river_city_actions = [
            action
            for action in resource_city_actions
            if action.coord is not None and resource_ring_counts(state, action.coord)[2] > 0
        ]
        road_actions = sorted(
            (
                action
                for action in groups.get(ActionType.BUILD_ROAD, [])
                if action.coord is not None
                and _road_structure_score(state, action.coord) > 0
            ),
            key=lambda action: (
                -_road_structure_score(state, _action_coord(action)),
                -road_site_score(state, _action_coord(action)),
                _action_coord(action),
            ),
        )
        building_actions = sorted(
            groups.get(ActionType.BUILD_BUILDING, []),
            key=lambda action: (
                -building_action_score(state, action),
                (
                    city_key(state.cities[action.city_id])
                    if action.city_id is not None
                    else (0, (0, 0), 0)
                ),
            ),
        )
        gap_building_actions = [
            action for action in building_actions if _is_gap_build_action(state, action)
        ]
        research_actions = sorted(
            groups.get(ActionType.RESEARCH_TECH, []),
            key=lambda action: (
                -research_action_score(state, action),
                (
                    TECH_UNLOCK_PRIORITY.index(action.tech_type)
                    if action.tech_type is not None
                    else len(TECH_UNLOCK_PRIORITY)
                ),
            ),
        )

        building_limit = min(14, MAX_BUILDING_CANDIDATES + max(0, len(state.cities) // 8))
        research_limit = min(max(2, len(state.networks) + 1), len(research_actions))

        if pressure > 0:
            farm_actions = [
                action
                for action in building_actions
                if action.building_type is BuildingType.FARM
            ]
            if farm_actions:
                candidates.extend(farm_actions[:MAX_BUILDING_CANDIDATES])
            agriculture = [
                action for action in research_actions if action.tech_type is TechType.AGRICULTURE
            ]
            candidates.extend(agriculture[:1])
            candidates.extend(road_actions[: max(2, len(state.networks))])
            rescue_cities = [
                action
                for action in city_actions
                if action.coord is not None
                and city_site_score(state, action.coord) >= 40
            ]
            candidates.extend(rescue_cities[:4])
            if food_crisis:
                candidates.extend(river_city_actions[:4])
                candidates.extend(plain_city_actions[:4])

        city_limit = min(10, MAX_CITY_CANDIDATES + max(0, (state.config.map_size - 16) // 4))
        road_limit = min(6, max(2, len(state.networks) + 1))
        resource_city_limit = min(
            min(6, MAX_RESOURCE_CITY_CANDIDATES + max(0, state.config.map_size - 20)),
            city_limit,
        )
        if turns_remaining <= 100:
            city_limit = max(4, city_limit - 2)
            resource_city_limit = max(3, resource_city_limit - 1)
        if turns_remaining <= 60:
            city_limit = max(3, city_limit - 2)
            resource_city_limit = max(2, resource_city_limit - 1)
            building_limit = min(18, building_limit + 2)
        if current_tech_count < len(TechType):
            city_limit = max(3, city_limit - 2)
            resource_city_limit = max(2, resource_city_limit - 1)
            research_limit = min(max(3, len(state.networks) + 2), len(research_actions))
        if total_buildings < len(state.cities):
            city_limit = max(3, city_limit - 2)
            resource_city_limit = max(2, resource_city_limit - 1)
            building_limit = min(18, building_limit + 2)
        if missing_unlocked_buildings:
            city_limit = max(2, city_limit - 2)
            resource_city_limit = max(2, resource_city_limit - 1)
            road_limit = min(3, road_limit)
            building_limit = min(20, building_limit + 4)
        if food_crisis:
            city_limit = min(city_limit, 2)
            resource_city_limit = min(resource_city_limit, 2)
            road_limit = min(2, road_limit)
            building_limit = min(20, building_limit + 4)
            research_limit = min(max(2, len(state.networks)), len(research_actions))
        elif development_saturated:
            city_limit = min(11, city_limit + 1)
            resource_city_limit = min(7, resource_city_limit + 1)
            building_limit = max(8, building_limit - 2)
            current_composition_gap = _composition_gap(
                current_connected_cities,
                current_connected_inland,
            )
            if current_composition_gap > 0.20:
                road_limit = min(7, road_limit + 1)

        candidates.extend(gap_building_actions[: min(8, len(gap_building_actions))])
        candidates.extend(research_actions[:research_limit])
        candidates.extend(building_actions[:building_limit])
        candidates.extend(city_actions[:city_limit])
        candidates.extend(resource_city_actions[:resource_city_limit])
        candidates.extend(interior_gem_actions[:4])
        if _inland_share(current_connected_cities, current_connected_inland) < TARGET_INLAND_SHARE:
            candidates.extend(inland_city_actions[: min(6, city_limit)])
        food_target = len(state.cities) * FOOD_CONSUMPTION_PER_CITY * 3
        if resources.wood < wood_target or terrain_counts[TerrainType.FOREST] < 3:
            candidates.extend(forest_city_actions[: min(6, resource_city_limit)])
        if resources.ore < ore_target or terrain_counts[TerrainType.MOUNTAIN] < 3:
            candidates.extend(mountain_city_actions[: min(6, resource_city_limit)])
        if resources.food < food_target or terrain_counts[TerrainType.PLAIN] < 3:
            if food_crisis:
                candidates.extend(plain_city_actions[: min(4, resource_city_limit)])
            else:
                candidates.extend(plain_city_actions[: min(6, resource_city_limit)])
        if food_crisis or current_connected_cities < 6:
            candidates.extend(river_city_actions[: min(4, resource_city_limit)])
        else:
            candidates.extend(river_city_actions[: min(2, resource_city_limit)])
        candidates.extend(road_actions[:road_limit])
        candidates.extend(groups.get(ActionType.SKIP, [])[:1])

        deduped: list[Action] = []
        seen: set[Action] = set()
        for action in candidates:
            if action not in seen:
                deduped.append(action)
                seen.add(action)
        return deduped

    def _evaluate_action(
        self,
        state: GameState,
        action: Action,
        current_score: int,
    ) -> int:
        current_resources = total_resources(state)
        current_breakdown = score_breakdown(state)
        turns_remaining = max(0, state.config.turn_limit - state.turn + 1)
        current_buildings = building_count(state)
        city_count = len(state.cities)
        buildings_per_city = current_buildings / max(1, city_count)
        infrastructure_gap = max(0, city_count - current_buildings)
        food_buffer_target = city_count * FOOD_CONSUMPTION_PER_CITY * 3
        current_connected = connected_city_count(state)
        current_isolated = isolated_city_count(state)
        current_largest_network = largest_network_size(state)
        current_tech_count = tech_count(state)
        missing_unlocked_buildings = _has_missing_unlocked_buildings(state)
        current_connected_cities, current_connected_inland = _connected_city_mix(state)
        current_composition_gap = _composition_gap(
            current_connected_cities,
            current_connected_inland,
        )
        development_saturated = (
            city_count > 0
            and current_tech_count == len(TechType)
            and not missing_unlocked_buildings
            and current_buildings >= city_count * 3
            and current_resources.food >= max(1, food_buffer_target)
        )
        simulated = simulate_action(state, action)
        breakdown = score_breakdown(simulated)
        resources = total_resources(simulated)
        starving = starving_network_count(simulated)
        connected = connected_city_count(simulated)
        isolated = isolated_city_count(simulated)
        largest_network = largest_network_size(simulated)
        connected_cities, connected_inland = _connected_city_mix(simulated)
        delta_score = breakdown.total - current_score

        value = breakdown.total * 20
        value += delta_score * 40
        value += max(0, connected - current_connected) * 90
        value += max(0, current_isolated - isolated) * 140
        value += max(0, largest_network - current_largest_network) * 35
        value += (
            breakdown.building_utilization_score - current_breakdown.building_utilization_score
        ) * 18
        value += (
            current_breakdown.building_mismatch_penalty - breakdown.building_mismatch_penalty
        ) * 14
        value += (
            breakdown.city_composition_bonus - current_breakdown.city_composition_bonus
        ) * 10
        value -= max(0, -resources.food) * 14
        value -= starving * 260
        value -= isolated * 24
        excess_science = max(0, resources.science - 60)
        if excess_science:
            value -= excess_science * 2
        if action.action_type is ActionType.BUILD_ROAD:
            assert action.coord is not None
            road_structure = _road_structure_score(state, action.coord)
            value += road_structure * 120
            value += int(current_composition_gap * road_structure * 80)
            if connected == current_connected and isolated == current_isolated:
                value -= 520
            if largest_network == current_largest_network:
                value -= 160
            if missing_unlocked_buildings:
                value -= 220
            if current_tech_count < len(TechType):
                value -= 180
            if current_breakdown.building_utilization_score < 0:
                value -= 260
            if resources.food <= 0:
                value -= 260
        if (
            action.action_type is ActionType.BUILD_BUILDING
            and action.building_type is BuildingType.FARM
        ):
            value += 70
        if action.action_type is ActionType.BUILD_BUILDING:
            assert action.building_type is not None
            per_turn_yield = sum(BUILDING_YIELDS[action.building_type].values())
            value += per_turn_yield * 18
            value += infrastructure_gap * 28
            if _is_gap_build_action(state, action):
                value += 220
            if development_saturated:
                value -= 110
            if (
                current_connected_cities >= 8
                and current_buildings >= city_count * 2
                and current_composition_gap > 0.15
            ):
                value -= int(current_composition_gap * 520)
            if (
                action.building_type is BuildingType.FARM
                and resources.food > current_resources.food
            ):
                value += 180
            if resources.food <= 0 and action.building_type is not BuildingType.FARM:
                value -= 180
        if (
            action.action_type is ActionType.RESEARCH_TECH
            and action.tech_type is TechType.AGRICULTURE
        ):
            value += 80
        if action.action_type is ActionType.RESEARCH_TECH:
            assert action.tech_type is not None
            value += 140
            value += (len(TechType) - current_tech_count) * 45
            value += min(turns_remaining, 24) * 4
            if current_breakdown.building_utilization_score < 0:
                value += 80
        if action.action_type is ActionType.BUILD_CITY:
            assert action.coord is not None
            food_gain = resources.food - current_resources.food
            site_quality = max(0, city_site_score(state, action.coord) - 60)
            value += max(0, food_gain) * 20
            value += site_quality * 2
            if development_saturated:
                value += 180
                value += current_tech_count * 20
                if current_composition_gap > 0.20:
                    value += 80
            current_gap = _composition_gap(current_connected_cities, current_connected_inland)
            future_gap = _composition_gap(connected_cities, connected_inland)
            value += (current_gap - future_gap) * 1000
            if not _is_river_adjacent_site(state, action.coord):
                connection_steps = _road_steps_to_network(state, action.coord, max_steps=3)
                value += int(current_gap * 1400)
                if connection_steps is not None:
                    value += max(0, 4 - connection_steps) * 180
                    value += int(current_gap * 420)
                    if connection_steps <= 2:
                        soft_gap = _composition_gap(
                            current_connected_cities + 1,
                            current_connected_inland + 1,
                        )
                        value += max(0, current_gap - soft_gap) * 1000
                else:
                    value -= 220
            elif current_gap > 0 and connected >= current_connected:
                value -= current_gap * 1100
            if infrastructure_gap > 0:
                value -= infrastructure_gap * 70
            if current_buildings < city_count * 1.8:
                value -= int((city_count * 1.8 - current_buildings) * 140)
            if buildings_per_city < 1.4:
                value -= 180
            if current_buildings + 4 < city_count * 2:
                value -= 240
            if missing_unlocked_buildings:
                value -= 260
            if current_tech_count < len(TechType):
                value -= 180
            if current_resources.food < food_buffer_target:
                value -= 240
            if current_resources.food < 0:
                value -= 360
                if food_gain <= 0:
                    value -= 420
            if resources.food <= 0:
                value -= 520
        if action.action_type is ActionType.SKIP:
            value -= 220
            if current_breakdown.building_utilization_score < 0:
                value -= 160
            if current_tech_count < len(TechType):
                value -= 140
            if infrastructure_gap > 0:
                value -= min(260, infrastructure_gap * 35)
        return value


def _priority_label(state: GameState, action: Action) -> str:
    if (
        action.action_type is ActionType.BUILD_BUILDING
        and action.building_type is BuildingType.FARM
    ):
        return "food_rescue"
    if (
        action.action_type is ActionType.RESEARCH_TECH
        and action.tech_type is TechType.AGRICULTURE
    ):
        return "food_rescue"
    if action.action_type is ActionType.BUILD_ROAD:
        return "connective_road"
    if action.action_type is ActionType.BUILD_BUILDING:
        return "building"
    if action.action_type is ActionType.RESEARCH_TECH:
        return "tech"
    if action.action_type is ActionType.BUILD_CITY:
        return "city"
    return "skip"


def _action_tiebreak_key(state: GameState, action: Action) -> tuple[int, tuple[int, int], int, int]:
    coord = action.coord if action.coord is not None else (-1, -1)
    city_turn = 0
    city_id = action.city_id or 0
    if action.city_id is not None:
        city_turn = state.cities[action.city_id].founded_turn
    return (action.action_type.value != "build_building", coord, city_turn, city_id)


def _action_coord(action: Action) -> tuple[int, int]:
    assert action.coord is not None
    return action.coord


def _is_river_adjacent_site(state: GameState, coord: tuple[int, int]) -> bool:
    return any(
        (tile := state.board.get(neighbor)) is not None
        and tile.base_terrain is TerrainType.RIVER
        for neighbor in cardinal_neighbors(coord)
    )


def _connected_city_mix(state: GameState) -> tuple[int, int]:
    connected = 0
    inland = 0
    for city in state.cities.values():
        network = state.networks[city.network_id]
        if len(network.city_ids) < 2:
            continue
        connected += 1
        if not _is_river_adjacent_site(state, city.coord):
            inland += 1
    return connected, inland


def _inland_share(connected_cities: int, connected_inland: int) -> float:
    if connected_cities <= 0:
        return 0.0
    return connected_inland / connected_cities


def _composition_gap(connected_cities: int, connected_inland: int) -> float:
    if connected_cities < 6:
        return max(0.0, TARGET_INLAND_SHARE - _inland_share(connected_cities, connected_inland))
    return abs(_inland_share(connected_cities, connected_inland) - TARGET_INLAND_SHARE)


def _road_steps_to_network(
    state: GameState,
    coord: tuple[int, int],
    max_steps: int,
) -> int | None:
    passable_map = map_passable_coords_to_networks(state)
    if coord in passable_map:
        return 0
    frontier = [(coord, 0)]
    seen = {coord}
    while frontier:
        current, steps = frontier.pop(0)
        if steps >= max_steps:
            continue
        for neighbor in cardinal_neighbors(current):
            if neighbor in seen:
                continue
            tile = state.board.get(neighbor)
            if tile is None:
                continue
            if neighbor in passable_map:
                return steps + 1
            if tile.occupant is not OccupantType.NONE:
                continue
            if tile.base_terrain not in {
                TerrainType.PLAIN,
                TerrainType.FOREST,
                TerrainType.MOUNTAIN,
                TerrainType.RIVER,
            }:
                continue
            seen.add(neighbor)
            frontier.append((neighbor, steps + 1))
    return None


def _has_missing_unlocked_buildings(state: GameState) -> bool:
    return any(_network_missing_building_types(state, network_id) for network_id in state.networks)


def _network_missing_building_types(
    state: GameState,
    network_id: int,
) -> set[BuildingType]:
    network = state.networks[network_id]
    missing: set[BuildingType] = set()
    for tech_type in network.unlocked_techs:
        building_type = TECH_UNLOCK_PRIORITY_TO_BUILDING[tech_type]
        total = sum(
            state.cities[city_id].buildings.for_type(building_type)
            for city_id in network.city_ids
        )
        if total == 0:
            missing.add(building_type)
    return missing


def _is_gap_build_action(state: GameState, action: Action) -> bool:
    if action.city_id is None or action.building_type is None:
        return False
    city = state.cities[action.city_id]
    return action.building_type in _network_missing_building_types(state, city.network_id)


def _road_structure_score(state: GameState, coord: tuple[int, int]) -> int:
    structural_score = 0
    passable_map = map_passable_coords_to_networks(state)
    adjacent_network_ids = {
        passable_map[neighbor]
        for neighbor in cardinal_neighbors(coord)
        if neighbor in passable_map
    }
    if len(adjacent_network_ids) >= 2:
        structural_score += 4
    if any(len(state.networks[network_id].city_ids) == 1 for network_id in adjacent_network_ids):
        structural_score += 3
    if state.board[coord].base_terrain is TerrainType.RIVER and adjacent_network_ids:
        structural_score += 1
    for neighbor in moore_neighbors(coord):
        tile = state.board.get(neighbor)
        if tile is None or tile.occupant is not OccupantType.NONE:
            continue
        if tile.base_terrain not in {TerrainType.PLAIN, TerrainType.FOREST, TerrainType.MOUNTAIN}:
            continue
        if city_site_score(state, neighbor) < 120:
            continue
        has_prior_access = any(
            (adjacent := state.board.get(n2)) is not None
            and (
                adjacent.occupant in {OccupantType.CITY, OccupantType.ROAD}
                or adjacent.base_terrain is TerrainType.RIVER
            )
            for n2 in cardinal_neighbors(neighbor)
            if n2 != coord
        )
        if not has_prior_access:
            structural_score += 2
            break
    return structural_score


TECH_UNLOCK_PRIORITY_TO_BUILDING: dict[TechType, BuildingType] = {
    TechType.AGRICULTURE: BuildingType.FARM,
    TechType.LOGGING: BuildingType.LUMBER_MILL,
    TechType.MINING: BuildingType.MINE,
    TechType.EDUCATION: BuildingType.LIBRARY,
}
