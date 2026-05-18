"""Reusable candidate and leaf-evaluation helpers for search policies."""

from __future__ import annotations

from dataclasses import dataclass

from microciv.ai.heuristics import (
    HeuristicContext,
    build_heuristic_context,
    building_action_score,
    city_expansion_score_for_context,
    city_network_pressure,
    context_passable_network_map,
    partition_actions,
    research_action_score,
    road_site_score_for_context,
    site_budget,
)
from microciv.ai.policy import get_legal_actions
from microciv.constants import FOOD_CONSUMPTION_PER_CITY
from microciv.game.actions import Action
from microciv.game.enums import ActionType, BuildingType, TechType
from microciv.game.models import GameState
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

_ACTION_TYPE_ORDER: dict[ActionType, int] = {
    ActionType.BUILD_CITY: 0,
    ActionType.BUILD_ROAD: 1,
    ActionType.BUILD_BUILDING: 2,
    ActionType.RESEARCH_TECH: 3,
    ActionType.SKIP: 4,
}
_BUILDING_TYPE_ORDER: dict[BuildingType, int] = {
    building_type: index for index, building_type in enumerate(BuildingType)
}
_TECH_TYPE_ORDER: dict[TechType, int] = {
    tech_type: index for index, tech_type in enumerate(TechType)
}
_NON_SKIP_TYPES: tuple[ActionType, ...] = (
    ActionType.BUILD_CITY,
    ActionType.BUILD_ROAD,
    ActionType.BUILD_BUILDING,
    ActionType.RESEARCH_TECH,
)
_SKIP_RANK_SCORE = -(10**9)
SEARCH_MODE_RESCUE = "rescue"
SEARCH_MODE_CONNECT = "connect"
SEARCH_MODE_EXPAND = "expand"
SEARCH_MODE_FILL = "fill"


@dataclass(slots=True, frozen=True)
class SearchPositionProfile:
    """Public, Greedy-independent position summary for Search pruning and diagnostics."""

    mode: str
    is_healthy_steady: bool
    turns_remaining: int
    city_count: int
    target_city_count: int
    expansion_deficit: int
    network_count: int
    connected_city_count: int
    isolated_city_count: int
    starving_network_count: int
    total_food: int
    food_pressure: int


@dataclass(slots=True, frozen=True)
class SearchCandidateConfig:
    candidate_limit: int
    include_skip: bool = True


@dataclass(slots=True, frozen=True)
class SearchCandidate:
    action: Action
    action_type: ActionType
    rank_score: int
    reason: str


@dataclass(slots=True, frozen=True)
class SearchCandidateSet:
    candidates: list[SearchCandidate]
    legal_action_count: int
    legal_counts_by_type: dict[ActionType, int]
    candidate_counts_by_type: dict[ActionType, int]
    profile: SearchPositionProfile
    safe_city_candidate_count: int = 0
    effective_connection_road_candidate_count: int = 0
    rescue_candidate_count: int = 0


@dataclass(slots=True, frozen=True)
class SearchLeafEvaluation:
    value: int
    value_components: dict[str, int]
    score_total: int
    connected_city_count: int
    isolated_city_count: int
    starving_network_count: int
    network_count: int
    largest_network_size: int
    total_food: int
    total_wood: int
    total_ore: int
    total_science: int
    food_pressure: int
    starving_turns: int


def generate_search_candidates(
    state: GameState,
    config: SearchCandidateConfig,
) -> SearchCandidateSet:
    """Return a deterministic, heuristic-ranked candidate set for search expansion."""
    if config.candidate_limit < 1:
        raise ValueError("candidate_limit must be at least 1")

    profile = build_search_position_profile(state)
    legal_actions = get_legal_actions(state, include_skip=config.include_skip)
    groups = partition_actions(legal_actions)
    legal_counts_by_type = {
        action_type: len(groups.get(action_type, [])) for action_type in ActionType
    }
    if not legal_actions:
        return SearchCandidateSet(
            candidates=[],
            legal_action_count=0,
            legal_counts_by_type=legal_counts_by_type,
            candidate_counts_by_type={action_type: 0 for action_type in ActionType},
            profile=profile,
        )

    context = build_heuristic_context(state)
    scored_by_type: dict[ActionType, list[SearchCandidate]] = {}
    for action_type in ActionType:
        scored = [
            _score_candidate(state, action, context, profile)
            for action in groups.get(action_type, [])
        ]
        scored_by_type[action_type] = sorted(scored, key=_candidate_sort_key)

    if config.candidate_limit == 1:
        non_skip_candidates = [
            candidate
            for action_type in _NON_SKIP_TYPES
            for candidate in scored_by_type.get(action_type, [])
        ]
        pool = non_skip_candidates or scored_by_type.get(ActionType.SKIP, [])
        candidates = pool[:1]
        safe_city_count, connection_road_count, rescue_count = _candidate_health_counts(
            candidates,
            state,
            context,
            profile,
        )
        return SearchCandidateSet(
            candidates=candidates,
            legal_action_count=len(legal_actions),
            legal_counts_by_type=legal_counts_by_type,
            candidate_counts_by_type=_candidate_counts(candidates),
            profile=profile,
            safe_city_candidate_count=safe_city_count,
            effective_connection_road_candidate_count=connection_road_count,
            rescue_candidate_count=rescue_count,
        )

    skip_candidates = scored_by_type.get(ActionType.SKIP, []) if config.include_skip else []
    has_non_skip = any(scored_by_type.get(action_type) for action_type in _NON_SKIP_TYPES)
    reserve_skip = bool(skip_candidates and (profile.turns_remaining <= 3 or not has_non_skip))
    non_skip_limit = config.candidate_limit - 1 if reserve_skip else config.candidate_limit

    selected: dict[Action, SearchCandidate] = {}
    quotas = _candidate_type_quotas(profile, non_skip_limit, scored_by_type)
    max_by_type = _candidate_type_maxima(profile, non_skip_limit, quotas, scored_by_type)

    if profile.mode == SEARCH_MODE_EXPAND:
        safe_city_candidates = [
            candidate
            for candidate in scored_by_type.get(ActionType.BUILD_CITY, [])
            if candidate.action.coord is not None
            and _is_safe_city_site(state, candidate.action.coord, context, profile)
        ]
        for candidate in safe_city_candidates[: quotas.get(ActionType.BUILD_CITY, 0)]:
            selected[candidate.action] = candidate

    for action_type in _NON_SKIP_TYPES:
        quota = quotas.get(action_type, 0)
        if quota <= 0:
            continue
        already_selected = sum(
            1 for candidate in selected.values() if candidate.action_type is action_type
        )
        for candidate in scored_by_type.get(action_type, []):
            if already_selected >= quota:
                break
            if candidate.action in selected:
                continue
            selected[candidate.action] = candidate
            already_selected += 1

    remaining_slots = non_skip_limit - len(selected)
    if remaining_slots > 0:
        remaining_pool = [
            candidate
            for action_type in _NON_SKIP_TYPES
            for candidate in scored_by_type.get(action_type, [])
            if candidate.action not in selected
        ]
        for candidate in sorted(remaining_pool, key=_candidate_sort_key):
            if remaining_slots <= 0:
                break
            action_type = candidate.action_type
            if _selected_count(selected, action_type) >= max_by_type.get(
                action_type, non_skip_limit
            ):
                continue
            selected[candidate.action] = candidate
            remaining_slots -= 1

    if reserve_skip:
        selected[skip_candidates[0].action] = skip_candidates[0]

    candidates = sorted(selected.values(), key=_candidate_sort_key)[: config.candidate_limit]
    safe_city_count, connection_road_count, rescue_count = _candidate_health_counts(
        candidates,
        state,
        context,
        profile,
    )
    return SearchCandidateSet(
        candidates=candidates,
        legal_action_count=len(legal_actions),
        legal_counts_by_type=legal_counts_by_type,
        candidate_counts_by_type=_candidate_counts(candidates),
        profile=profile,
        safe_city_candidate_count=safe_city_count,
        effective_connection_road_candidate_count=connection_road_count,
        rescue_candidate_count=rescue_count,
    )


def build_search_position_profile(state: GameState) -> SearchPositionProfile:
    """Return a compact Search-only position profile without Greedy private state."""
    resources = total_resources(state)
    connected = connected_city_count(state)
    isolated = isolated_city_count(state)
    starving = starving_network_count(state)
    city_count_value = len(state.cities)
    network_count = len(state.networks)
    turns_remaining = _turns_remaining(state)
    food_pressure = _max_food_pressure(state)
    target_city_count = search_target_city_count(state)
    expansion_deficit = max(0, target_city_count - city_count_value)
    isolated_risk_limit = max(1, city_count_value // 3)
    network_risk_limit = max(2, city_count_value // 3)
    steady_turn_threshold = max(10, min(18, state.config.turn_limit // 4))
    is_healthy_steady = (
        turns_remaining > steady_turn_threshold
        and starving == 0
        and resources.food >= 0
        and food_pressure <= FOOD_CONSUMPTION_PER_CITY
        and isolated <= isolated_risk_limit
        and network_count <= network_risk_limit
    )

    if starving > 0 or resources.food < 0 or food_pressure >= FOOD_CONSUMPTION_PER_CITY * 2:
        mode = SEARCH_MODE_RESCUE
    elif (
        not is_healthy_steady
        and city_count_value >= 2
        and (isolated > 0 or network_count > max(1, city_count_value // 4))
    ):
        mode = SEARCH_MODE_CONNECT
    elif turns_remaining > 6 and expansion_deficit > 0:
        mode = SEARCH_MODE_EXPAND
    else:
        mode = SEARCH_MODE_FILL

    return SearchPositionProfile(
        mode=mode,
        is_healthy_steady=is_healthy_steady,
        turns_remaining=turns_remaining,
        city_count=city_count_value,
        target_city_count=target_city_count,
        expansion_deficit=expansion_deficit,
        network_count=network_count,
        connected_city_count=connected,
        isolated_city_count=isolated,
        starving_network_count=starving,
        total_food=resources.food,
        food_pressure=food_pressure,
    )


def search_target_city_count(state: GameState) -> int:
    """Return the long-horizon city target used only by Search shaping."""
    board_capacity = sum(
        1 for tile in state.board.values() if tile.base_terrain.value not in {"river", "wasteland"}
    )
    turn_target = max(4, state.config.turn_limit // 4)
    size_target = max(5, state.config.map_size - 1)
    return min(board_capacity, 24, max(turn_target, size_target))


def evaluate_search_leaf(state: GameState) -> SearchLeafEvaluation:
    """Return a stable value estimate for a terminal node in a shallow search tree."""
    breakdown = score_breakdown(state)
    resources = total_resources(state)
    connected = connected_city_count(state)
    isolated = isolated_city_count(state)
    starving = starving_network_count(state)
    network_count = len(state.networks)
    largest_network = largest_network_size(state)
    food_pressure = _max_food_pressure(state)
    starving_turns = sum(network.consecutive_starving_turns for network in state.networks.values())
    profile = build_search_position_profile(state)
    isolated_weight = 450 if profile.is_healthy_steady else 650
    food_pressure_weight = 100 if profile.is_healthy_steady else 150
    fragmentation_weight = 180 if profile.is_healthy_steady else 260

    components = {
        "score_total": breakdown.total * 90,
        "connected_city": connected * 220,
        "largest_network": largest_network * 220,
        "building": building_count(state) * 60,
        "tech": tech_count(state) * 130,
        "food_stock": _bounded_resource_value(
            resources.food, positive_cap=100, negative_cap=160, weight=10
        ),
        "wood_stock": _bounded_resource_value(
            resources.wood, positive_cap=80, negative_cap=40, weight=3
        ),
        "ore_stock": _bounded_resource_value(
            resources.ore, positive_cap=60, negative_cap=40, weight=4
        ),
        "science_stock": _bounded_resource_value(
            resources.science, positive_cap=60, negative_cap=20, weight=3
        ),
        "isolated_penalty": -(isolated * isolated_weight),
        "starving_penalty": -(starving * 2200),
        "starving_turn_penalty": -(starving_turns * 500),
        "food_pressure_penalty": -(food_pressure * food_pressure_weight),
        "fragmentation_penalty": -(max(0, network_count - 1) * fragmentation_weight),
        "expansion_deficit_penalty": -_expansion_deficit_penalty(state, profile),
        "early_fill_penalty": -_early_fill_penalty(state, profile),
        "road_overbuild_penalty": -_road_overbuild_penalty(state, profile),
    }
    value = sum(components.values())

    return SearchLeafEvaluation(
        value=value,
        value_components=components,
        score_total=breakdown.total,
        connected_city_count=connected,
        isolated_city_count=isolated,
        starving_network_count=starving,
        network_count=network_count,
        largest_network_size=largest_network,
        total_food=resources.food,
        total_wood=resources.wood,
        total_ore=resources.ore,
        total_science=resources.science,
        food_pressure=food_pressure,
        starving_turns=starving_turns,
    )


def _score_candidate(
    state: GameState,
    action: Action,
    context: HeuristicContext,
    profile: SearchPositionProfile,
) -> SearchCandidate:
    if action.action_type is ActionType.BUILD_CITY and action.coord is not None:
        score = city_expansion_score_for_context(context, action.coord)
        score += _city_food_safety_score(state, action.coord, context)
        return SearchCandidate(
            action=action,
            action_type=action.action_type,
            rank_score=score,
            reason="city_food_safe_expansion",
        )
    if action.action_type is ActionType.BUILD_ROAD and action.coord is not None:
        score = road_site_score_for_context(context, action.coord)
        score += _road_food_rescue_score(state, action.coord, context)
        if profile.mode in {SEARCH_MODE_EXPAND, SEARCH_MODE_FILL} and not _road_merges_networks(
            action.coord, context
        ):
            score -= 900
        return SearchCandidate(
            action=action,
            action_type=action.action_type,
            rank_score=score,
            reason="road_structure_rescue",
        )
    if action.action_type is ActionType.BUILD_BUILDING:
        score = building_action_score(state, action)
        if action.city_id is not None and action.building_type is BuildingType.FARM:
            city = state.cities[action.city_id]
            network = state.networks[city.network_id]
            pressure = city_network_pressure(network)
            if network.resources.food <= 0:
                score += 520
            elif pressure >= FOOD_CONSUMPTION_PER_CITY:
                score += 260 + (pressure * 8)
        return SearchCandidate(
            action=action,
            action_type=action.action_type,
            rank_score=score,
            reason="building_yield",
        )
    if action.action_type is ActionType.RESEARCH_TECH:
        score = research_action_score(state, action)
        if action.city_id is not None and action.tech_type is TechType.AGRICULTURE:
            city = state.cities[action.city_id]
            network = state.networks[city.network_id]
            pressure = city_network_pressure(network)
            if network.resources.food <= len(network.city_ids) * FOOD_CONSUMPTION_PER_CITY:
                score += 320 + max(0, pressure) * 6
        return SearchCandidate(
            action=action,
            action_type=action.action_type,
            rank_score=score,
            reason="tech_unlock",
        )
    return SearchCandidate(
        action=action,
        action_type=action.action_type,
        rank_score=_SKIP_RANK_SCORE,
        reason="skip_fallback",
    )


def _candidate_sort_key(
    candidate: SearchCandidate,
) -> tuple[int, int, tuple[int, int], int, int, int]:
    action = candidate.action
    coord = action.coord if action.coord is not None else (10**9, 10**9)
    building_type_order = (
        _BUILDING_TYPE_ORDER[action.building_type] if action.building_type is not None else 10**9
    )
    tech_type_order = _TECH_TYPE_ORDER[action.tech_type] if action.tech_type is not None else 10**9
    return (
        -candidate.rank_score,
        _ACTION_TYPE_ORDER[action.action_type],
        coord,
        action.city_id if action.city_id is not None else 10**9,
        building_type_order,
        tech_type_order,
    )


def _bounded_resource_value(
    value: int,
    *,
    positive_cap: int,
    negative_cap: int,
    weight: int,
) -> int:
    bounded = min(max(value, -negative_cap), positive_cap)
    return bounded * weight


def _max_food_pressure(state: GameState) -> int:
    return max((city_network_pressure(network) for network in state.networks.values()), default=0)


def _city_food_safety_score(
    state: GameState,
    coord: tuple[int, int],
    context: HeuristicContext,
) -> int:
    budget = site_budget(state, coord, context)
    pressure = _max_food_pressure(state)
    score = budget.food_balance * 110
    if budget.food_balance >= 2:
        score += 280
    elif budget.food_balance == 1:
        score += 120
    elif budget.food_balance == 0:
        score -= 180
    else:
        score -= 700 + (abs(budget.food_balance) * 220)
    if pressure >= FOOD_CONSUMPTION_PER_CITY and budget.food_balance < 1:
        score -= 260 + (pressure * 28)
    return score


def _candidate_type_quotas(
    profile: SearchPositionProfile,
    limit: int,
    scored_by_type: dict[ActionType, list[SearchCandidate]],
) -> dict[ActionType, int]:
    if limit <= 0:
        return {action_type: 0 for action_type in _NON_SKIP_TYPES}

    if profile.mode == SEARCH_MODE_RESCUE:
        weights = {
            ActionType.BUILD_CITY: 1,
            ActionType.BUILD_ROAD: 3,
            ActionType.BUILD_BUILDING: 4,
            ActionType.RESEARCH_TECH: 3,
        }
    elif profile.mode == SEARCH_MODE_CONNECT:
        weights = {
            ActionType.BUILD_CITY: 3,
            ActionType.BUILD_ROAD: 6,
            ActionType.BUILD_BUILDING: 1,
            ActionType.RESEARCH_TECH: 1,
        }
    elif profile.mode == SEARCH_MODE_EXPAND:
        weights = {
            ActionType.BUILD_CITY: 12,
            ActionType.BUILD_ROAD: 1,
            ActionType.BUILD_BUILDING: 1,
            ActionType.RESEARCH_TECH: 1,
        }
    elif profile.is_healthy_steady:
        weights = {
            ActionType.BUILD_CITY: 5,
            ActionType.BUILD_ROAD: 4,
            ActionType.BUILD_BUILDING: 1,
            ActionType.RESEARCH_TECH: 1,
        }
    else:
        weights = {
            ActionType.BUILD_CITY: 3,
            ActionType.BUILD_ROAD: 2,
            ActionType.BUILD_BUILDING: 3,
            ActionType.RESEARCH_TECH: 3,
        }

    quotas = {action_type: 0 for action_type in _NON_SKIP_TYPES}
    available_types = [
        action_type for action_type in _NON_SKIP_TYPES if scored_by_type.get(action_type)
    ]
    if not available_types:
        return quotas

    remaining = limit
    for action_type in available_types:
        quotas[action_type] = 1
        remaining -= 1
        if remaining <= 0:
            return quotas

    total_weight = sum(weights[action_type] for action_type in available_types)
    for action_type in sorted(
        available_types,
        key=lambda item: (-weights[item], _ACTION_TYPE_ORDER[item]),
    ):
        if remaining <= 0:
            break
        available_room = len(scored_by_type[action_type]) - quotas[action_type]
        if available_room <= 0:
            continue
        extra = max(0, round((limit * weights[action_type] / total_weight) - quotas[action_type]))
        extra = min(extra, available_room, remaining)
        quotas[action_type] += extra
        remaining -= extra

    while remaining > 0:
        progressed = False
        for action_type in sorted(
            available_types,
            key=lambda item: (-weights[item], _ACTION_TYPE_ORDER[item]),
        ):
            if quotas[action_type] >= len(scored_by_type[action_type]):
                continue
            quotas[action_type] += 1
            remaining -= 1
            progressed = True
            if remaining <= 0:
                break
        if not progressed:
            break
    return quotas


def _candidate_type_maxima(
    profile: SearchPositionProfile,
    limit: int,
    quotas: dict[ActionType, int],
    scored_by_type: dict[ActionType, list[SearchCandidate]],
) -> dict[ActionType, int]:
    maxima = {
        action_type: min(limit, len(scored_by_type.get(action_type, [])))
        for action_type in _NON_SKIP_TYPES
    }
    if profile.mode == SEARCH_MODE_EXPAND and profile.turns_remaining > 10:
        maxima[ActionType.BUILD_BUILDING] = quotas.get(ActionType.BUILD_BUILDING, 0)
        maxima[ActionType.RESEARCH_TECH] = quotas.get(ActionType.RESEARCH_TECH, 0)
    elif profile.is_healthy_steady and profile.mode == SEARCH_MODE_FILL:
        maxima[ActionType.BUILD_BUILDING] = min(
            maxima[ActionType.BUILD_BUILDING],
            max(1, limit // 3),
        )
        maxima[ActionType.RESEARCH_TECH] = min(
            maxima[ActionType.RESEARCH_TECH],
            max(1, limit // 3),
        )
    return maxima


def _candidate_counts(candidates: list[SearchCandidate]) -> dict[ActionType, int]:
    return {
        action_type: sum(1 for candidate in candidates if candidate.action_type is action_type)
        for action_type in ActionType
    }


def _candidate_health_counts(
    candidates: list[SearchCandidate],
    state: GameState,
    context: HeuristicContext,
    profile: SearchPositionProfile,
) -> tuple[int, int, int]:
    safe_city_count = 0
    connection_road_count = 0
    rescue_count = 0
    for candidate in candidates:
        action = candidate.action
        if action.action_type is ActionType.BUILD_CITY and action.coord is not None:
            if _is_safe_city_site(state, action.coord, context, profile):
                safe_city_count += 1
            if _city_food_safety_score(state, action.coord, context) > 0:
                rescue_count += 1
            continue
        if action.action_type is ActionType.BUILD_ROAD and action.coord is not None:
            if _road_merges_networks(action.coord, context):
                connection_road_count += 1
            if _road_food_rescue_score(state, action.coord, context) > 0:
                rescue_count += 1
            continue
        if action.action_type is ActionType.BUILD_BUILDING:
            if action.city_id is None or action.building_type is not BuildingType.FARM:
                continue
            city = state.cities[action.city_id]
            network = state.networks[city.network_id]
            if network.resources.food <= 0 or city_network_pressure(network) >= 0:
                rescue_count += 1
            continue
        if action.action_type is ActionType.RESEARCH_TECH:
            if action.city_id is None or action.tech_type is not TechType.AGRICULTURE:
                continue
            city = state.cities[action.city_id]
            network = state.networks[city.network_id]
            if network.resources.food <= len(network.city_ids) * FOOD_CONSUMPTION_PER_CITY:
                rescue_count += 1
    return safe_city_count, connection_road_count, rescue_count


def _selected_count(
    selected: dict[Action, SearchCandidate],
    action_type: ActionType,
) -> int:
    return sum(1 for candidate in selected.values() if candidate.action_type is action_type)


def _is_safe_city_site(
    state: GameState,
    coord: tuple[int, int],
    context: HeuristicContext,
    profile: SearchPositionProfile,
) -> bool:
    budget = site_budget(state, coord, context)
    if budget.food_balance >= 0:
        return True
    return profile.total_food >= (profile.city_count + 1) * FOOD_CONSUMPTION_PER_CITY * 4


def _expansion_deficit_penalty(
    state: GameState,
    profile: SearchPositionProfile | None = None,
) -> int:
    profile = profile or build_search_position_profile(state)
    if profile.turns_remaining <= 6 or profile.expansion_deficit <= 0:
        return 0
    weight = 1_500 if profile.is_healthy_steady else 2_400
    return min(36_000, profile.expansion_deficit * weight)


def _early_fill_penalty(
    state: GameState,
    profile: SearchPositionProfile | None = None,
) -> int:
    profile = profile or build_search_position_profile(state)
    if profile.turns_remaining <= 10 or profile.expansion_deficit <= 0:
        return 0
    fill_count = building_count(state) + tech_count(state)
    allowed_fill = max(1, profile.city_count // 2)
    weight = 2_200 if profile.is_healthy_steady else 3_800
    return max(0, fill_count - allowed_fill) * weight


def _road_overbuild_penalty(
    state: GameState,
    profile: SearchPositionProfile | None = None,
) -> int:
    city_count_value = len(state.cities)
    if city_count_value <= 0:
        return len(state.roads) * 4_000
    road_allowance = max(2, city_count_value // 2)
    profile = profile or build_search_position_profile(state)
    weight = 2_500 if profile.is_healthy_steady else 4_000
    return max(0, len(state.roads) - road_allowance) * weight


def _road_merges_networks(coord: tuple[int, int], context: HeuristicContext) -> bool:
    passable_map = context_passable_network_map(context)
    adjacent_network_ids = {
        passable_map[neighbor]
        for neighbor in (
            (coord[0] - 1, coord[1]),
            (coord[0] + 1, coord[1]),
            (coord[0], coord[1] - 1),
            (coord[0], coord[1] + 1),
        )
        if neighbor in passable_map
    }
    return len(adjacent_network_ids) >= 2


def _turns_remaining(state: GameState) -> int:
    return max(0, state.config.turn_limit - state.turn)


def _road_food_rescue_score(
    state: GameState,
    coord: tuple[int, int],
    context: HeuristicContext,
) -> int:
    passable_map = context_passable_network_map(context)
    adjacent_network_ids = {
        passable_map[neighbor]
        for neighbor in (
            (coord[0] - 1, coord[1]),
            (coord[0] + 1, coord[1]),
            (coord[0], coord[1] - 1),
            (coord[0], coord[1] + 1),
        )
        if neighbor in passable_map
    }
    if len(adjacent_network_ids) < 2:
        return 0

    networks = [state.networks[network_id] for network_id in adjacent_network_ids]
    pressures = [city_network_pressure(network) for network in networks]
    has_starving = any(network.resources.food <= 0 for network in networks)
    has_food_buffer = any(
        network.resources.food >= len(network.city_ids) * FOOD_CONSUMPTION_PER_CITY * 2
        for network in networks
    )
    score = 180 + (sum(len(network.city_ids) for network in networks) * 30)
    if has_starving and has_food_buffer:
        score += 760
    elif has_starving:
        score += 420
    if max(pressures, default=0) >= FOOD_CONSUMPTION_PER_CITY:
        score += max(pressures) * 12
    return score
