"""Reusable candidate and leaf-evaluation helpers for search policies."""

from __future__ import annotations

from dataclasses import dataclass

from microciv.ai.heuristics import (
    BUILDING_RESOURCE_TYPE,
    HeuristicContext,
    build_heuristic_context,
    building_action_score,
    city_expansion_score_for_context,
    city_network_pressure,
    city_site_score_for_context,
    context_passable_network_map,
    partition_actions,
    research_action_score,
    resource_ring_bonus_for_context,
    resource_ring_counts_for_context,
    road_site_score_for_context,
    site_budget,
)
from microciv.ai.policy import get_legal_actions, simulate_action
from microciv.constants import COVER_REWARDS, FOOD_CONSUMPTION_PER_CITY
from microciv.game.actions import Action
from microciv.game.enums import (
    ActionType,
    BuildingType,
    MapDifficulty,
    OccupantType,
    ResourceType,
    TechType,
    TerrainType,
)
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
from microciv.utils.grid import Coord, cardinal_neighbors, moore_neighbors

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
    safe_target_city_count: int
    safe_expansion_deficit: int
    road_overbuild: int
    fill_count: int
    is_small_long_map: bool


@dataclass(slots=True, frozen=True)
class SearchCandidateConfig:
    candidate_limit: int
    include_skip: bool = True
    forced_actions: tuple[Action, ...] = ()


@dataclass(slots=True, frozen=True)
class SearchCandidate:
    action: Action
    action_type: ActionType
    rank_score: int
    reason: str
    effective: bool = False
    risk: bool = False


@dataclass(slots=True, frozen=True)
class RoadCandidateProfile:
    merge_networks: bool
    connected_city_delta: int
    network_delta: int
    starvation_bridge: bool
    path_progress_score: int
    resource_frontier: int
    redundant: bool
    after_full_connectivity: bool

    @property
    def effective_connection(self) -> bool:
        return self.merge_networks or self.connected_city_delta > 0

    @property
    def effective(self) -> bool:
        return self.effective_connection or self.starvation_bridge or self.path_progress_score > 0


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
    effective_city_candidate_count: int = 0
    redundant_road_candidate_count: int = 0
    high_roi_building_candidate_count: int = 0
    gated_candidate_count: int = 0


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
    raw_scored_by_type: dict[ActionType, list[SearchCandidate]] = {}
    for action_type in ActionType:
        scored = [
            _score_candidate(state, action, context, profile)
            for action in groups.get(action_type, [])
        ]
        raw_scored_by_type[action_type] = sorted(scored, key=_candidate_sort_key)
    scored_by_type, gated_candidate_count = _candidate_effective_pool(
        state,
        context,
        profile,
        raw_scored_by_type,
    )

    if config.candidate_limit == 1:
        non_skip_candidates = [
            candidate
            for action_type in _NON_SKIP_TYPES
            for candidate in scored_by_type.get(action_type, [])
        ]
        pool = non_skip_candidates or scored_by_type.get(ActionType.SKIP, [])
        candidates = pool[:1]
        (
            safe_city_count,
            connection_road_count,
            rescue_count,
            effective_city_count,
            redundant_road_count,
            high_roi_building_count,
        ) = _candidate_health_counts(
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
            effective_city_candidate_count=effective_city_count,
            redundant_road_candidate_count=redundant_road_count,
            high_roi_building_candidate_count=high_roi_building_count,
            gated_candidate_count=gated_candidate_count,
        )

    skip_candidates = scored_by_type.get(ActionType.SKIP, []) if config.include_skip else []
    has_non_skip = any(scored_by_type.get(action_type) for action_type in _NON_SKIP_TYPES)
    reserve_skip = bool(skip_candidates and (profile.turns_remaining <= 3 or not has_non_skip))
    non_skip_limit = config.candidate_limit - 1 if reserve_skip else config.candidate_limit

    selected: dict[Action, SearchCandidate] = {}
    quotas = _candidate_type_quotas(profile, non_skip_limit, scored_by_type)
    max_by_type = _candidate_type_maxima(profile, non_skip_limit, quotas, scored_by_type)
    forced_candidates = _forced_candidates(config.forced_actions, raw_scored_by_type)

    if profile.mode == SEARCH_MODE_EXPAND:
        safe_city_candidates = [
            candidate
            for candidate in scored_by_type.get(ActionType.BUILD_CITY, [])
            if candidate.action.coord is not None
            and _is_safe_city_site(state, candidate.action.coord, context, profile)
        ]
        for candidate in safe_city_candidates[: quotas.get(ActionType.BUILD_CITY, 0)]:
            selected[candidate.action] = candidate

    for candidate in forced_candidates:
        if len(selected) >= non_skip_limit:
            worst_action = max(selected.values(), key=_candidate_sort_key).action
            del selected[worst_action]
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
    (
        safe_city_count,
        connection_road_count,
        rescue_count,
        effective_city_count,
        redundant_road_count,
        high_roi_building_count,
    ) = _candidate_health_counts(
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
        effective_city_candidate_count=effective_city_count,
        redundant_road_candidate_count=redundant_road_count,
        high_roi_building_candidate_count=high_roi_building_count,
        gated_candidate_count=gated_candidate_count,
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
    fill_count = building_count(state) + tech_count(state)
    road_overbuild = _road_overbuild_metric(state)
    is_small_long_map = state.config.map_size <= 12 and state.config.turn_limit >= 80
    safe_target_city_count = _safe_target_city_count(
        state=state,
        target_city_count=target_city_count,
        city_count_value=city_count_value,
        total_food=resources.food,
        food_pressure=food_pressure,
        starving_network_count_value=starving,
        is_small_long_map=is_small_long_map,
    )
    expansion_deficit = max(0, target_city_count - city_count_value)
    safe_expansion_deficit = max(0, safe_target_city_count - city_count_value)
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
    elif turns_remaining > 6 and safe_expansion_deficit > 0:
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
        safe_target_city_count=safe_target_city_count,
        safe_expansion_deficit=safe_expansion_deficit,
        road_overbuild=road_overbuild,
        fill_count=fill_count,
        is_small_long_map=is_small_long_map,
    )


def search_target_city_count(state: GameState) -> int:
    """Return the long-horizon city target used only by Search shaping."""
    board_capacity = sum(
        1
        for tile in state.board.values()
        if tile.base_terrain not in {TerrainType.RIVER, TerrainType.WASTELAND}
    )
    if board_capacity <= 0:
        return 0
    turn_bonus = 0
    if state.config.turn_limit > 100:
        turn_bonus = 2
    elif state.config.turn_limit > 50:
        turn_bonus = 1
    difficulty_penalty = 1 if state.config.map_difficulty is MapDifficulty.HARD else 0
    size_target = max(5, (state.config.map_size * 3 + 2) // 4)
    capacity_target = max(5, board_capacity // 8)
    strategic_target = max(4, size_target + turn_bonus - difficulty_penalty)
    return min(board_capacity, 24, capacity_target, strategic_target)


def _safe_target_city_count(
    *,
    state: GameState,
    target_city_count: int,
    city_count_value: int,
    total_food: int,
    food_pressure: int,
    starving_network_count_value: int,
    is_small_long_map: bool,
) -> int:
    if city_count_value <= 0:
        return target_city_count
    if starving_network_count_value > 0 or total_food < 0:
        return min(target_city_count, city_count_value)

    safe_target = target_city_count
    if food_pressure >= FOOD_CONSUMPTION_PER_CITY * 2:
        safe_target = min(safe_target, city_count_value)
    elif food_pressure >= FOOD_CONSUMPTION_PER_CITY:
        safe_target = min(safe_target, city_count_value + 1)

    if is_small_long_map:
        early_city_cap = max(4, min(target_city_count, state.config.map_size - 2))
        first_half_turn = state.turn <= max(20, state.config.turn_limit // 2)
        if first_half_turn and city_count_value >= early_city_cap:
            safe_target = min(safe_target, city_count_value)

    food_buffer_slots = max(0, total_food // (FOOD_CONSUMPTION_PER_CITY * 6))
    if total_food < city_count_value * FOOD_CONSUMPTION_PER_CITY:
        safe_target = min(safe_target, city_count_value + food_buffer_slots)
    return max(0, safe_target)


def _road_overbuild_metric(state: GameState) -> int:
    city_count_value = len(state.cities)
    if city_count_value <= 0:
        return len(state.roads)
    road_allowance = max(2, city_count_value // 2)
    return max(0, len(state.roads) - road_allowance)


def evaluate_search_leaf(
    state: GameState,
    *,
    root_state: GameState | None = None,
) -> SearchLeafEvaluation:
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
    root_profile = build_search_position_profile(root_state) if root_state is not None else profile
    root_breakdown = score_breakdown(root_state) if root_state is not None else breakdown
    root_context = build_heuristic_context(root_state) if root_state is not None else None
    root_connected = connected_city_count(root_state) if root_state is not None else connected
    root_isolated = isolated_city_count(root_state) if root_state is not None else isolated
    root_starving = starving_network_count(root_state) if root_state is not None else starving
    root_network_count = len(root_state.networks) if root_state is not None else network_count
    root_buildings = building_count(root_state) if root_state is not None else building_count(state)
    root_techs = tech_count(root_state) if root_state is not None else tech_count(state)
    root_food_pressure = _max_food_pressure(root_state) if root_state is not None else food_pressure
    root_roads = len(root_state.roads) if root_state is not None else len(state.roads)

    score_delta = breakdown.total - root_breakdown.total
    connected_delta = connected - root_connected
    isolated_delta = isolated - root_isolated
    starving_delta = starving - root_starving
    network_reduction = max(0, root_network_count - network_count)
    building_delta = building_count(state) - root_buildings
    tech_delta = tech_count(state) - root_techs
    food_pressure_delta = food_pressure - root_food_pressure
    road_delta = len(state.roads) - root_roads
    city_quality_delta = _city_quality_delta(state, root_state, root_context)

    isolated_weight = 450 if profile.is_healthy_steady else 650
    food_pressure_weight = 135 if profile.is_healthy_steady else 190
    fragmentation_weight = 180 if profile.is_healthy_steady else 260
    fill_weight = 320 if root_profile.mode == SEARCH_MODE_FILL else 80
    tech_weight = 260 if root_profile.mode == SEARCH_MODE_FILL else 70

    components = {
        "score_total": breakdown.total * 26,
        "score_delta": score_delta * 90,
        "resource_ring_delta": (
            (breakdown.resource_ring_score - root_breakdown.resource_ring_score) * 135
        ),
        "city_quality_delta": city_quality_delta * 110,
        "connected_city_delta": max(0, connected_delta) * 900,
        "network_reduction": network_reduction * 850,
        "building_delta": max(0, building_delta) * fill_weight,
        "tech_delta": max(0, tech_delta) * tech_weight,
        "food_stock": _bounded_resource_value(
            resources.food, positive_cap=100, negative_cap=160, weight=8
        ),
        "wood_stock": _bounded_resource_value(
            resources.wood, positive_cap=80, negative_cap=40, weight=2
        ),
        "ore_stock": _bounded_resource_value(
            resources.ore, positive_cap=60, negative_cap=40, weight=3
        ),
        "science_stock": _bounded_resource_value(
            resources.science, positive_cap=60, negative_cap=20, weight=2
        ),
        "isolated_penalty": -(isolated * isolated_weight),
        "starving_penalty": -(starving * 2200),
        "starving_turn_penalty": -(starving_turns * 500),
        "food_pressure_penalty": -(food_pressure * food_pressure_weight),
        "fragmentation_penalty": -(max(0, network_count - 1) * fragmentation_weight),
        "expansion_deficit_penalty": -_expansion_deficit_penalty(state, profile),
        "early_fill_penalty": -_early_fill_penalty(state, profile),
        "road_overbuild_penalty": -_road_overbuild_penalty(state, profile),
        "starving_delta_penalty": -(max(0, starving_delta) * 8_000),
        "food_pressure_delta_penalty": -(max(0, food_pressure_delta) * 420),
        "isolated_delta_penalty": -(max(0, isolated_delta) * 2_200),
        "network_delta_penalty": -(max(0, network_count - root_network_count) * 2_400),
        "road_delta_penalty": -(
            max(0, road_delta - max(1, connected_delta + network_reduction)) * 1_700
        ),
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
        safe = _is_safe_city_site(state, action.coord, context, profile)
        food_delta = _city_food_pressure_delta(state, action.coord, context)
        budget = site_budget(state, action.coord, context)
        ring_bonus = resource_ring_bonus_for_context(context, action.coord)
        effective = _city_food_pressure_delta(state, action.coord, context) < 0 or safe
        score = city_expansion_score_for_context(context, action.coord)
        score += _city_food_safety_score(state, action.coord, context)
        score += ring_bonus * (4 if profile.is_healthy_steady else 3)
        score += city_site_score_for_context(context, action.coord)
        if safe:
            score += 1_400
        if ring_bonus >= 420 and budget.food_balance >= 0:
            score += 1_600
        elif ring_bonus >= 260 and budget.food_balance >= 1:
            score += 900
        if food_delta < 0:
            score += 700
        if profile.mode == SEARCH_MODE_EXPAND and profile.turns_remaining > 10:
            if budget.food_balance <= 0 and ring_bonus < 300:
                score -= 2_000
            if budget.food_balance < 0:
                score -= 2_800
        if profile.city_count >= profile.safe_target_city_count and not safe:
            score -= 3_600
        if profile.mode == SEARCH_MODE_RESCUE and not _city_can_rescue_food_pressure(
            state, action.coord, context
        ):
            score -= 5_500
        return SearchCandidate(
            action=action,
            action_type=action.action_type,
            rank_score=score,
            reason="city_safe_expansion" if safe else "city_risky_expansion",
            effective=effective,
            risk=not safe,
        )
    if action.action_type is ActionType.BUILD_ROAD and action.coord is not None:
        road_profile = _road_candidate_profile(state, action.coord, context, profile)
        score = road_site_score_for_context(context, action.coord)
        score += _road_food_rescue_score(state, action.coord, context)
        score += road_profile.connected_city_delta * 1_300
        score += max(0, -road_profile.network_delta) * 900
        score += road_profile.path_progress_score * 120
        if road_profile.starvation_bridge:
            score += 2_400
        if road_profile.resource_frontier >= 4 and profile.road_overbuild == 0:
            score += 260
        if road_profile.redundant:
            score -= 3_500
        if road_profile.after_full_connectivity and road_profile.resource_frontier < 4:
            score -= 6_000
        if profile.road_overbuild > 0 and not road_profile.effective:
            score -= 5_000 + (profile.road_overbuild * 800)
        if profile.mode in {SEARCH_MODE_EXPAND, SEARCH_MODE_FILL} and not road_profile.effective:
            score -= 1_800
        return SearchCandidate(
            action=action,
            action_type=action.action_type,
            rank_score=score,
            reason=_road_candidate_reason(road_profile),
            effective=road_profile.effective,
            risk=road_profile.redundant,
        )
    if action.action_type is ActionType.BUILD_BUILDING:
        score = building_action_score(state, action)
        score += _building_roi_score(state, action, context)
        rescue_delta = _rescue_action_pressure_delta(state, action)
        if action.city_id is not None and action.building_type is BuildingType.FARM:
            city = state.cities[action.city_id]
            network = state.networks[city.network_id]
            pressure = city_network_pressure(network)
            if network.resources.food <= 0:
                score += 1_500
            elif pressure >= FOOD_CONSUMPTION_PER_CITY:
                score += 620 + (pressure * 12)
        if profile.mode == SEARCH_MODE_EXPAND and profile.turns_remaining > 10:
            score -= 420
            if profile.safe_expansion_deficit > 0 and not _is_high_roi_building(
                state,
                action,
                context,
            ):
                score -= 1_200
        if profile.mode == SEARCH_MODE_RESCUE and not _is_rescue_action(
            state, action, context, profile
        ):
            score -= 4_000
        elif profile.mode == SEARCH_MODE_RESCUE and rescue_delta < 0:
            score += abs(rescue_delta) * 260
        return SearchCandidate(
            action=action,
            action_type=action.action_type,
            rank_score=score,
            reason="building_rescue"
            if _is_rescue_action(state, action, context, profile)
            else "building_yield",
            effective=_is_high_roi_building(state, action, context)
            or _is_rescue_action(state, action, context, profile),
            risk=False,
        )
    if action.action_type is ActionType.RESEARCH_TECH:
        score = research_action_score(state, action)
        rescue_delta = _rescue_action_pressure_delta(state, action)
        if action.city_id is not None and action.tech_type is TechType.AGRICULTURE:
            city = state.cities[action.city_id]
            network = state.networks[city.network_id]
            pressure = city_network_pressure(network)
            if network.resources.food <= len(network.city_ids) * FOOD_CONSUMPTION_PER_CITY:
                score += 900 + max(0, pressure) * 10
        if profile.mode == SEARCH_MODE_EXPAND and profile.turns_remaining > 10:
            score -= 420
            if profile.safe_expansion_deficit > 0:
                score -= 900
        if profile.mode == SEARCH_MODE_RESCUE and not _is_rescue_action(
            state, action, context, profile
        ):
            score -= 4_000
        elif profile.mode == SEARCH_MODE_RESCUE and rescue_delta < 0:
            score += abs(rescue_delta) * 220
        return SearchCandidate(
            action=action,
            action_type=action.action_type,
            rank_score=score,
            reason="tech_rescue"
            if _is_rescue_action(state, action, context, profile)
            else "tech_unlock",
            effective=_is_rescue_action(state, action, context, profile),
            risk=False,
        )
    return SearchCandidate(
        action=action,
        action_type=action.action_type,
        rank_score=_SKIP_RANK_SCORE,
        reason="skip_fallback",
    )


def _candidate_effective_pool(
    state: GameState,
    context: HeuristicContext,
    profile: SearchPositionProfile,
    scored_by_type: dict[ActionType, list[SearchCandidate]],
) -> tuple[dict[ActionType, list[SearchCandidate]], int]:
    filtered: dict[ActionType, list[SearchCandidate]] = {
        action_type: list(candidates) for action_type, candidates in scored_by_type.items()
    }
    gated_count = 0

    city_candidates = filtered.get(ActionType.BUILD_CITY, [])
    if city_candidates:
        if profile.mode != SEARCH_MODE_RESCUE and profile.safe_expansion_deficit <= 0:
            allowed_cities = [
                candidate
                for candidate in city_candidates
                if candidate.action.coord is not None
                and _city_can_rescue_food_pressure(state, candidate.action.coord, context)
            ]
            gated_count += len(city_candidates) - len(allowed_cities)
            filtered[ActionType.BUILD_CITY] = allowed_cities
            city_candidates = allowed_cities
        safe_cities = [
            candidate
            for candidate in city_candidates
            if candidate.action.coord is not None
            and _is_safe_city_site(state, candidate.action.coord, context, profile)
        ]
        if safe_cities:
            gated_count += len(city_candidates) - len(safe_cities)
            filtered[ActionType.BUILD_CITY] = safe_cities
        elif profile.mode == SEARCH_MODE_RESCUE:
            rescue_cities = [
                candidate
                for candidate in city_candidates
                if candidate.action.coord is not None
                and _city_can_rescue_food_pressure(state, candidate.action.coord, context)
            ]
            gated_count += len(city_candidates) - len(rescue_cities)
            filtered[ActionType.BUILD_CITY] = rescue_cities

    road_candidates = filtered.get(ActionType.BUILD_ROAD, [])
    if road_candidates:
        road_profiles = {
            candidate.action: _road_candidate_profile(
                state,
                candidate.action.coord,
                context,
                profile,
            )
            for candidate in road_candidates
            if candidate.action.coord is not None
        }
        effective_roads = [
            candidate
            for candidate in road_candidates
            if road_profiles.get(candidate.action) is not None
            and road_profiles[candidate.action].effective
        ]
        connection_roads = [
            candidate
            for candidate in road_candidates
            if road_profiles.get(candidate.action) is not None
            and road_profiles[candidate.action].effective_connection
        ]
        path_roads = [
            candidate
            for candidate in road_candidates
            if road_profiles.get(candidate.action) is not None
            and road_profiles[candidate.action].path_progress_score > 0
        ]
        frontier_roads = [
            candidate
            for candidate in road_candidates
            if road_profiles.get(candidate.action) is not None
            and road_profiles[candidate.action].resource_frontier >= 4
            and not road_profiles[candidate.action].after_full_connectivity
            and profile.road_overbuild == 0
        ]
        if profile.mode == SEARCH_MODE_CONNECT:
            if connection_roads:
                allowed = _unique_candidates([*connection_roads, *path_roads])
            else:
                allowed = path_roads[:2]
            gated_count += len(road_candidates) - len(allowed)
            filtered[ActionType.BUILD_ROAD] = allowed
        elif profile.mode == SEARCH_MODE_RESCUE:
            rescue_roads = [
                candidate
                for candidate in road_candidates
                if road_profiles.get(candidate.action) is not None
                and (
                    road_profiles[candidate.action].starvation_bridge
                    or road_profiles[candidate.action].effective_connection
                )
            ]
            gated_count += len(road_candidates) - len(rescue_roads)
            filtered[ActionType.BUILD_ROAD] = rescue_roads
        elif profile.mode in {SEARCH_MODE_EXPAND, SEARCH_MODE_FILL}:
            allowed = _unique_candidates([*effective_roads, *frontier_roads])
            if not allowed and profile.mode == SEARCH_MODE_FILL and profile.road_overbuild == 0:
                allowed = frontier_roads[:1]
            gated_count += len(road_candidates) - len(allowed)
            filtered[ActionType.BUILD_ROAD] = allowed
        elif profile.road_overbuild > 0:
            allowed = effective_roads
            gated_count += len(road_candidates) - len(allowed)
            filtered[ActionType.BUILD_ROAD] = allowed

    if profile.mode == SEARCH_MODE_RESCUE:
        for action_type in (ActionType.BUILD_BUILDING, ActionType.RESEARCH_TECH):
            candidates = filtered.get(action_type, [])
            rescue_candidates = [
                candidate
                for candidate in candidates
                if _is_rescue_action(state, candidate.action, context, profile)
            ]
            if rescue_candidates:
                gated_count += len(candidates) - len(rescue_candidates)
                filtered[action_type] = rescue_candidates

    return {
        action_type: sorted(candidates, key=_candidate_sort_key)
        for action_type, candidates in filtered.items()
    }, gated_count


def _unique_candidates(candidates: list[SearchCandidate]) -> list[SearchCandidate]:
    result: dict[Action, SearchCandidate] = {}
    for candidate in candidates:
        result.setdefault(candidate.action, candidate)
    return sorted(result.values(), key=_candidate_sort_key)


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
            ActionType.BUILD_CITY: 2,
            ActionType.BUILD_ROAD: 6,
            ActionType.BUILD_BUILDING: 3,
            ActionType.RESEARCH_TECH: 3,
        }
    elif profile.mode == SEARCH_MODE_CONNECT:
        weights = {
            ActionType.BUILD_CITY: 2,
            ActionType.BUILD_ROAD: 8,
            ActionType.BUILD_BUILDING: 1,
            ActionType.RESEARCH_TECH: 1,
        }
    elif profile.mode == SEARCH_MODE_EXPAND:
        weights = {
            ActionType.BUILD_CITY: 14,
            ActionType.BUILD_ROAD: 1,
            ActionType.BUILD_BUILDING: 1,
            ActionType.RESEARCH_TECH: 1,
        }
    elif profile.is_healthy_steady:
        weights = {
            ActionType.BUILD_CITY: 1,
            ActionType.BUILD_ROAD: 1,
            ActionType.BUILD_BUILDING: 5,
            ActionType.RESEARCH_TECH: 3,
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
        if weights[action_type] <= 0:
            continue
        quotas[action_type] = 1
        remaining -= 1
        if remaining <= 0:
            return quotas

    total_weight = sum(weights[action_type] for action_type in available_types)
    if total_weight <= 0:
        return quotas
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
    if (
        profile.mode == SEARCH_MODE_EXPAND
        and scored_by_type.get(ActionType.BUILD_CITY)
        and limit >= 4
    ):
        minimum_city_quota = min(
            len(scored_by_type[ActionType.BUILD_CITY]),
            max(2, (limit * 2) // 3),
        )
        if quotas[ActionType.BUILD_CITY] < minimum_city_quota:
            needed = minimum_city_quota - quotas[ActionType.BUILD_CITY]
            for action_type in (
                ActionType.BUILD_ROAD,
                ActionType.BUILD_BUILDING,
                ActionType.RESEARCH_TECH,
            ):
                removable = min(needed, max(0, quotas[action_type] - 1))
                quotas[action_type] -= removable
                quotas[ActionType.BUILD_CITY] += removable
                needed -= removable
                if needed <= 0:
                    break
    if profile.mode == SEARCH_MODE_EXPAND and profile.turns_remaining > 10:
        quotas[ActionType.BUILD_BUILDING] = min(quotas[ActionType.BUILD_BUILDING], 1)
        quotas[ActionType.RESEARCH_TECH] = min(quotas[ActionType.RESEARCH_TECH], 1)
    return quotas


def _forced_candidates(
    forced_actions: tuple[Action, ...],
    scored_by_type: dict[ActionType, list[SearchCandidate]],
) -> list[SearchCandidate]:
    if not forced_actions:
        return []
    by_action = {
        candidate.action: candidate
        for candidates in scored_by_type.values()
        for candidate in candidates
    }
    return [
        by_action[action]
        for action in forced_actions
        if action in by_action and action.action_type in _NON_SKIP_TYPES
    ]


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
        fill_cap = 1 if profile.safe_expansion_deficit > 0 else 2
        maxima[ActionType.BUILD_BUILDING] = min(maxima[ActionType.BUILD_BUILDING], fill_cap)
        maxima[ActionType.RESEARCH_TECH] = min(maxima[ActionType.RESEARCH_TECH], fill_cap)
        if profile.road_overbuild > 0:
            maxima[ActionType.BUILD_ROAD] = min(maxima[ActionType.BUILD_ROAD], 1)
    elif profile.mode == SEARCH_MODE_CONNECT:
        if scored_by_type.get(ActionType.BUILD_ROAD):
            maxima[ActionType.BUILD_BUILDING] = min(maxima[ActionType.BUILD_BUILDING], 1)
            maxima[ActionType.RESEARCH_TECH] = min(maxima[ActionType.RESEARCH_TECH], 1)
    elif profile.mode == SEARCH_MODE_RESCUE:
        maxima[ActionType.BUILD_CITY] = min(maxima[ActionType.BUILD_CITY], 1)
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
) -> tuple[int, int, int, int, int, int]:
    safe_city_count = 0
    connection_road_count = 0
    rescue_count = 0
    effective_city_count = 0
    redundant_road_count = 0
    high_roi_building_count = 0
    for candidate in candidates:
        action = candidate.action
        if action.action_type is ActionType.BUILD_CITY and action.coord is not None:
            if _is_safe_city_site(state, action.coord, context, profile):
                safe_city_count += 1
                effective_city_count += 1
            if _city_food_safety_score(state, action.coord, context) > 0:
                rescue_count += 1
            continue
        if action.action_type is ActionType.BUILD_ROAD and action.coord is not None:
            road_profile = _road_candidate_profile(state, action.coord, context, profile)
            if road_profile.effective_connection:
                connection_road_count += 1
            if road_profile.redundant:
                redundant_road_count += 1
            if _road_food_rescue_score(state, action.coord, context) > 0:
                rescue_count += 1
            continue
        if action.action_type is ActionType.BUILD_BUILDING:
            if _is_high_roi_building(state, action, context):
                high_roi_building_count += 1
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
    return (
        safe_city_count,
        connection_road_count,
        rescue_count,
        effective_city_count,
        redundant_road_count,
        high_roi_building_count,
    )


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
    future_food, future_pressure = _estimated_city_food_after(state, coord, context)
    if future_food <= 0:
        return False
    if profile.starving_network_count > 0 and budget.food_balance < 2:
        return False
    if profile.city_count >= profile.safe_target_city_count and budget.food_balance < 2:
        return False
    if profile.is_small_long_map and profile.city_count >= profile.safe_target_city_count - 1:
        if budget.food_balance < 2:
            return False
    if budget.food_balance < 0:
        return (
            profile.total_food >= (profile.city_count + 1) * FOOD_CONSUMPTION_PER_CITY * 8
            and future_pressure <= profile.food_pressure
        )
    if future_pressure > max(
        profile.food_pressure + FOOD_CONSUMPTION_PER_CITY,
        FOOD_CONSUMPTION_PER_CITY * 3,
    ):
        return False
    return True


def _city_can_rescue_food_pressure(
    state: GameState,
    coord: Coord,
    context: HeuristicContext,
) -> bool:
    budget = site_budget(state, coord, context)
    return budget.food_balance >= 2 and _city_food_pressure_delta(state, coord, context) < 0


def _city_food_pressure_delta(
    state: GameState,
    coord: Coord,
    context: HeuristicContext,
) -> int:
    _, future_pressure = _estimated_city_food_after(state, coord, context)
    return future_pressure - _max_food_pressure(state)


def _estimated_city_food_after(
    state: GameState,
    coord: Coord,
    context: HeuristicContext,
) -> tuple[int, int]:
    adjacent_network_ids = _adjacent_network_ids(coord, context)
    budget = site_budget(state, coord, context)
    cover_food = COVER_REWARDS[state.board[coord].base_terrain].get(ResourceType.FOOD, 0)
    if adjacent_network_ids:
        city_count_value = 1 + sum(
            len(state.networks[network_id].city_ids) for network_id in adjacent_network_ids
        )
        food_after = (
            sum(state.networks[network_id].resources.food for network_id in adjacent_network_ids)
            + cover_food
            + budget.food_yield
            - (city_count_value * FOOD_CONSUMPTION_PER_CITY)
        )
        future_pressure = city_count_value * FOOD_CONSUMPTION_PER_CITY * 2 - food_after
        other_pressures = [
            city_network_pressure(network)
            for network_id, network in state.networks.items()
            if network_id not in adjacent_network_ids
        ]
        return food_after, max([future_pressure, *other_pressures], default=future_pressure)

    food_after = cover_food + budget.food_yield - FOOD_CONSUMPTION_PER_CITY
    future_pressure = FOOD_CONSUMPTION_PER_CITY * 2 - food_after
    other_pressures = [city_network_pressure(network) for network in state.networks.values()]
    return food_after, max([future_pressure, *other_pressures], default=future_pressure)


def _adjacent_network_ids(coord: Coord, context: HeuristicContext) -> set[int]:
    passable_map = context_passable_network_map(context)
    return {
        passable_map[neighbor] for neighbor in cardinal_neighbors(coord) if neighbor in passable_map
    }


def _building_roi_score(state: GameState, action: Action, context: HeuristicContext) -> int:
    if action.city_id is None or action.building_type is None:
        return 0
    city = state.cities[action.city_id]
    forest, mountain, river, plain, occupied = resource_ring_counts_for_context(
        context,
        city.coord,
    )
    ring_bonus = resource_ring_bonus_for_context(context, city.coord)
    resource_type = BUILDING_RESOURCE_TYPE[action.building_type]
    match_score = 0
    if resource_type is ResourceType.FOOD:
        match_score = (plain * 42) + (river * 34)
    elif resource_type is ResourceType.WOOD:
        match_score = forest * 52
    elif resource_type is ResourceType.ORE:
        match_score = mountain * 56
    elif resource_type is ResourceType.SCIENCE:
        match_score = river * 48
    crowd_penalty = occupied * 18
    same_building_penalty = city.buildings.for_type(action.building_type) * 35
    return (ring_bonus // 3) + match_score - crowd_penalty - same_building_penalty


def _is_high_roi_building(state: GameState, action: Action, context: HeuristicContext) -> bool:
    return _building_roi_score(state, action, context) >= 150


def _is_rescue_action(
    state: GameState,
    action: Action,
    context: HeuristicContext,
    profile: SearchPositionProfile,
) -> bool:
    if action.action_type is ActionType.BUILD_CITY and action.coord is not None:
        return (
            _city_can_rescue_food_pressure(state, action.coord, context)
            and _rescue_action_pressure_delta(state, action) < 0
        )
    if action.action_type is ActionType.BUILD_ROAD and action.coord is not None:
        road_profile = _road_candidate_profile(state, action.coord, context, profile)
        return road_profile.starvation_bridge or (
            profile.starving_network_count > 0 and road_profile.effective_connection
        )
    if action.action_type is ActionType.BUILD_BUILDING:
        if action.city_id is None or action.building_type is not BuildingType.FARM:
            return False
        return _rescue_action_pressure_delta(state, action) < 0
    if action.action_type is ActionType.RESEARCH_TECH:
        if action.city_id is None or action.tech_type is not TechType.AGRICULTURE:
            return False
        return _rescue_action_pressure_delta(state, action) < 0
    return False


def _rescue_action_pressure_delta(state: GameState, action: Action) -> int:
    before_pressure = _max_food_pressure(state)
    try:
        simulated = simulate_action(state, action)
    except ValueError:
        return 0
    return _max_food_pressure(simulated) - before_pressure


def _city_quality_delta(
    state: GameState,
    root_state: GameState | None,
    root_context: HeuristicContext | None,
) -> int:
    if root_state is None or root_context is None:
        return 0
    added_city_coords = {
        city.coord for city_id, city in state.cities.items() if city_id not in root_state.cities
    }
    quality = 0
    for coord in added_city_coords:
        if coord not in root_state.board:
            continue
        budget = site_budget(root_state, coord, root_context)
        ring_bonus = resource_ring_bonus_for_context(root_context, coord)
        site_score = city_site_score_for_context(root_context, coord)
        quality += (ring_bonus * 2) + site_score + (budget.food_balance * 220)
        if budget.food_balance < 0:
            quality -= abs(budget.food_balance) * 650
    return quality


def _road_candidate_profile(
    state: GameState,
    coord: Coord,
    context: HeuristicContext,
    profile: SearchPositionProfile,
) -> RoadCandidateProfile:
    adjacent_network_ids = _adjacent_network_ids(coord, context)
    merge_networks = len(adjacent_network_ids) >= 2
    before_connected = sum(
        len(state.networks[network_id].city_ids)
        for network_id in adjacent_network_ids
        if len(state.networks[network_id].city_ids) >= 2
    )
    merged_city_count = sum(
        len(state.networks[network_id].city_ids) for network_id in adjacent_network_ids
    )
    connected_city_delta = max(0, merged_city_count - before_connected) if merge_networks else 0
    network_delta = -(len(adjacent_network_ids) - 1) if merge_networks else 0
    pressures = [
        city_network_pressure(state.networks[network_id]) for network_id in adjacent_network_ids
    ]
    starvation_bridge = (
        merge_networks
        and any(
            state.networks[network_id].resources.food <= 0
            or city_network_pressure(state.networks[network_id]) >= FOOD_CONSUMPTION_PER_CITY
            for network_id in adjacent_network_ids
        )
        and any(
            state.networks[network_id].resources.food
            >= len(state.networks[network_id].city_ids) * FOOD_CONSUMPTION_PER_CITY * 3
            or city_network_pressure(state.networks[network_id]) < 0
            for network_id in adjacent_network_ids
        )
    )
    path_progress_score = _road_path_progress_score(state, coord, context, adjacent_network_ids)
    resource_frontier = _road_resource_frontier(state, coord)
    after_full_connectivity = (
        profile.city_count >= 2 and profile.connected_city_count >= profile.city_count
    )
    effective_connection = merge_networks or connected_city_delta > 0
    resource_frontier_is_valid = (
        resource_frontier >= 4 and profile.road_overbuild == 0 and not after_full_connectivity
    )
    redundant = (
        not effective_connection
        and not starvation_bridge
        and path_progress_score <= 0
        and not resource_frontier_is_valid
    )
    return RoadCandidateProfile(
        merge_networks=merge_networks,
        connected_city_delta=connected_city_delta,
        network_delta=network_delta,
        starvation_bridge=starvation_bridge,
        path_progress_score=path_progress_score + max(0, max(pressures, default=0) // 8),
        resource_frontier=resource_frontier,
        redundant=redundant,
        after_full_connectivity=after_full_connectivity,
    )


def _road_path_progress_score(
    state: GameState,
    coord: Coord,
    context: HeuristicContext,
    adjacent_network_ids: set[int],
) -> int:
    if not adjacent_network_ids or len(state.cities) < 2:
        return 0
    passable_map = context_passable_network_map(context)
    max_useful_distance = max(5, state.config.map_size // 3 + 2)
    best_progress = 0
    for network_id in adjacent_network_ids:
        network_coords = [
            passable_coord
            for passable_coord, passable_network_id in passable_map.items()
            if passable_network_id == network_id
        ]
        if not network_coords:
            continue
        for city in state.cities.values():
            if city.network_id == network_id:
                continue
            road_distance = _manhattan(coord, city.coord)
            if road_distance > max_useful_distance:
                continue
            current_distance = min(_manhattan(item, city.coord) for item in network_coords)
            if road_distance < current_distance:
                best_progress = max(
                    best_progress,
                    (current_distance - road_distance) + max(0, 8 - road_distance),
                )
    return best_progress


def _road_resource_frontier(state: GameState, coord: Coord) -> int:
    return sum(
        1
        for neighbor in moore_neighbors(coord)
        if (tile := state.board.get(neighbor)) is not None
        and tile.occupant is OccupantType.NONE
        and tile.base_terrain in {TerrainType.FOREST, TerrainType.MOUNTAIN}
    )


def _road_candidate_reason(profile: RoadCandidateProfile) -> str:
    if profile.starvation_bridge:
        return "road_starvation_bridge"
    if profile.effective_connection:
        return "road_effective_connection"
    if profile.path_progress_score > 0:
        return "road_path_progress"
    if profile.resource_frontier >= 4:
        return "road_resource_frontier"
    return "road_redundant"


def _manhattan(first: Coord, second: Coord) -> int:
    return abs(first[0] - second[0]) + abs(first[1] - second[1])


def _expansion_deficit_penalty(
    state: GameState,
    profile: SearchPositionProfile | None = None,
) -> int:
    profile = profile or build_search_position_profile(state)
    if profile.turns_remaining <= 6 or profile.safe_expansion_deficit <= 0:
        return 0
    weight = 1_500 if profile.is_healthy_steady else 2_400
    return min(36_000, profile.safe_expansion_deficit * weight)


def _early_fill_penalty(
    state: GameState,
    profile: SearchPositionProfile | None = None,
) -> int:
    profile = profile or build_search_position_profile(state)
    if profile.turns_remaining <= 10 or profile.safe_expansion_deficit <= 0:
        return 0
    fill_count = profile.fill_count
    allowed_fill = max(1, profile.city_count // 3)
    weight = 2_200 if profile.is_healthy_steady else 3_800
    return max(0, fill_count - allowed_fill) * weight


def _road_overbuild_penalty(
    state: GameState,
    profile: SearchPositionProfile | None = None,
) -> int:
    city_count_value = len(state.cities)
    if city_count_value <= 0:
        return len(state.roads) * 4_000
    profile = profile or build_search_position_profile(state)
    weight = 2_500 if profile.is_healthy_steady else 4_000
    return profile.road_overbuild * weight


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
