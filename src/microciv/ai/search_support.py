"""Reusable candidate and leaf-evaluation helpers for search policies."""

from __future__ import annotations

from dataclasses import dataclass

from microciv.ai.heuristics import (
    HeuristicContext,
    build_heuristic_context,
    building_action_score,
    city_expansion_score_for_context,
    partition_actions,
    research_action_score,
    road_site_score_for_context,
)
from microciv.ai.policy import get_legal_actions
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


@dataclass(slots=True, frozen=True)
class SearchLeafEvaluation:
    value: int
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


def generate_search_candidates(
    state: GameState,
    config: SearchCandidateConfig,
) -> SearchCandidateSet:
    """Return a deterministic, heuristic-ranked candidate set for search expansion."""
    if config.candidate_limit < 1:
        raise ValueError("candidate_limit must be at least 1")

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
        )

    context = build_heuristic_context(state)
    scored_by_type: dict[ActionType, list[SearchCandidate]] = {}
    for action_type in ActionType:
        scored = [
            _score_candidate(state, action, context) for action in groups.get(action_type, [])
        ]
        scored_by_type[action_type] = sorted(scored, key=_candidate_sort_key)

    if config.candidate_limit == 1:
        non_skip_candidates = [
            candidate
            for action_type in _NON_SKIP_TYPES
            for candidate in scored_by_type.get(action_type, [])
        ]
        pool = non_skip_candidates or scored_by_type.get(ActionType.SKIP, [])
        return SearchCandidateSet(
            candidates=pool[:1],
            legal_action_count=len(legal_actions),
            legal_counts_by_type=legal_counts_by_type,
        )

    skip_candidates = scored_by_type.get(ActionType.SKIP, []) if config.include_skip else []
    reserve_skip = bool(skip_candidates)
    non_skip_limit = config.candidate_limit - 1 if reserve_skip else config.candidate_limit

    selected: dict[Action, SearchCandidate] = {}
    representative_pool = [
        scored_by_type[action_type][0]
        for action_type in _NON_SKIP_TYPES
        if scored_by_type.get(action_type)
    ]
    for candidate in sorted(representative_pool, key=_candidate_sort_key)[:non_skip_limit]:
        selected[candidate.action] = candidate

    remaining_slots = non_skip_limit - len(selected)
    if remaining_slots > 0:
        remaining_pool = [
            candidate
            for action_type in _NON_SKIP_TYPES
            for candidate in scored_by_type.get(action_type, [])
            if candidate.action not in selected
        ]
        for candidate in sorted(remaining_pool, key=_candidate_sort_key)[:remaining_slots]:
            selected[candidate.action] = candidate

    if reserve_skip:
        selected[skip_candidates[0].action] = skip_candidates[0]

    return SearchCandidateSet(
        candidates=sorted(selected.values(), key=_candidate_sort_key)[: config.candidate_limit],
        legal_action_count=len(legal_actions),
        legal_counts_by_type=legal_counts_by_type,
    )


def evaluate_search_leaf(state: GameState) -> SearchLeafEvaluation:
    """Return a stable value estimate for a terminal node in a shallow search tree."""
    breakdown = score_breakdown(state)
    resources = total_resources(state)
    connected = connected_city_count(state)
    isolated = isolated_city_count(state)
    starving = starving_network_count(state)
    network_count = len(state.networks)
    largest_network = largest_network_size(state)

    value = breakdown.total * 100
    value += connected * 90
    value += largest_network * 120
    value += building_count(state) * 60
    value += tech_count(state) * 150
    value += _bounded_resource_value(resources.food, positive_cap=80, negative_cap=80, weight=6)
    value += _bounded_resource_value(resources.wood, positive_cap=80, negative_cap=40, weight=3)
    value += _bounded_resource_value(resources.ore, positive_cap=60, negative_cap=40, weight=4)
    value += _bounded_resource_value(resources.science, positive_cap=60, negative_cap=20, weight=3)
    value -= isolated * 450
    value -= starving * 1200
    value -= max(0, network_count - 1) * 180

    return SearchLeafEvaluation(
        value=value,
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
    )


def _score_candidate(
    state: GameState,
    action: Action,
    context: HeuristicContext,
) -> SearchCandidate:
    if action.action_type is ActionType.BUILD_CITY and action.coord is not None:
        return SearchCandidate(
            action=action,
            action_type=action.action_type,
            rank_score=city_expansion_score_for_context(context, action.coord),
            reason="city_expansion",
        )
    if action.action_type is ActionType.BUILD_ROAD and action.coord is not None:
        return SearchCandidate(
            action=action,
            action_type=action.action_type,
            rank_score=road_site_score_for_context(context, action.coord),
            reason="road_structure",
        )
    if action.action_type is ActionType.BUILD_BUILDING:
        return SearchCandidate(
            action=action,
            action_type=action.action_type,
            rank_score=building_action_score(state, action),
            reason="building_yield",
        )
    if action.action_type is ActionType.RESEARCH_TECH:
        return SearchCandidate(
            action=action,
            action_type=action.action_type,
            rank_score=research_action_score(state, action),
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
