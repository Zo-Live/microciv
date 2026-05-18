"""Rolling-horizon beam-search policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from microciv.ai.heuristics import (
    HeuristicContext,
    build_heuristic_context,
    city_network_pressure,
    city_site_score_for_context,
    context_is_river_adjacent_site,
    resource_ring_bonus_for_context,
    resource_ring_counts_for_context,
    site_budget,
)
from microciv.ai.policy import Policy, simulate_action
from microciv.ai.search_support import (
    SEARCH_MODE_CONNECT,
    SEARCH_MODE_EXPAND,
    SEARCH_MODE_RESCUE,
    SearchCandidateConfig,
    SearchCandidateSet,
    SearchLeafEvaluation,
    SearchPositionProfile,
    build_search_position_profile,
    evaluate_search_leaf,
    generate_search_candidates,
)
from microciv.constants import (
    DEFAULT_SEARCH_BEAM_WIDTH,
    DEFAULT_SEARCH_CANDIDATE_LIMIT,
    DEFAULT_SEARCH_DEPTH,
    DEFAULT_SEARCH_MAX_DEPTH,
    FOOD_CONSUMPTION_PER_CITY,
)
from microciv.game.actions import Action
from microciv.game.enums import ActionType, BuildingType, TechType
from microciv.game.models import GameState
from microciv.utils.grid import Coord

SEARCH_DEPTH_REASON_FIXED = "fixed"
SEARCH_DEPTH_REASON_FOOD_RESCUE = "food_rescue"
SEARCH_DEPTH_REASON_NETWORK_CONNECT = "network_connect"
SEARCH_DEPTH_REASON_GROWTH_STALL = "growth_stall"
SEARCH_DEPTH_REASON_FOOD_WATCH = "food_watch"
SEARCH_DEPTH_REASON_ENDGAME_PUSH = "endgame_push"
SEARCH_DEPTH_REASON_STEADY = "steady"
SEARCH_PLANNING_MODE_BEAM = "beam_search"
SEARCH_PLANNING_MODE_GREEDY_ANCHOR = "greedy_anchor"
SEARCH_PLANNING_REASON_RISK_SEARCH = "risk_search"
SEARCH_PLANNING_REASON_HEALTHY_GREEDY_CITY = "healthy_greedy_city"
SEARCH_PLANNING_REASON_HEALTHY_SHALLOW = "healthy_shallow"

_SEARCH_PRESSURE_COMPONENT_KEYS: tuple[str, ...] = (
    "isolated_penalty",
    "starving_penalty",
    "starving_turn_penalty",
    "food_pressure_penalty",
    "fragmentation_penalty",
    "expansion_deficit_penalty",
    "early_fill_penalty",
    "road_overbuild_penalty",
    "starving_delta_penalty",
    "food_pressure_delta_penalty",
    "isolated_delta_penalty",
    "network_delta_penalty",
    "road_delta_penalty",
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
_MISSING_SORT_VALUE = 10**9


@dataclass(slots=True, frozen=True)
class SearchDepthContext:
    """Inputs for deciding the effective search horizon."""

    state: GameState
    base_depth: int
    max_depth: int
    beam_width: int
    candidate_limit: int


@dataclass(slots=True, frozen=True)
class SearchDepthDecision:
    """Effective depth and a short diagnostic reason."""

    depth: int
    reason: str = SEARCH_DEPTH_REASON_FIXED


class SearchDepthStrategy(Protocol):
    """Strategy hook for future dynamic horizon selection."""

    def choose_depth(self, context: SearchDepthContext) -> SearchDepthDecision:
        """Return the effective depth for the current turn."""


class FixedSearchDepthStrategy:
    """Default depth strategy: always use the configured base depth."""

    def choose_depth(self, context: SearchDepthContext) -> SearchDepthDecision:
        return SearchDepthDecision(depth=context.base_depth, reason=SEARCH_DEPTH_REASON_FIXED)


class DynamicSearchDepthStrategy:
    """Choose a deeper horizon for tactical food, network, and endgame positions."""

    def choose_depth(self, context: SearchDepthContext) -> SearchDepthDecision:
        state = context.state
        if context.max_depth <= context.base_depth:
            return SearchDepthDecision(depth=context.base_depth, reason=SEARCH_DEPTH_REASON_FIXED)

        if _has_food_rescue_need(state):
            return SearchDepthDecision(
                depth=context.max_depth,
                reason=SEARCH_DEPTH_REASON_FOOD_RESCUE,
            )
        profile = build_search_position_profile(state)
        if not profile.is_healthy_steady and _has_network_connect_need(state):
            return SearchDepthDecision(
                depth=min(context.max_depth, 5),
                reason=SEARCH_DEPTH_REASON_NETWORK_CONNECT,
            )
        if _has_growth_stall(state):
            return SearchDepthDecision(
                depth=context.max_depth,
                reason=SEARCH_DEPTH_REASON_GROWTH_STALL,
            )
        if _has_food_watch_warning(state, profile):
            return SearchDepthDecision(
                depth=min(context.max_depth, context.base_depth + 2),
                reason=SEARCH_DEPTH_REASON_FOOD_WATCH,
            )
        if profile.is_healthy_steady:
            return SearchDepthDecision(depth=context.base_depth, reason=SEARCH_DEPTH_REASON_STEADY)
        if _max_food_pressure(state) >= FOOD_CONSUMPTION_PER_CITY:
            return SearchDepthDecision(
                depth=min(context.max_depth, context.base_depth + 2),
                reason=SEARCH_DEPTH_REASON_FOOD_WATCH,
            )
        if _turns_remaining(state) <= _endgame_push_threshold(state):
            return SearchDepthDecision(
                depth=min(context.max_depth, 5),
                reason=SEARCH_DEPTH_REASON_ENDGAME_PUSH,
            )
        return SearchDepthDecision(depth=context.base_depth, reason=SEARCH_DEPTH_REASON_STEADY)


@dataclass(slots=True, frozen=True)
class PlannedSearchDecision:
    action: Action
    context: dict[str, object]
    root_candidate_diagnostics: tuple[RootCandidateDiagnostic, ...] = ()


@dataclass(slots=True, frozen=True)
class SearchNode:
    state: GameState
    sequence: tuple[Action, ...]
    value: int
    sequence_adjustment: int
    leaf_evaluation: SearchLeafEvaluation


@dataclass(slots=True, frozen=True)
class RootCandidateDiagnostic:
    action: Action
    value: int


@dataclass(slots=True, frozen=True)
class GreedyAnchorPlan:
    action: Action
    direct: bool
    force_candidate: bool
    reason: str


@dataclass(slots=True)
class SearchTelemetry:
    nodes_expanded: int = 0
    candidates_considered: int = 0
    leaf_count: int = 0
    root_legal_action_count: int = 0
    root_profile: SearchPositionProfile | None = None
    root_legal_counts_by_type: dict[ActionType, int] | None = None
    root_candidate_counts_by_type: dict[ActionType, int] | None = None
    root_safe_city_candidate_count: int = 0
    root_effective_connection_road_candidate_count: int = 0
    root_rescue_candidate_count: int = 0
    root_effective_city_candidate_count: int = 0
    root_redundant_road_candidate_count: int = 0
    root_high_roi_building_candidate_count: int = 0
    root_gated_candidate_count: int = 0
    root_candidate_diagnostics: list[RootCandidateDiagnostic] = field(default_factory=list)


class SearchPolicy(Policy):
    """Deterministic rolling-horizon beam-search policy."""

    def __init__(
        self,
        *,
        search_depth: int = DEFAULT_SEARCH_DEPTH,
        search_beam_width: int = DEFAULT_SEARCH_BEAM_WIDTH,
        search_candidate_limit: int = DEFAULT_SEARCH_CANDIDATE_LIMIT,
        search_depth_strategy: SearchDepthStrategy | None = None,
        search_max_depth: int | None = DEFAULT_SEARCH_MAX_DEPTH,
    ) -> None:
        self.search_depth = _require_positive(search_depth, "search_depth")
        self.search_beam_width = _require_positive(search_beam_width, "search_beam_width")
        self.search_candidate_limit = _require_positive(
            search_candidate_limit, "search_candidate_limit"
        )
        self.search_max_depth = _require_positive(
            self.search_depth if search_max_depth is None else search_max_depth,
            "search_max_depth",
        )
        if self.search_max_depth < self.search_depth:
            raise ValueError("search_max_depth must be greater than or equal to search_depth")
        self.search_depth_strategy = search_depth_strategy or (
            DynamicSearchDepthStrategy()
            if self.search_max_depth > self.search_depth
            else FixedSearchDepthStrategy()
        )

        self._cache_key: tuple[object, ...] | None = None
        self._cached_decision: PlannedSearchDecision | None = None

    def select_action(self, state: GameState) -> Action:
        return self._plan_action(state).action

    def explain_decision(self, state: GameState) -> dict[str, object]:
        decision = self._plan_action(state)
        context = dict(decision.context)
        context.update(_post_decision_diagnostics(state, decision))
        return context

    def _plan_action(self, state: GameState) -> PlannedSearchDecision:
        cache_key = self._build_cache_key(state)
        if self._cache_key == cache_key and self._cached_decision is not None:
            return self._cached_decision

        depth_decision = self._choose_depth(state)
        root_profile = build_search_position_profile(state)
        greedy_anchor = _greedy_anchor_plan(
            state,
            root_profile,
            allow_direct=depth_decision.reason
            in {SEARCH_DEPTH_REASON_STEADY, SEARCH_DEPTH_REASON_FIXED},
        )
        forced_actions = (greedy_anchor.action,) if greedy_anchor.force_candidate else ()
        candidate_config = SearchCandidateConfig(
            candidate_limit=self.search_candidate_limit,
            forced_actions=forced_actions,
        )
        telemetry = SearchTelemetry()
        planning_mode = SEARCH_PLANNING_MODE_BEAM
        planning_reason = SEARCH_PLANNING_REASON_RISK_SEARCH
        effective_depth = depth_decision.depth
        actual_depth = depth_decision.depth
        best_node: SearchNode | None = None
        if greedy_anchor.direct:
            best_node = self._run_anchor_plan(
                state=state,
                action=greedy_anchor.action,
                candidate_config=candidate_config,
                telemetry=telemetry,
            )
            if best_node is not None:
                planning_mode = SEARCH_PLANNING_MODE_GREEDY_ANCHOR
                planning_reason = greedy_anchor.reason
                actual_depth = 1

        if best_node is None:
            beam_depth = depth_decision.depth
            if _should_use_healthy_shallow_search(root_profile, depth_decision):
                beam_depth = 1
                planning_reason = SEARCH_PLANNING_REASON_HEALTHY_SHALLOW
            actual_depth = beam_depth
            best_node = self._run_beam_search(
                state=state,
                depth=beam_depth,
                candidate_config=candidate_config,
                telemetry=telemetry,
            )

        if best_node is None or not best_node.sequence:
            action = Action.skip()
            best_evaluation = evaluate_search_leaf(state, root_state=state)
            best_value = best_evaluation.value
            best_sequence_adjustment = 0
            best_sequence: list[dict[str, object]] = []
        else:
            action = best_node.sequence[0]
            best_evaluation = best_node.leaf_evaluation
            best_value = best_node.value
            best_sequence_adjustment = best_node.sequence_adjustment
            best_sequence = [_action_to_dict(item) for item in best_node.sequence]
        (
            dominant_pressure,
            dominant_pressure_value,
            risk_pressure_total,
            is_risk_dominated,
            is_sequence_adjusted,
        ) = _search_pressure_diagnostics(
            best_evaluation.value_components,
            best_sequence_adjustment,
        )
        root_profile = telemetry.root_profile or build_search_position_profile(state)
        root_legal_counts = telemetry.root_legal_counts_by_type or {
            action_type: 0 for action_type in ActionType
        }
        root_candidate_counts = telemetry.root_candidate_counts_by_type or {
            action_type: 0 for action_type in ActionType
        }
        root_candidate_diagnostics = _root_candidate_diagnostics(
            telemetry.root_candidate_diagnostics,
            chosen_action=action,
        )
        action_delta_diagnostics = _action_delta_diagnostics(state, action)
        legal_action_count = telemetry.root_legal_action_count
        root_candidate_total = sum(root_candidate_counts.values())
        candidate_cut_ratio = (
            (legal_action_count - root_candidate_total) / legal_action_count
            if legal_action_count
            else 0.0
        )

        decision = PlannedSearchDecision(
            action=action,
            context={
                "search_mode": root_profile.mode,
                "search_depth": effective_depth,
                "search_actual_depth": actual_depth,
                "search_base_depth": self.search_depth,
                "search_max_depth": self.search_max_depth,
                "search_depth_reason": depth_decision.reason,
                "search_deep_search_enabled": planning_mode == SEARCH_PLANNING_MODE_BEAM
                and actual_depth > 1,
                "search_planning_mode": planning_mode,
                "search_planning_reason": planning_reason,
                "search_beam_width": self.search_beam_width,
                "search_candidate_limit": self.search_candidate_limit,
                "search_root_legal_build_city_count": root_legal_counts[ActionType.BUILD_CITY],
                "search_root_legal_build_road_count": root_legal_counts[ActionType.BUILD_ROAD],
                "search_root_legal_build_building_count": root_legal_counts[
                    ActionType.BUILD_BUILDING
                ],
                "search_root_legal_research_tech_count": root_legal_counts[
                    ActionType.RESEARCH_TECH
                ],
                "search_root_legal_skip_count": root_legal_counts[ActionType.SKIP],
                "search_root_candidate_build_city_count": root_candidate_counts[
                    ActionType.BUILD_CITY
                ],
                "search_root_candidate_build_road_count": root_candidate_counts[
                    ActionType.BUILD_ROAD
                ],
                "search_root_candidate_build_building_count": root_candidate_counts[
                    ActionType.BUILD_BUILDING
                ],
                "search_root_candidate_research_tech_count": root_candidate_counts[
                    ActionType.RESEARCH_TECH
                ],
                "search_root_candidate_skip_count": root_candidate_counts[ActionType.SKIP],
                "search_root_candidate_cut_ratio": candidate_cut_ratio,
                "search_root_safe_city_candidate_count": (telemetry.root_safe_city_candidate_count),
                "search_root_effective_connection_road_candidate_count": (
                    telemetry.root_effective_connection_road_candidate_count
                ),
                "search_root_rescue_candidate_count": telemetry.root_rescue_candidate_count,
                "search_root_effective_city_candidate_count": (
                    telemetry.root_effective_city_candidate_count
                ),
                "search_root_redundant_road_candidate_count": (
                    telemetry.root_redundant_road_candidate_count
                ),
                "search_root_high_roi_building_candidate_count": (
                    telemetry.root_high_roi_building_candidate_count
                ),
                "search_root_gated_candidate_count": telemetry.root_gated_candidate_count,
                "search_profile_city_count": root_profile.city_count,
                "search_profile_target_city_count": root_profile.target_city_count,
                "search_profile_expansion_deficit": root_profile.expansion_deficit,
                "search_profile_safe_expansion_deficit": root_profile.safe_expansion_deficit,
                "search_profile_network_count": root_profile.network_count,
                "search_profile_connected_city_count": root_profile.connected_city_count,
                "search_profile_isolated_city_count": root_profile.isolated_city_count,
                "search_profile_starving_network_count": root_profile.starving_network_count,
                "search_profile_food_pressure": root_profile.food_pressure,
                "search_profile_road_overbuild": root_profile.road_overbuild,
                "search_profile_fill_count": root_profile.fill_count,
                "search_nodes_expanded": telemetry.nodes_expanded,
                "search_candidates_considered": telemetry.candidates_considered,
                "search_leaf_count": telemetry.leaf_count,
                "search_best_value": best_value,
                "search_value_components": best_evaluation.value_components,
                "search_sequence_adjustment": best_sequence_adjustment,
                "search_dominant_pressure": dominant_pressure,
                "search_dominant_pressure_value": dominant_pressure_value,
                "search_risk_pressure_total": risk_pressure_total,
                "search_is_risk_dominated": is_risk_dominated,
                "search_is_sequence_adjusted": is_sequence_adjusted,
                "search_best_score_total": best_evaluation.score_total,
                "search_best_connected_city_count": best_evaluation.connected_city_count,
                "search_best_isolated_city_count": best_evaluation.isolated_city_count,
                "search_best_starving_network_count": best_evaluation.starving_network_count,
                "search_best_network_count": best_evaluation.network_count,
                "search_best_largest_network_size": best_evaluation.largest_network_size,
                "search_best_total_food": best_evaluation.total_food,
                "search_best_total_wood": best_evaluation.total_wood,
                "search_best_total_ore": best_evaluation.total_ore,
                "search_best_total_science": best_evaluation.total_science,
                "search_best_food_pressure": best_evaluation.food_pressure,
                "search_best_starving_turns": best_evaluation.starving_turns,
                "search_best_sequence": best_sequence,
                **root_candidate_diagnostics,
                **action_delta_diagnostics,
            },
            root_candidate_diagnostics=tuple(telemetry.root_candidate_diagnostics),
        )
        self._cache_key = cache_key
        self._cached_decision = decision
        return decision

    def _run_anchor_plan(
        self,
        *,
        state: GameState,
        action: Action,
        candidate_config: SearchCandidateConfig,
        telemetry: SearchTelemetry,
    ) -> SearchNode | None:
        root_evaluation = evaluate_search_leaf(state, root_state=state)
        candidate_set = generate_search_candidates(state, candidate_config)
        self._record_root_candidate_set(candidate_set, telemetry)
        telemetry.nodes_expanded += 1
        telemetry.candidates_considered += len(candidate_set.candidates)
        selected_node: SearchNode | None = None
        for candidate in candidate_set.candidates:
            simulated_state = simulate_action(state, candidate.action)
            leaf_evaluation = evaluate_search_leaf(simulated_state, root_state=state)
            telemetry.leaf_count += 1
            sequence = (candidate.action,)
            sequence_adjustment = _sequence_adjustment(state, simulated_state, sequence)
            child = SearchNode(
                state=simulated_state,
                sequence=sequence,
                value=leaf_evaluation.value + sequence_adjustment,
                sequence_adjustment=sequence_adjustment,
                leaf_evaluation=leaf_evaluation,
            )
            telemetry.root_candidate_diagnostics.append(
                RootCandidateDiagnostic(
                    action=candidate.action,
                    value=child.value,
                )
            )
            if candidate.action == action:
                selected_node = child
        if selected_node is not None:
            return selected_node
        return SearchNode(
            state=state,
            sequence=(),
            value=root_evaluation.value,
            sequence_adjustment=0,
            leaf_evaluation=root_evaluation,
        )

    def _choose_depth(self, state: GameState) -> SearchDepthDecision:
        context = SearchDepthContext(
            state=state,
            base_depth=self.search_depth,
            max_depth=self.search_max_depth,
            beam_width=self.search_beam_width,
            candidate_limit=self.search_candidate_limit,
        )
        decision = self.search_depth_strategy.choose_depth(context)
        if decision.depth < 1:
            raise ValueError("SearchDepthStrategy returned depth less than 1")
        if decision.depth > self.search_max_depth:
            raise ValueError("SearchDepthStrategy returned depth greater than search_max_depth")
        reason = decision.reason or "custom"
        return SearchDepthDecision(depth=decision.depth, reason=reason)

    def _run_beam_search(
        self,
        *,
        state: GameState,
        depth: int,
        candidate_config: SearchCandidateConfig,
        telemetry: SearchTelemetry,
    ) -> SearchNode | None:
        root_evaluation = evaluate_search_leaf(state, root_state=state)
        beam = [
            SearchNode(
                state=state,
                sequence=(),
                value=root_evaluation.value,
                sequence_adjustment=0,
                leaf_evaluation=root_evaluation,
            )
        ]
        best_node: SearchNode | None = None

        for _level in range(depth):
            next_nodes: list[SearchNode] = []
            for node in beam:
                if node.state.is_game_over:
                    best_node = _better_node(best_node, node)
                    continue

                candidate_set = generate_search_candidates(node.state, candidate_config)
                if not node.sequence and telemetry.root_profile is None:
                    self._record_root_candidate_set(candidate_set, telemetry)
                telemetry.nodes_expanded += 1
                telemetry.candidates_considered += len(candidate_set.candidates)

                if not candidate_set.candidates:
                    best_node = _better_node(best_node, node)
                    continue

                for candidate in candidate_set.candidates:
                    simulated_state = simulate_action(node.state, candidate.action)
                    leaf_evaluation = evaluate_search_leaf(simulated_state, root_state=state)
                    telemetry.leaf_count += 1
                    sequence = (*node.sequence, candidate.action)
                    sequence_adjustment = _sequence_adjustment(state, simulated_state, sequence)
                    child = SearchNode(
                        state=simulated_state,
                        sequence=sequence,
                        value=leaf_evaluation.value + sequence_adjustment,
                        sequence_adjustment=sequence_adjustment,
                        leaf_evaluation=leaf_evaluation,
                    )
                    if not node.sequence:
                        telemetry.root_candidate_diagnostics.append(
                            RootCandidateDiagnostic(
                                action=candidate.action,
                                value=child.value,
                            )
                        )
                    next_nodes.append(child)
                    best_node = _better_node(best_node, child)

            if not next_nodes:
                break
            beam = sorted(next_nodes, key=_node_sort_key)[: self.search_beam_width]

        return best_node

    def _record_root_candidate_set(
        self,
        candidate_set: SearchCandidateSet,
        telemetry: SearchTelemetry,
    ) -> None:
        telemetry.root_profile = candidate_set.profile
        telemetry.root_legal_action_count = candidate_set.legal_action_count
        telemetry.root_legal_counts_by_type = candidate_set.legal_counts_by_type
        telemetry.root_candidate_counts_by_type = candidate_set.candidate_counts_by_type
        telemetry.root_safe_city_candidate_count = candidate_set.safe_city_candidate_count
        telemetry.root_effective_connection_road_candidate_count = (
            candidate_set.effective_connection_road_candidate_count
        )
        telemetry.root_rescue_candidate_count = candidate_set.rescue_candidate_count
        telemetry.root_effective_city_candidate_count = candidate_set.effective_city_candidate_count
        telemetry.root_redundant_road_candidate_count = candidate_set.redundant_road_candidate_count
        telemetry.root_high_roi_building_candidate_count = (
            candidate_set.high_roi_building_candidate_count
        )
        telemetry.root_gated_candidate_count = candidate_set.gated_candidate_count

    def _build_cache_key(self, state: GameState) -> tuple[object, ...]:
        network_signature = tuple(
            (
                network_id,
                tuple(sorted(network.city_ids)),
                network.resources.food,
                network.resources.wood,
                network.resources.ore,
                network.resources.science,
                tuple(sorted(tech.value for tech in network.unlocked_techs)),
                network.consecutive_starving_turns,
            )
            for network_id, network in sorted(state.networks.items())
        )
        return (
            id(state),
            state.turn,
            state.score,
            state.is_game_over,
            len(state.cities),
            len(state.roads),
            len(state.networks),
            len(state.stats.decision_contexts),
            state.next_city_id,
            state.next_road_id,
            state.next_network_id,
            network_signature,
            self.search_depth,
            self.search_max_depth,
            self.search_beam_width,
            self.search_candidate_limit,
        )


def _require_positive(value: int, field_name: str) -> int:
    if value < 1:
        raise ValueError(f"{field_name} must be at least 1")
    return value


def _greedy_anchor_plan(
    state: GameState,
    profile: SearchPositionProfile,
    *,
    allow_direct: bool,
) -> GreedyAnchorPlan:
    from microciv.ai.greedy import GreedyPolicy

    greedy_action = GreedyPolicy().select_action(state)
    if greedy_action.action_type is not ActionType.BUILD_CITY or greedy_action.coord is None:
        return GreedyAnchorPlan(
            action=greedy_action,
            direct=False,
            force_candidate=False,
            reason="greedy_non_city",
        )
    if not allow_direct or not _is_healthy_expansion_anchor_state(profile):
        return GreedyAnchorPlan(
            action=greedy_action,
            direct=False,
            force_candidate=True,
            reason="risk_search_with_greedy_city",
        )

    context = build_heuristic_context(state)
    quality = _city_anchor_quality(state, greedy_action.coord, context)
    if quality["food_balance"] < 0:
        return GreedyAnchorPlan(
            action=greedy_action,
            direct=False,
            force_candidate=True,
            reason="greedy_city_food_risk",
        )
    if quality["ring_bonus"] >= 180 or quality["site_score"] >= 260 or profile.city_count < 3:
        return GreedyAnchorPlan(
            action=greedy_action,
            direct=True,
            force_candidate=True,
            reason=SEARCH_PLANNING_REASON_HEALTHY_GREEDY_CITY,
        )
    return GreedyAnchorPlan(
        action=greedy_action,
        direct=False,
        force_candidate=True,
        reason="greedy_city_low_quality",
    )


def _is_healthy_expansion_anchor_state(profile: SearchPositionProfile) -> bool:
    return (
        profile.mode == SEARCH_MODE_EXPAND
        and profile.is_healthy_steady
        and profile.safe_expansion_deficit > 0
        and profile.turns_remaining > 10
        and profile.starving_network_count == 0
        and profile.food_pressure <= FOOD_CONSUMPTION_PER_CITY
    )


def _should_use_healthy_shallow_search(
    profile: SearchPositionProfile,
    depth_decision: SearchDepthDecision,
) -> bool:
    return (
        depth_decision.reason == SEARCH_DEPTH_REASON_STEADY
        and _is_healthy_expansion_anchor_state(profile)
        and depth_decision.depth > 1
    )


def _city_anchor_quality(
    state: GameState,
    coord: Coord,
    context: HeuristicContext,
) -> dict[str, int]:
    budget = site_budget(state, coord, context)
    return {
        "site_score": city_site_score_for_context(context, coord),
        "ring_bonus": resource_ring_bonus_for_context(context, coord),
        "food_balance": budget.food_balance,
    }


def _root_candidate_diagnostics(
    candidates: list[RootCandidateDiagnostic],
    *,
    chosen_action: Action,
) -> dict[str, object]:
    result: dict[str, object] = {
        "search_root_chosen_action_type": chosen_action.action_type.value,
    }
    for action_type in ActionType:
        values = [
            candidate.value
            for candidate in candidates
            if candidate.action.action_type is action_type
        ]
        result[f"search_root_best_{action_type.value}_value"] = max(values) if values else None

    if not candidates:
        return result

    ranked = sorted(
        candidates,
        key=lambda candidate: (-candidate.value, _action_sort_key(candidate.action)),
    )
    best_candidate = ranked[0]
    chosen_rank: int | None = None
    chosen_value: int | None = None
    for index, candidate in enumerate(ranked, start=1):
        if candidate.action == chosen_action:
            chosen_rank = index
            chosen_value = candidate.value
            break

    result.update(
        {
            "search_root_chosen_rank": chosen_rank,
            "search_root_chosen_value": chosen_value,
            "search_root_best_value": best_candidate.value,
            "search_root_value_margin": (
                best_candidate.value - chosen_value if chosen_value is not None else None
            ),
            "search_root_best_action_type": best_candidate.action.action_type.value,
        }
    )
    return result


def _action_delta_diagnostics(state: GameState, action: Action) -> dict[str, object]:
    before = build_search_position_profile(state)
    before_risk = _network_food_risk_profile(state)
    after_state = simulate_action(state, action)
    after = build_search_position_profile(after_state)
    after_risk = _network_food_risk_profile(after_state)
    road_connected_city_delta = after.connected_city_count - before.connected_city_count
    road_merges_networks = (
        action.action_type is ActionType.BUILD_ROAD and after.network_count < before.network_count
    )
    road_after_full_connectivity = (
        action.action_type is ActionType.BUILD_ROAD
        and before.city_count >= 2
        and before.connected_city_count >= before.city_count
    )
    road_is_redundant = (
        action.action_type is ActionType.BUILD_ROAD
        and not road_merges_networks
        and road_connected_city_delta <= 0
    )
    return {
        "search_delta_starving_network_count": (
            after.starving_network_count - before.starving_network_count
        ),
        "search_delta_food_pressure": after.food_pressure - before.food_pressure,
        "search_delta_isolated_city_count": after.isolated_city_count - before.isolated_city_count,
        "search_delta_network_count": after.network_count - before.network_count,
        "search_delta_connected_city_count": (
            after.connected_city_count - before.connected_city_count
        ),
        "search_delta_road_overbuild": _road_overbuild_metric(after_state)
        - _road_overbuild_metric(state),
        "search_delta_worst_network_food_pressure": (
            after_risk["worst_pressure"] - before_risk["worst_pressure"]
        ),
        "search_delta_min_network_food": after_risk["min_food"] - before_risk["min_food"],
        "search_road_merges_networks": road_merges_networks,
        "search_road_connected_city_delta": (
            road_connected_city_delta if action.action_type is ActionType.BUILD_ROAD else 0
        ),
        "search_road_is_redundant": road_is_redundant,
        "search_road_after_full_connectivity": road_after_full_connectivity,
        **_network_food_risk_diagnostics(after_state),
    }


def _post_decision_diagnostics(
    state: GameState,
    decision: PlannedSearchDecision,
) -> dict[str, object]:
    from microciv.ai.greedy import GreedyPolicy

    greedy_action = GreedyPolicy().select_action(state)
    diagnostics = _greedy_anchor_diagnostics(
        root_candidates=decision.root_candidate_diagnostics,
        chosen_action=decision.action,
        greedy_action=greedy_action,
    )
    diagnostics.update(
        _city_anchor_diagnostics(
            state=state,
            chosen_action=decision.action,
            greedy_action=greedy_action,
        )
    )
    return diagnostics


def _greedy_anchor_diagnostics(
    *,
    root_candidates: tuple[RootCandidateDiagnostic, ...],
    chosen_action: Action,
    greedy_action: Action,
) -> dict[str, object]:
    result: dict[str, object] = {
        "search_greedy_action_type": greedy_action.action_type.value,
        "search_matches_greedy_action": chosen_action == greedy_action,
        "search_greedy_action_in_root_candidates": False,
    }
    if not root_candidates:
        return result

    ranked = sorted(
        root_candidates,
        key=lambda candidate: (-candidate.value, _action_sort_key(candidate.action)),
    )
    best_value = ranked[0].value
    chosen_value: int | None = None
    greedy_value: int | None = None
    greedy_rank: int | None = None
    for rank, candidate in enumerate(ranked, start=1):
        if candidate.action == chosen_action:
            chosen_value = candidate.value
        if candidate.action == greedy_action:
            greedy_value = candidate.value
            greedy_rank = rank

    result.update(
        {
            "search_greedy_action_in_root_candidates": greedy_value is not None,
            "search_greedy_action_root_rank": greedy_rank,
            "search_greedy_action_root_value": greedy_value,
            "search_greedy_action_root_value_margin": (
                best_value - greedy_value if greedy_value is not None else None
            ),
            "search_chosen_value_delta_vs_greedy_action": (
                chosen_value - greedy_value
                if chosen_value is not None and greedy_value is not None
                else None
            ),
        }
    )
    return result


def _city_anchor_diagnostics(
    *,
    state: GameState,
    chosen_action: Action,
    greedy_action: Action,
) -> dict[str, object]:
    context = build_heuristic_context(state)
    result: dict[str, object] = {}
    result.update(
        _city_action_diagnostics(
            state=state,
            context=context,
            action=chosen_action,
            prefix="search_chosen_city",
        )
    )
    result.update(
        _city_action_diagnostics(
            state=state,
            context=context,
            action=greedy_action,
            prefix="search_greedy_city",
        )
    )
    chosen_score = result.get("search_chosen_city_site_score")
    greedy_score = result.get("search_greedy_city_site_score")
    if isinstance(chosen_score, int) and isinstance(greedy_score, int):
        result["search_chosen_city_site_score_delta_vs_greedy"] = chosen_score - greedy_score
    return result


def _city_action_diagnostics(
    *,
    state: GameState,
    context: HeuristicContext,
    action: Action,
    prefix: str,
) -> dict[str, object]:
    if action.action_type is not ActionType.BUILD_CITY or action.coord is None:
        return {}
    coord = action.coord
    budget = site_budget(state, coord, context)
    forest, mountain, river, plain, occupied = resource_ring_counts_for_context(context, coord)
    return {
        f"{prefix}_site_score": city_site_score_for_context(context, coord),
        f"{prefix}_resource_ring_bonus": resource_ring_bonus_for_context(context, coord),
        f"{prefix}_food_balance": budget.food_balance,
        f"{prefix}_total_yield": budget.total_yield,
        f"{prefix}_river_access": context_is_river_adjacent_site(context, coord),
        f"{prefix}_forest_neighbors": forest,
        f"{prefix}_mountain_neighbors": mountain,
        f"{prefix}_river_neighbors": river,
        f"{prefix}_plain_neighbors": plain,
        f"{prefix}_occupied_neighbors": occupied,
        f"{prefix}_distance_to_network": _distance_to_existing_network(state, coord),
    }


def _distance_to_existing_network(state: GameState, coord: Coord) -> int | None:
    occupied_coords = [city.coord for city in state.cities.values()] + [
        road.coord for road in state.roads.values()
    ]
    if not occupied_coords:
        return None
    return min(abs(coord[0] - other[0]) + abs(coord[1] - other[1]) for other in occupied_coords)


def _network_food_risk_diagnostics(state: GameState) -> dict[str, object]:
    profile = _network_food_risk_profile(state)
    return {
        "search_min_network_food_after_action": profile["min_food"],
        "search_worst_network_food_pressure_after_action": profile["worst_pressure"],
        "search_food_surplus_network_count_after_action": profile["surplus_count"],
        "search_food_deficit_network_count_after_action": profile["deficit_count"],
    }


def _network_food_risk_profile(state: GameState) -> dict[str, int]:
    foods = [network.resources.food for network in state.networks.values()]
    pressures = [city_network_pressure(network) for network in state.networks.values()]
    return {
        "min_food": min(foods, default=0),
        "worst_pressure": max(pressures, default=0),
        "surplus_count": sum(1 for pressure in pressures if pressure <= 0),
        "deficit_count": sum(1 for pressure in pressures if pressure > 0),
    }


def _road_overbuild_metric(state: GameState) -> int:
    city_count_value = len(state.cities)
    if city_count_value <= 0:
        return len(state.roads)
    road_allowance = max(2, city_count_value // 2)
    return max(0, len(state.roads) - road_allowance)


def _sequence_adjustment(
    root_state: GameState,
    leaf_state: GameState,
    sequence: tuple[Action, ...],
) -> int:
    root_profile = build_search_position_profile(root_state)
    leaf_profile = build_search_position_profile(leaf_state)
    action_counts = {
        action_type: sum(1 for action in sequence if action.action_type is action_type)
        for action_type in ActionType
    }
    city_actions = action_counts[ActionType.BUILD_CITY]
    road_actions = action_counts[ActionType.BUILD_ROAD]
    fill_actions = (
        action_counts[ActionType.BUILD_BUILDING] + action_counts[ActionType.RESEARCH_TECH]
    )
    skip_actions = action_counts[ActionType.SKIP]
    connected_gain = max(0, leaf_profile.connected_city_count - root_profile.connected_city_count)
    network_reduction = max(0, root_profile.network_count - leaf_profile.network_count)
    starvation_reduction = max(
        0,
        root_profile.starving_network_count - leaf_profile.starving_network_count,
    )
    pressure_reduction = max(0, root_profile.food_pressure - leaf_profile.food_pressure)
    first_action = sequence[0] if sequence else None
    first_delta = _first_action_delta(root_state, first_action) if first_action is not None else {}
    first_food_delta = int(first_delta.get("food_pressure", 0))
    first_starving_delta = int(first_delta.get("starving_network_count", 0))
    first_network_delta = int(first_delta.get("network_count", 0))
    first_connected_delta = int(first_delta.get("connected_city_count", 0))
    first_road_overbuild_delta = int(first_delta.get("road_overbuild", 0))

    adjustment = 0
    if root_profile.turns_remaining > 3 and skip_actions:
        adjustment -= skip_actions * 5_500
        adjustment -= max(0, skip_actions - 1) * 2_500

    if root_profile.mode == SEARCH_MODE_EXPAND:
        adjustment += min(city_actions, root_profile.safe_expansion_deficit) * 14_000
        adjustment += connected_gain * 2_500
        if first_action is not None and first_action.action_type is not ActionType.BUILD_CITY:
            adjustment -= 18_000
        if root_profile.turns_remaining > 10 and root_profile.safe_expansion_deficit > 0:
            adjustment -= fill_actions * 4_500
            if connected_gain == 0 and network_reduction == 0:
                adjustment -= road_actions * 4_200
            adjustment -= skip_actions * 4_000
    elif root_profile.mode == SEARCH_MODE_CONNECT:
        adjustment += connected_gain * 5_200
        adjustment += network_reduction * 4_800
        if connected_gain > 0 or network_reduction > 0:
            adjustment += road_actions * 1_200
        else:
            adjustment -= road_actions * 4_400
        if (
            first_action is not None
            and root_profile.network_count > 1
            and first_connected_delta <= 0
            and first_network_delta >= 0
        ):
            adjustment -= 14_000
        adjustment -= skip_actions * 2_500
    elif root_profile.mode == SEARCH_MODE_RESCUE:
        adjustment += starvation_reduction * 9_000
        adjustment += pressure_reduction * 260
        if (
            first_action is not None
            and first_starving_delta >= 0
            and first_food_delta >= 0
            and root_profile.food_pressure >= FOOD_CONSUMPTION_PER_CITY
        ):
            adjustment -= 18_000
        if root_profile.food_pressure >= FOOD_CONSUMPTION_PER_CITY * 2:
            adjustment -= city_actions * 4_800
        adjustment -= skip_actions * 3_000
    elif root_profile.turns_remaining > 10 and root_profile.safe_expansion_deficit > 0:
        adjustment += min(city_actions, root_profile.safe_expansion_deficit) * 3_500
        adjustment -= skip_actions * 2_500

    if first_action is not None:
        if first_action.action_type is ActionType.BUILD_ROAD:
            if (
                first_road_overbuild_delta > 0
                and first_connected_delta <= 0
                and first_network_delta >= 0
            ):
                adjustment -= 45_000
            if (
                root_profile.connected_city_count >= root_profile.city_count
                and root_profile.city_count >= 2
                and first_connected_delta <= 0
                and first_network_delta >= 0
            ):
                adjustment -= 24_000
        if first_action.action_type is ActionType.BUILD_BUILDING and (
            root_profile.mode in {SEARCH_MODE_EXPAND, SEARCH_MODE_CONNECT}
        ):
            if first_food_delta >= 0:
                adjustment -= 9_000
        if root_profile.food_pressure >= FOOD_CONSUMPTION_PER_CITY and first_food_delta > 0:
            adjustment -= first_food_delta * 700

    return adjustment


def _search_pressure_diagnostics(
    value_components: dict[str, int],
    sequence_adjustment: int,
) -> tuple[str | None, int, int, bool, bool]:
    pressure_items: list[tuple[str, int]] = [
        (key, value)
        for key, value in value_components.items()
        if key in _SEARCH_PRESSURE_COMPONENT_KEYS and value < 0
    ]
    risk_pressure_total = sum(-value for _, value in pressure_items)

    candidates = pressure_items.copy()
    if sequence_adjustment != 0:
        candidates.append(("search_sequence_adjustment", sequence_adjustment))
    if not candidates:
        return None, 0, risk_pressure_total, False, False

    dominant_pressure, dominant_value = max(
        candidates,
        key=lambda item: (abs(item[1]), item[0]),
    )
    return (
        dominant_pressure,
        dominant_value,
        risk_pressure_total,
        dominant_pressure != "search_sequence_adjustment" and dominant_value < 0,
        dominant_pressure == "search_sequence_adjustment",
    )


def _first_action_delta(state: GameState, action: Action) -> dict[str, int]:
    before = build_search_position_profile(state)
    after_state = simulate_action(state, action)
    after = build_search_position_profile(after_state)
    return {
        "starving_network_count": after.starving_network_count - before.starving_network_count,
        "food_pressure": after.food_pressure - before.food_pressure,
        "isolated_city_count": after.isolated_city_count - before.isolated_city_count,
        "network_count": after.network_count - before.network_count,
        "connected_city_count": after.connected_city_count - before.connected_city_count,
        "road_overbuild": _road_overbuild_metric(after_state) - _road_overbuild_metric(state),
    }


def _has_food_rescue_need(state: GameState) -> bool:
    return (
        any(network.resources.food <= 0 for network in state.networks.values())
        or sum(network.resources.food for network in state.networks.values()) < 0
        or _max_food_pressure(state) >= FOOD_CONSUMPTION_PER_CITY * 2
    )


def _has_network_connect_need(state: GameState) -> bool:
    if len(state.cities) < 2:
        return False
    isolated_cities = sum(
        len(network.city_ids) for network in state.networks.values() if len(network.city_ids) == 1
    )
    network_limit = max(1, len(state.cities) // 4)
    return isolated_cities > 0 or len(state.networks) > network_limit


def _has_growth_stall(state: GameState) -> bool:
    if _turns_remaining(state) < 20:
        return False
    recent_contexts = state.stats.decision_contexts[-3:]
    if len(recent_contexts) < 3:
        return False
    return sum(1 for context in recent_contexts if context.get("chosen_action_type") == "skip") >= 2


def _has_food_watch_warning(state: GameState, profile: SearchPositionProfile) -> bool:
    if profile.starving_network_count > 0:
        return False
    if profile.food_pressure > FOOD_CONSUMPTION_PER_CITY:
        return True
    if (
        profile.is_small_long_map
        and profile.safe_expansion_deficit <= 0
        and profile.expansion_deficit > 0
        and profile.turns_remaining > 20
    ):
        return True
    if profile.city_count >= max(3, profile.safe_target_city_count - 1):
        total_food = sum(network.resources.food for network in state.networks.values())
        return total_food < max(1, profile.city_count) * FOOD_CONSUMPTION_PER_CITY * 3
    return False


def _max_food_pressure(state: GameState) -> int:
    return max(
        (
            len(network.city_ids) * FOOD_CONSUMPTION_PER_CITY * 2 - network.resources.food
            for network in state.networks.values()
        ),
        default=0,
    )


def _turns_remaining(state: GameState) -> int:
    return max(0, state.config.turn_limit - state.turn)


def _endgame_push_threshold(state: GameState) -> int:
    turn_limit = state.config.turn_limit
    return max(10, min(18, turn_limit // 4))


def _better_node(current: SearchNode | None, candidate: SearchNode) -> SearchNode:
    if current is None:
        return candidate
    if _node_sort_key(candidate) < _node_sort_key(current):
        return candidate
    return current


def _node_sort_key(
    node: SearchNode,
) -> tuple[int, tuple[tuple[int, tuple[int, int], int, int, int], ...]]:
    return (-node.value, tuple(_action_sort_key(action) for action in node.sequence))


def _action_sort_key(action: Action) -> tuple[int, tuple[int, int], int, int, int]:
    coord = action.coord if action.coord is not None else (_MISSING_SORT_VALUE, _MISSING_SORT_VALUE)
    building_type_order = (
        _BUILDING_TYPE_ORDER[action.building_type]
        if action.building_type is not None
        else _MISSING_SORT_VALUE
    )
    tech_type_order = (
        _TECH_TYPE_ORDER[action.tech_type] if action.tech_type is not None else _MISSING_SORT_VALUE
    )
    return (
        _ACTION_TYPE_ORDER[action.action_type],
        coord,
        action.city_id if action.city_id is not None else _MISSING_SORT_VALUE,
        building_type_order,
        tech_type_order,
    )


def _action_to_dict(action: Action) -> dict[str, object]:
    result: dict[str, object] = {"action_type": action.action_type.value}
    if action.coord is not None:
        result["x"] = action.coord[0]
        result["y"] = action.coord[1]
    if action.city_id is not None:
        result["city_id"] = action.city_id
    if action.building_type is not None:
        result["building_type"] = action.building_type.value
    if action.tech_type is not None:
        result["tech_type"] = action.tech_type.value
    return result
