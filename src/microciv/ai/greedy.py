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
from microciv.constants import BUILDING_YIELDS, FOOD_CONSUMPTION_PER_CITY, TECH_COSTS
from microciv.game.actions import Action
from microciv.game.enums import ActionType, BuildingType, OccupantType, TechType, TerrainType
from microciv.game.models import GameState
from microciv.game.scoring import (
    building_count,
    connected_city_count,
    isolated_city_count,
    largest_network_size,
    score_breakdown,
    starving_network_count,
    total_resources,
)
from microciv.utils.grid import cardinal_neighbors, moore_neighbors

MAX_CITY_CANDIDATES = 8
MAX_ROAD_CANDIDATES = 10
MAX_BUILDING_CANDIDATES = 8
MAX_RESOURCE_CITY_CANDIDATES = 8
LONG_GAME_BUILDING_BONUS_TURNS = 30


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
            key=lambda action: (-city_site_score(state, action.coord), action.coord),
        )
        resource_city_actions = sorted(
            city_actions,
            key=lambda action: (-city_expansion_score(state, action.coord), action.coord),
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
            ),
            key=lambda action: (-road_site_score(state, action.coord), action.coord),
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
            candidates.extend(road_actions[:MAX_ROAD_CANDIDATES])
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

        city_limit = min(
            24,
            MAX_CITY_CANDIDATES
            + max(0, (state.config.map_size - 12) // 2)
            + max(0, (len(state.cities) - 10) // 2),
        )
        road_limit = min(14, MAX_ROAD_CANDIDATES + max(0, state.config.map_size - 16))
        building_limit = min(
            18,
            MAX_BUILDING_CANDIDATES
            + max(0, (state.config.map_size - 16))
            + max(0, len(state.cities) // 12),
        )
        resource_city_limit = min(
            MAX_RESOURCE_CITY_CANDIDATES + max(0, state.config.map_size - 16),
            city_limit,
        )
        if turns_remaining <= 60:
            city_limit = max(6, city_limit - 6)
            resource_city_limit = max(4, resource_city_limit - 2)
            building_limit = min(20, building_limit + 4)
        if total_buildings < len(state.cities):
            city_limit = max(6, city_limit - 4)
            resource_city_limit = max(4, resource_city_limit - 2)
            building_limit = min(20, building_limit + 4)
        if total_buildings + 8 < len(state.cities) * 2:
            city_limit = max(4, city_limit - 6)
            resource_city_limit = max(3, resource_city_limit - 4)
            building_limit = min(22, building_limit + 6)
        if resources.wood >= 20 and resources.ore >= 8 and turns_remaining >= 20:
            city_limit = max(4, city_limit - 4)
            resource_city_limit = max(3, resource_city_limit - 2)
            building_limit = min(24, building_limit + 6)
        if food_crisis:
            city_limit = min(city_limit, 6)
            resource_city_limit = min(resource_city_limit, 5)
            building_limit = min(24, building_limit + 4)

        candidates.extend(city_actions[:city_limit])
        candidates.extend(resource_city_actions[:resource_city_limit])
        candidates.extend(interior_gem_actions[:4])
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
        candidates.extend(river_city_actions[: min(6, resource_city_limit)])
        candidates.extend(road_actions[:road_limit])
        candidates.extend(building_actions[:building_limit])
        candidates.extend(research_actions)
        candidates.extend(groups.get(ActionType.SKIP, [])[:1])

        deduped: list[Action] = []
        seen: set[Action] = set()
        for action in candidates:
            if action not in seen:
                deduped.append(action)
                seen.add(action)
        return deduped

    def _evaluate_action(self, state: GameState, action: Action, current_score: int) -> int:
        current_resources = total_resources(state)
        turns_remaining = max(0, state.config.turn_limit - state.turn + 1)
        current_buildings = building_count(state)
        city_count = len(state.cities)
        wood_target, ore_target = material_targets(state)
        terrain_counts = city_terrain_counts(state)
        infrastructure_gap = max(0, city_count - current_buildings)
        food_buffer_target = city_count * FOOD_CONSUMPTION_PER_CITY * 3
        simulated = simulate_action(state, action)
        breakdown = score_breakdown(simulated)
        resources = total_resources(simulated)
        starving = starving_network_count(simulated)
        connected = connected_city_count(simulated)
        isolated = isolated_city_count(simulated)
        largest_network = largest_network_size(simulated)
        delta_score = breakdown.total - current_score

        value = breakdown.total * 10
        value += delta_score * 14
        value += connected * 25
        value += largest_network * 12
        value -= isolated * 10
        value -= starving * 220
        value -= max(0, -resources.food) * 3
        value += building_count(simulated) * 8
        excess_science = max(0, resources.science - 60)
        if excess_science:
            value -= excess_science * 3
        if action.action_type is ActionType.BUILD_ROAD:
            assert action.coord is not None
            road_value = road_site_score(state, action.coord)
            value += road_value * 4
            frontier_city_boost = 0
            for neighbor in moore_neighbors(action.coord):
                tile = state.board.get(neighbor)
                if tile is None or tile.occupant is not OccupantType.NONE:
                    continue
                if tile.base_terrain not in {
                    TerrainType.PLAIN, TerrainType.FOREST, TerrainType.MOUNTAIN
                }:
                    continue
                # Check if this road unlocks a high-value city site that was previously disconnected
                has_nearby_road = any(
                    (n := state.board.get(n2)) is not None
                    and n.occupant.value in {"road", "city"}
                    for n2 in cardinal_neighbors(neighbor)
                    if n2 != action.coord
                )
                if not has_nearby_road and city_site_score(state, neighbor) >= 90:
                    frontier_city_boost = max(frontier_city_boost, 160)
            value += frontier_city_boost
            if len(state.roads) == 0 and len(state.cities) >= 2:
                value += 620
                if road_value >= 80:
                    value += 520
            if len(state.roads) < max(1, len(state.cities) // 4):
                value += 140
            if current_resources.food < 0 and road_value >= 120:
                value += 180
            if (
                connected == connected_city_count(state)
                and largest_network == largest_network_size(state)
                and isolated == isolated_city_count(state)
                and road_value < 120
            ):
                value -= 180
        if (
            action.action_type is ActionType.BUILD_BUILDING
            and action.building_type is BuildingType.FARM
        ):
            value += 80
        if action.action_type is ActionType.BUILD_BUILDING:
            assert action.building_type is not None
            per_turn_yield = sum(BUILDING_YIELDS[action.building_type].values())
            value += per_turn_yield * min(turns_remaining, LONG_GAME_BUILDING_BONUS_TURNS) * 4
            value += infrastructure_gap * 30
            value += 120
            if current_resources.wood >= 10:
                value += 110
            if (
                action.building_type in {BuildingType.MINE, BuildingType.LIBRARY}
                and current_resources.ore >= 8
            ):
                value += 130
            if current_buildings + 8 < city_count * 2:
                value += 160
        if (
            action.action_type is ActionType.RESEARCH_TECH
            and action.tech_type is TechType.AGRICULTURE
        ):
            value += 70
        if action.action_type is ActionType.RESEARCH_TECH:
            assert action.tech_type is not None
            value += 220
            value += min(turns_remaining, 24) * 8
            if current_resources.science >= TECH_COSTS[action.tech_type]:
                value += 180
            science_excess = max(0, current_resources.science - 50)
            if science_excess:
                value -= science_excess * 2
        if action.action_type is ActionType.BUILD_CITY:
            assert action.coord is not None
            terrain = state.board[action.coord].base_terrain
            forest_ring, mountain_ring, river_ring, plain_ring, occupied_ring = resource_ring_counts(
                state, action.coord
            )
            resource_ring = forest_ring + mountain_ring
            ring_total = resource_ring + river_ring
            river_adjacent = sum(
                1
                for neighbor in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if (
                    adjacent := state.board.get(
                        (action.coord[0] + neighbor[0], action.coord[1] + neighbor[1])
                    )
                ) is not None
                and adjacent.base_terrain is TerrainType.RIVER
            )
            wood_gain = resources.wood - current_resources.wood
            ore_gain = resources.ore - current_resources.ore
            food_gain = resources.food - current_resources.food
            science_gain = resources.science - current_resources.science
            city_soft_cap = max(12, state.config.map_size - 4)
            value -= max(0, len(state.cities) - city_soft_cap) * 12
            value += max(0, food_gain) * 2
            value += max(0, wood_gain) * max(10, 24 - current_resources.wood)
            value += max(0, ore_gain) * max(12, 20 - current_resources.ore)
            value += max(0, science_gain) * max(2, 10 - (current_resources.science // 4))
            if current_resources.wood <= 4 and wood_gain > 0:
                value += 140
            if current_resources.wood <= 10 and wood_gain > 0:
                value += 160
            if current_resources.ore <= 4 and ore_gain > 0:
                value += 160
            if current_resources.ore <= 8 and ore_gain > 0:
                value += 180
            if building_count(state) == 0 and (wood_gain > 0 or ore_gain > 0):
                value += 120
            value += resource_ring * 88
            value += river_ring * 56
            value += river_adjacent * 80
            if current_resources.food < 0:
                food_crisis_scale = min(80, -current_resources.food)
                value += river_ring * food_crisis_scale * 2
                value += river_adjacent * food_crisis_scale * 3
            mix = min(forest_ring, mountain_ring)
            mix_c_triggered = False
            if resource_ring >= 4 and occupied_ring <= 4:
                if river_ring == 0 and plain_ring == 0:
                    value += mix * 96
                    mix_c_triggered = True
                elif river_ring == 0 and plain_ring > 0:
                    value += mix * 64
                elif river_ring > 0:
                    value += mix * 64
            if mix_c_triggered and terrain in {
                TerrainType.FOREST, TerrainType.MOUNTAIN
            }:
                value += 240
            value += max(0, ring_total - 3) * 95
            if terrain is TerrainType.PLAIN and resource_ring >= 4:
                value += 240 + ((resource_ring - 4) * 70)
            if terrain is TerrainType.FOREST:
                value += max(0, wood_target - current_resources.wood) * 34
                value += max(0, 4 - terrain_counts[TerrainType.FOREST]) * 110
                if resource_ring >= 4:
                    value += 120
            elif terrain is TerrainType.MOUNTAIN:
                value += max(0, ore_target - current_resources.ore) * 38
                value += max(0, 4 - terrain_counts[TerrainType.MOUNTAIN]) * 120
                if resource_ring >= 4:
                    value += 140
            elif terrain is TerrainType.PLAIN:
                if current_resources.food > food_buffer_target * 2:
                    if current_resources.wood < wood_target or current_resources.ore < ore_target:
                        value -= 300
                if current_resources.food < 0:
                    value += food_crisis_scale * 3
                if current_resources.food < food_buffer_target:
                    value += 120
            if turns_remaining <= 60:
                value -= (60 - turns_remaining) * 5
            if infrastructure_gap > 0:
                value -= infrastructure_gap * 34
            if current_buildings + 8 < city_count * 2:
                value -= 220
            if current_resources.wood >= 20 and current_resources.ore >= 8:
                value -= 180
            if current_resources.food < 0:
                value -= max(0, -current_resources.food) * 6
                if food_gain <= 0:
                    value -= 420
                if river_ring == 0 and river_adjacent == 0:
                    value -= 600
            if current_resources.food < -(city_count * FOOD_CONSUMPTION_PER_CITY):
                if food_gain <= 0:
                    value -= 900
                if river_ring == 0 and river_adjacent == 0:
                    value -= 400
            if current_resources.food < food_buffer_target and food_gain <= 0:
                value -= 180
            if resources.food <= 0:
                value -= 260
        if action.action_type is ActionType.SKIP:
            value -= 140
            if building_count(state) == 0 and len(state.cities) >= 8:
                value -= 220
            if current_resources.wood <= 10:
                value -= 120
            if current_resources.ore <= 8:
                value -= 120
            if turns_remaining > 12 and infrastructure_gap > 0 and current_resources.wood >= 10:
                value -= min(280, infrastructure_gap * 25)
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
