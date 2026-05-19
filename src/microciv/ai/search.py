"""Rolling-horizon beam-search policy."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from heapq import heappop, heappush
from typing import Protocol

from microciv.ai.greedy import GreedyPlanSnapshot, GreedyPolicy
from microciv.ai.heuristics import (
    HeuristicContext,
    build_heuristic_context,
    building_action_score,
    city_network_pressure,
    city_site_score_for_context,
    context_is_river_adjacent_site,
    context_passable_network_map,
    partition_actions,
    research_action_score,
    resource_ring_bonus_for_context,
    resource_ring_counts_for_context,
    road_site_score_for_context,
    site_budget,
)
from microciv.ai.policy import Policy, get_legal_actions, simulate_action
from microciv.ai.search_support import (
    SEARCH_MODE_CONNECT,
    SEARCH_MODE_EXPAND,
    SEARCH_MODE_RESCUE,
    SearchCandidate,
    SearchCandidateSet,
    SearchLeafEvaluation,
    SearchPositionProfile,
    build_search_position_profile,
    evaluate_search_leaf,
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
from microciv.game.models import GameState, Network
from microciv.game.scoring import score_breakdown
from microciv.utils.grid import Coord, cardinal_neighbors

SEARCH_DEPTH_REASON_FIXED = "fixed"
SEARCH_DEPTH_REASON_FOOD_RESCUE = "food_rescue"
SEARCH_DEPTH_REASON_NETWORK_CONNECT = "network_connect"
SEARCH_DEPTH_REASON_GROWTH_STALL = "growth_stall"
SEARCH_DEPTH_REASON_FOOD_WATCH = "food_watch"
SEARCH_DEPTH_REASON_ENDGAME_PUSH = "endgame_push"
SEARCH_DEPTH_REASON_STEADY = "steady"
SEARCH_PLANNING_MODE_BEAM = "beam_search"
SEARCH_PLANNING_MODE_GREEDY_PASSTHROUGH = "greedy_passthrough"
SEARCH_PLANNING_REASON_RISK_SEARCH = "risk_search"
SEARCH_PLANNING_REASON_GREEDY_DIRECT = "greedy_direct"

SEARCH_INTERVENTION_NONE = "none"
SEARCH_INTERVENTION_FOOD_RESCUE = "food_rescue_probe"
SEARCH_INTERVENTION_CONNECT = "connect_probe"
SEARCH_INTERVENTION_STALL = "stall_probe"

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
class BridgePath:
    actions: tuple[Action, ...]
    source_network_id: int
    target_network_id: int
    progress_after_first_step: int

    @property
    def min_steps(self) -> int:
        return len(self.actions)


@dataclass(slots=True, frozen=True)
class BridgeDiagnostics:
    candidate_count: int = 0
    min_steps: int | None = None
    progress_after_first_step: int = 0


@dataclass(slots=True, frozen=True)
class RootCandidateDiagnostic:
    action: Action
    value: int


@dataclass(slots=True, frozen=True)
class PlannedSearchDecision:
    action: Action
    context: dict[str, object]
    greedy_action: Action
    root_candidate_diagnostics: tuple[RootCandidateDiagnostic, ...] = ()


@dataclass(slots=True, frozen=True)
class SearchNode:
    state: GameState
    sequence: tuple[Action, ...]
    value: int
    sequence_adjustment: int
    leaf_evaluation: SearchLeafEvaluation
    bridge_diagnostics: BridgeDiagnostics = BridgeDiagnostics()


@dataclass(slots=True, frozen=True)
class RiskProfile:
    score_total: int
    starving_network_count: int
    food_pressure: int
    min_network_food: int
    network_count: int
    connected_city_count: int
    isolated_city_count: int
    starving_isolated_network_count: int = 0


@dataclass(slots=True, frozen=True)
class RiskProbeDecision:
    trigger: str | None
    depth: int
    reason: str


@dataclass(slots=True, frozen=True)
class RiskProbeResult:
    accepted: bool
    accepted_reason: str | None
    rejected_reason: str | None


@dataclass(slots=True)
class SimulationCache:
    entries: dict[tuple[int, Action], GameState] = field(default_factory=dict)
    legal_actions_by_state: dict[int, list[Action]] = field(default_factory=dict)
    profiles_by_state: dict[int, SearchPositionProfile] = field(default_factory=dict)
    heuristic_contexts_by_state: dict[int, HeuristicContext] = field(default_factory=dict)
    risk_profiles_by_state: dict[int, RiskProfile] = field(default_factory=dict)
    network_food_risk_by_state: dict[int, dict[str, int]] = field(default_factory=dict)
    leaf_evaluations_by_state: dict[tuple[int, int], SearchLeafEvaluation] = field(
        default_factory=dict
    )
    greedy_plans_by_state: dict[int, GreedyPlanSnapshot] = field(default_factory=dict)
    bridge_paths_by_state: dict[int, tuple[BridgePath, ...]] = field(default_factory=dict)
    bridge_paths_by_first_action_by_state: dict[int, dict[Action, BridgePath]] = field(
        default_factory=dict
    )
    hits: int = 0
    misses: int = 0

    def simulate(self, state: GameState, action: Action) -> GameState:
        key = (id(state), action)
        cached = self.entries.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        simulated = simulate_action(state, action)
        self.entries[key] = simulated
        self.misses += 1
        return simulated

    def legal_actions(self, state: GameState) -> list[Action]:
        state_key = id(state)
        cached = self.legal_actions_by_state.get(state_key)
        if cached is None:
            cached = get_legal_actions(state)
            self.legal_actions_by_state[state_key] = cached
        return cached

    def profile(self, state: GameState) -> SearchPositionProfile:
        state_key = id(state)
        cached = self.profiles_by_state.get(state_key)
        if cached is None:
            cached = build_search_position_profile(state)
            self.profiles_by_state[state_key] = cached
        return cached

    def heuristic_context(self, state: GameState) -> HeuristicContext:
        state_key = id(state)
        cached = self.heuristic_contexts_by_state.get(state_key)
        if cached is None:
            cached = build_heuristic_context(state)
            self.heuristic_contexts_by_state[state_key] = cached
        return cached

    def network_food_risk(self, state: GameState) -> dict[str, int]:
        state_key = id(state)
        cached = self.network_food_risk_by_state.get(state_key)
        if cached is None:
            cached = _network_food_risk_profile(state)
            self.network_food_risk_by_state[state_key] = cached
        return cached

    def risk_profile(self, state: GameState) -> RiskProfile:
        state_key = id(state)
        cached = self.risk_profiles_by_state.get(state_key)
        if cached is None:
            profile = self.profile(state)
            network_risk = self.network_food_risk(state)
            cached = _risk_profile_from_parts(state, profile, network_risk)
            self.risk_profiles_by_state[state_key] = cached
        return cached

    def leaf_evaluation(
        self,
        state: GameState,
        *,
        root_state: GameState,
    ) -> SearchLeafEvaluation:
        key = (id(state), id(root_state))
        cached = self.leaf_evaluations_by_state.get(key)
        if cached is None:
            cached = evaluate_search_leaf(state, root_state=root_state)
            self.leaf_evaluations_by_state[key] = cached
        return cached

    def greedy_plan(self, greedy_policy: GreedyPolicy, state: GameState) -> GreedyPlanSnapshot:
        state_key = id(state)
        cached = self.greedy_plans_by_state.get(state_key)
        if cached is None:
            cached = greedy_policy.plan_for_search(state)
            self.greedy_plans_by_state[state_key] = cached
        return cached

    def bridge_paths(self, state: GameState) -> tuple[BridgePath, ...]:
        state_key = id(state)
        cached = self.bridge_paths_by_state.get(state_key)
        if cached is None:
            cached = tuple(
                _bridge_paths_for_state(
                    state,
                    legal_actions=self.legal_actions(state),
                    simulation_cache=self,
                )
            )
            self.bridge_paths_by_state[state_key] = cached
        return cached

    def bridge_path_for_first_action(
        self,
        state: GameState,
        action: Action,
    ) -> BridgePath | None:
        if action.action_type is not ActionType.BUILD_ROAD or action.coord is None:
            return None
        state_key = id(state)
        cached = self.bridge_paths_by_first_action_by_state.get(state_key)
        if cached is None:
            cached = {path.actions[0]: path for path in self.bridge_paths(state) if path.actions}
            self.bridge_paths_by_first_action_by_state[state_key] = cached
        return cached.get(action)


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
    bridge_candidate_count: int = 0
    bridge_min_steps: int | None = None
    bridge_progress_after_first_step: int = 0
    root_candidate_diagnostics: list[RootCandidateDiagnostic] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class GreedyVetoDecision:
    reason: str | None = None
    trigger: str | None = None


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
        self._greedy_policy = GreedyPolicy()

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

        simulation_cache = SimulationCache()
        depth_decision = self._choose_depth(state)
        root_profile = simulation_cache.profile(state)
        root_risk = simulation_cache.risk_profile(state)
        greedy_plan = simulation_cache.greedy_plan(self._greedy_policy, state)
        greedy_after_state = simulation_cache.simulate(state, greedy_plan.action)
        greedy_after_risk = simulation_cache.risk_profile(greedy_after_state)
        probe_decision = _risk_probe_decision(
            state=state,
            root_profile=root_profile,
            root_risk=root_risk,
            greedy_after=greedy_after_risk,
            greedy_plan=greedy_plan,
            depth_decision=depth_decision,
        )
        greedy_veto = _greedy_veto_decision(
            state=state,
            root_profile=root_profile,
            root_risk=root_risk,
            greedy_plan=greedy_plan,
            greedy_after=greedy_after_risk,
            simulation_cache=simulation_cache,
        )
        probe_decision = _probe_decision_after_veto(
            probe_decision,
            greedy_veto=greedy_veto,
            depth_decision=depth_decision,
            max_depth=self.search_max_depth,
        )

        if probe_decision.trigger is None:
            greedy_evaluation = simulation_cache.leaf_evaluation(
                greedy_after_state,
                root_state=state,
            )
            decision = self._build_planned_decision(
                state=state,
                action=greedy_plan.action,
                root_profile=root_profile,
                depth_decision=depth_decision,
                actual_depth=0,
                telemetry=SearchTelemetry(),
                best_evaluation=greedy_evaluation,
                best_value=greedy_evaluation.value,
                best_sequence_adjustment=0,
                best_sequence=(greedy_plan.action,),
                planning_mode=SEARCH_PLANNING_MODE_GREEDY_PASSTHROUGH,
                planning_reason=SEARCH_PLANNING_REASON_GREEDY_DIRECT,
                greedy_plan=greedy_plan,
                root_risk=root_risk,
                greedy_after_risk=greedy_after_risk,
                selected_after_risk=greedy_after_risk,
                simulation_cache=simulation_cache,
                overrode_greedy=False,
                intervention_trigger=SEARCH_INTERVENTION_NONE,
                accepted_reason=None,
                rejected_reason=probe_decision.reason,
                greedy_veto_reason=greedy_veto.reason,
            )
            self._cache_key = cache_key
            self._cached_decision = decision
            return decision

        telemetry = SearchTelemetry()
        best_node = self._run_risk_beam_search(
            state=state,
            trigger=probe_decision.trigger,
            depth=probe_decision.depth,
            telemetry=telemetry,
            simulation_cache=simulation_cache,
            blocked_root_action=greedy_plan.action if greedy_veto.reason is not None else None,
        )
        if best_node is None or not best_node.sequence:
            fallback = _best_veto_fallback_action(
                state=state,
                greedy_action=greedy_plan.action,
                veto_reason=greedy_veto.reason,
                simulation_cache=simulation_cache,
            )
            if fallback is not None:
                selected_after_state = simulation_cache.simulate(state, fallback)
                selected_after_risk = simulation_cache.risk_profile(selected_after_state)
                fallback_evaluation = simulation_cache.leaf_evaluation(
                    selected_after_state,
                    root_state=state,
                )
                decision = self._build_planned_decision(
                    state=state,
                    action=fallback,
                    root_profile=root_profile,
                    depth_decision=depth_decision,
                    actual_depth=probe_decision.depth,
                    telemetry=telemetry,
                    best_evaluation=fallback_evaluation,
                    best_value=fallback_evaluation.value,
                    best_sequence_adjustment=0,
                    best_sequence=(fallback,),
                    planning_mode=SEARCH_PLANNING_MODE_BEAM,
                    planning_reason=SEARCH_PLANNING_REASON_RISK_SEARCH,
                    greedy_plan=greedy_plan,
                    root_risk=root_risk,
                    greedy_after_risk=greedy_after_risk,
                    selected_after_risk=selected_after_risk,
                    simulation_cache=simulation_cache,
                    overrode_greedy=True,
                    intervention_trigger=probe_decision.trigger,
                    accepted_reason="greedy_veto_fallback",
                    rejected_reason=None,
                    greedy_veto_reason=greedy_veto.reason,
                )
                self._cache_key = cache_key
                self._cached_decision = decision
                return decision

            greedy_evaluation = simulation_cache.leaf_evaluation(
                greedy_after_state,
                root_state=state,
            )
            decision = self._build_planned_decision(
                state=state,
                action=greedy_plan.action,
                root_profile=root_profile,
                depth_decision=depth_decision,
                actual_depth=probe_decision.depth,
                telemetry=telemetry,
                best_evaluation=greedy_evaluation,
                best_value=greedy_evaluation.value,
                best_sequence_adjustment=0,
                best_sequence=(greedy_plan.action,),
                planning_mode=SEARCH_PLANNING_MODE_BEAM,
                planning_reason=SEARCH_PLANNING_REASON_RISK_SEARCH,
                greedy_plan=greedy_plan,
                root_risk=root_risk,
                greedy_after_risk=greedy_after_risk,
                selected_after_risk=greedy_after_risk,
                simulation_cache=simulation_cache,
                overrode_greedy=False,
                intervention_trigger=probe_decision.trigger,
                accepted_reason=None,
                rejected_reason="no_probe_candidate",
                greedy_veto_reason=greedy_veto.reason,
            )
            self._cache_key = cache_key
            self._cached_decision = decision
            return decision

        selected_action = best_node.sequence[0]
        selected_after_state = simulation_cache.simulate(state, selected_action)
        selected_after_risk = simulation_cache.risk_profile(selected_after_state)
        probe_result = _evaluate_probe_result(
            trigger=probe_decision.trigger,
            root_risk=root_risk,
            greedy_action=greedy_plan.action,
            selected_action=selected_action,
            greedy_after=greedy_after_risk,
            selected_after=selected_after_risk,
        )
        if (
            selected_action != greedy_plan.action
            and best_node.bridge_diagnostics.candidate_count > 0
            and best_node.sequence
            and simulation_cache.bridge_path_for_first_action(state, selected_action) is not None
        ):
            bridge_probe_result = _evaluate_bridge_probe_result(
                root_risk=root_risk,
                greedy_action=greedy_plan.action,
                selected_action=selected_action,
                greedy_after=greedy_after_risk,
                selected_sequence_after=simulation_cache.risk_profile(best_node.state),
            )
            if bridge_probe_result is not None and (
                bridge_probe_result.accepted or not probe_result.accepted
            ):
                probe_result = bridge_probe_result

        committed_route_result = _evaluate_committed_route_probe_result(
            state=state,
            simulation_cache=simulation_cache,
            root_risk=root_risk,
            greedy_action=greedy_plan.action,
            selected_action=selected_action,
            greedy_after=greedy_after_risk,
            selected_after=selected_after_risk,
        )
        if committed_route_result is not None and not probe_result.accepted:
            probe_result = committed_route_result

        veto_probe_result = _evaluate_greedy_veto_probe_result(
            state=state,
            simulation_cache=simulation_cache,
            veto_reason=greedy_veto.reason,
            root_risk=root_risk,
            greedy_action=greedy_plan.action,
            selected_action=selected_action,
            greedy_after=greedy_after_risk,
            selected_after=selected_after_risk,
        )
        if veto_probe_result is not None and not probe_result.accepted:
            probe_result = veto_probe_result

        if selected_action != greedy_plan.action and probe_result.accepted:
            action = selected_action
            best_evaluation = best_node.leaf_evaluation
            best_value = best_node.value
            best_sequence_adjustment = best_node.sequence_adjustment
            best_sequence = best_node.sequence
        else:
            action = greedy_plan.action
            best_evaluation = simulation_cache.leaf_evaluation(
                greedy_after_state,
                root_state=state,
            )
            best_value = best_evaluation.value
            best_sequence_adjustment = 0
            best_sequence = (greedy_plan.action,)
            selected_after_risk = greedy_after_risk

        if action == greedy_plan.action and greedy_veto.reason is not None:
            fallback = _best_veto_fallback_action(
                state=state,
                greedy_action=greedy_plan.action,
                veto_reason=greedy_veto.reason,
                simulation_cache=simulation_cache,
            )
            if fallback is not None:
                action = fallback
                selected_after_state = simulation_cache.simulate(state, action)
                selected_after_risk = simulation_cache.risk_profile(selected_after_state)
                best_evaluation = simulation_cache.leaf_evaluation(
                    selected_after_state,
                    root_state=state,
                )
                best_value = best_evaluation.value
                best_sequence_adjustment = 0
                best_sequence = (action,)
                probe_result = RiskProbeResult(
                    accepted=True,
                    accepted_reason="greedy_veto_fallback",
                    rejected_reason=None,
                )

        decision = PlannedSearchDecision(
            action=action,
            context=self._build_context(
                state=state,
                action=action,
                root_profile=root_profile,
                depth_decision=depth_decision,
                actual_depth=probe_decision.depth,
                telemetry=telemetry,
                best_evaluation=best_evaluation,
                best_value=best_value,
                best_sequence_adjustment=best_sequence_adjustment,
                best_sequence=best_sequence,
                planning_mode=SEARCH_PLANNING_MODE_BEAM,
                planning_reason=SEARCH_PLANNING_REASON_RISK_SEARCH,
                greedy_plan=greedy_plan,
                root_risk=root_risk,
                greedy_after_risk=greedy_after_risk,
                selected_after_risk=selected_after_risk,
                simulation_cache=simulation_cache,
                overrode_greedy=action != greedy_plan.action,
                intervention_trigger=probe_decision.trigger,
                accepted_reason=probe_result.accepted_reason
                if action != greedy_plan.action
                else None,
                rejected_reason=probe_result.rejected_reason
                if action == greedy_plan.action
                else None,
                greedy_veto_reason=greedy_veto.reason,
            ),
            greedy_action=greedy_plan.action,
            root_candidate_diagnostics=tuple(telemetry.root_candidate_diagnostics),
        )
        self._cache_key = cache_key
        self._cached_decision = decision
        return decision

    def _build_planned_decision(
        self,
        *,
        state: GameState,
        action: Action,
        root_profile: SearchPositionProfile,
        depth_decision: SearchDepthDecision,
        actual_depth: int,
        telemetry: SearchTelemetry,
        best_evaluation: SearchLeafEvaluation,
        best_value: int,
        best_sequence_adjustment: int,
        best_sequence: tuple[Action, ...],
        planning_mode: str,
        planning_reason: str,
        greedy_plan: GreedyPlanSnapshot,
        root_risk: RiskProfile,
        greedy_after_risk: RiskProfile,
        selected_after_risk: RiskProfile,
        simulation_cache: SimulationCache,
        overrode_greedy: bool,
        intervention_trigger: str,
        accepted_reason: str | None,
        rejected_reason: str | None,
        greedy_veto_reason: str | None,
    ) -> PlannedSearchDecision:
        return PlannedSearchDecision(
            action=action,
            context=self._build_context(
                state=state,
                action=action,
                root_profile=root_profile,
                depth_decision=depth_decision,
                actual_depth=actual_depth,
                telemetry=telemetry,
                best_evaluation=best_evaluation,
                best_value=best_value,
                best_sequence_adjustment=best_sequence_adjustment,
                best_sequence=best_sequence,
                planning_mode=planning_mode,
                planning_reason=planning_reason,
                greedy_plan=greedy_plan,
                root_risk=root_risk,
                greedy_after_risk=greedy_after_risk,
                selected_after_risk=selected_after_risk,
                simulation_cache=simulation_cache,
                overrode_greedy=overrode_greedy,
                intervention_trigger=intervention_trigger,
                accepted_reason=accepted_reason,
                rejected_reason=rejected_reason,
                greedy_veto_reason=greedy_veto_reason,
            ),
            greedy_action=greedy_plan.action,
            root_candidate_diagnostics=tuple(telemetry.root_candidate_diagnostics),
        )

    def _build_context(
        self,
        *,
        state: GameState,
        action: Action,
        root_profile: SearchPositionProfile,
        depth_decision: SearchDepthDecision,
        actual_depth: int,
        telemetry: SearchTelemetry,
        best_evaluation: SearchLeafEvaluation,
        best_value: int,
        best_sequence_adjustment: int,
        best_sequence: tuple[Action, ...],
        planning_mode: str,
        planning_reason: str,
        greedy_plan: GreedyPlanSnapshot,
        root_risk: RiskProfile,
        greedy_after_risk: RiskProfile,
        selected_after_risk: RiskProfile,
        simulation_cache: SimulationCache,
        overrode_greedy: bool,
        intervention_trigger: str,
        accepted_reason: str | None,
        rejected_reason: str | None,
        greedy_veto_reason: str | None,
    ) -> dict[str, object]:
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
        root_profile = telemetry.root_profile or root_profile
        root_legal_counts = telemetry.root_legal_counts_by_type or greedy_plan.legal_counts_by_type
        root_candidate_counts = telemetry.root_candidate_counts_by_type or {
            action_type: 0 for action_type in ActionType
        }
        legal_action_count = telemetry.root_legal_action_count or sum(root_legal_counts.values())
        root_candidate_total = sum(root_candidate_counts.values())
        candidate_cut_ratio = (
            (legal_action_count - root_candidate_total) / legal_action_count
            if legal_action_count
            else 0.0
        )
        root_candidate_diagnostics = _root_candidate_diagnostics(
            telemetry.root_candidate_diagnostics,
            chosen_action=action,
        )
        action_delta_diagnostics = _action_delta_diagnostics(
            state,
            action,
            simulation_cache=simulation_cache,
        )
        route_diagnostics = _route_diagnostics(
            state,
            action,
            simulation_cache=simulation_cache,
        )
        return {
            **greedy_plan.context,
            "search_mode": root_profile.mode,
            "search_depth": depth_decision.depth,
            "search_actual_depth": actual_depth,
            "search_base_depth": self.search_depth,
            "search_max_depth": self.search_max_depth,
            "search_depth_reason": depth_decision.reason,
            "search_deep_search_enabled": planning_mode == SEARCH_PLANNING_MODE_BEAM
            and actual_depth > 1,
            "search_planning_mode": planning_mode,
            "search_planning_reason": planning_reason,
            "search_overrode_greedy": overrode_greedy,
            "search_intervention_trigger": intervention_trigger,
            "search_probe_accepted_reason": accepted_reason,
            "search_probe_rejected_reason": rejected_reason,
            "search_greedy_veto_reason": greedy_veto_reason,
            "search_beam_width": self.search_beam_width,
            "search_candidate_limit": self.search_candidate_limit,
            "search_root_legal_build_city_count": root_legal_counts[ActionType.BUILD_CITY],
            "search_root_legal_build_road_count": root_legal_counts[ActionType.BUILD_ROAD],
            "search_root_legal_build_building_count": root_legal_counts[ActionType.BUILD_BUILDING],
            "search_root_legal_research_tech_count": root_legal_counts[ActionType.RESEARCH_TECH],
            "search_root_legal_skip_count": root_legal_counts[ActionType.SKIP],
            "search_root_candidate_build_city_count": root_candidate_counts[ActionType.BUILD_CITY],
            "search_root_candidate_build_road_count": root_candidate_counts[ActionType.BUILD_ROAD],
            "search_root_candidate_build_building_count": root_candidate_counts[
                ActionType.BUILD_BUILDING
            ],
            "search_root_candidate_research_tech_count": root_candidate_counts[
                ActionType.RESEARCH_TECH
            ],
            "search_root_candidate_skip_count": root_candidate_counts[ActionType.SKIP],
            "search_root_candidate_cut_ratio": candidate_cut_ratio,
            "search_root_safe_city_candidate_count": telemetry.root_safe_city_candidate_count,
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
            "search_bridge_candidate_count": telemetry.bridge_candidate_count,
            "search_bridge_min_steps": telemetry.bridge_min_steps,
            "search_bridge_progress_after_first_step": (telemetry.bridge_progress_after_first_step),
            **route_diagnostics,
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
            "search_best_sequence": [_action_to_dict(item) for item in best_sequence],
            "search_greedy_after_score_total": greedy_after_risk.score_total,
            "search_greedy_after_starving_network_count": (
                greedy_after_risk.starving_network_count
            ),
            "search_greedy_after_food_pressure": greedy_after_risk.food_pressure,
            "search_greedy_after_min_network_food": greedy_after_risk.min_network_food,
            "search_greedy_after_network_count": greedy_after_risk.network_count,
            "search_greedy_after_connected_city_count": greedy_after_risk.connected_city_count,
            "search_greedy_after_isolated_city_count": greedy_after_risk.isolated_city_count,
            "search_selected_after_score_total": selected_after_risk.score_total,
            "search_selected_after_starving_network_count": (
                selected_after_risk.starving_network_count
            ),
            "search_selected_after_food_pressure": selected_after_risk.food_pressure,
            "search_selected_after_min_network_food": selected_after_risk.min_network_food,
            "search_selected_after_network_count": selected_after_risk.network_count,
            "search_selected_after_connected_city_count": selected_after_risk.connected_city_count,
            "search_selected_after_isolated_city_count": selected_after_risk.isolated_city_count,
            "search_simulation_cache_hits": simulation_cache.hits,
            "search_simulation_cache_misses": simulation_cache.misses,
            **root_candidate_diagnostics,
            **action_delta_diagnostics,
        }

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

    def _run_risk_beam_search(
        self,
        *,
        state: GameState,
        trigger: str,
        depth: int,
        telemetry: SearchTelemetry,
        simulation_cache: SimulationCache,
        blocked_root_action: Action | None,
    ) -> SearchNode | None:
        root_evaluation = simulation_cache.leaf_evaluation(state, root_state=state)
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

                candidate_set = _generate_risk_search_candidates(
                    self._greedy_policy,
                    node.state,
                    trigger,
                    self.search_candidate_limit,
                    simulation_cache,
                    blocked_action=blocked_root_action if not node.sequence else None,
                )
                if not node.sequence and telemetry.root_profile is None:
                    self._record_root_candidate_set(
                        node.state,
                        candidate_set,
                        telemetry,
                        simulation_cache=simulation_cache,
                    )
                telemetry.nodes_expanded += 1
                telemetry.candidates_considered += len(candidate_set.candidates)

                if not candidate_set.candidates:
                    best_node = _better_node(best_node, node)
                    continue

                for candidate in candidate_set.candidates:
                    simulated_state = simulation_cache.simulate(node.state, candidate.action)
                    leaf_evaluation = simulation_cache.leaf_evaluation(
                        simulated_state,
                        root_state=state,
                    )
                    telemetry.leaf_count += 1
                    sequence = (*node.sequence, candidate.action)
                    bridge_diagnostics = _sequence_bridge_diagnostics(
                        node.bridge_diagnostics,
                        node.state,
                        candidate.action,
                        simulation_cache=simulation_cache,
                    )
                    sequence_adjustment = _sequence_adjustment(
                        state,
                        simulated_state,
                        sequence,
                        simulation_cache=simulation_cache,
                    )
                    child = SearchNode(
                        state=simulated_state,
                        sequence=sequence,
                        value=leaf_evaluation.value + sequence_adjustment,
                        sequence_adjustment=sequence_adjustment,
                        leaf_evaluation=leaf_evaluation,
                        bridge_diagnostics=bridge_diagnostics,
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
        state: GameState,
        candidate_set: SearchCandidateSet,
        telemetry: SearchTelemetry,
        *,
        simulation_cache: SimulationCache,
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
        telemetry.bridge_candidate_count = 0
        telemetry.bridge_min_steps = None
        telemetry.bridge_progress_after_first_step = 0
        for candidate in candidate_set.candidates:
            bridge_path = simulation_cache.bridge_path_for_first_action(state, candidate.action)
            if bridge_path is None:
                continue
            telemetry.bridge_candidate_count += 1
            telemetry.bridge_min_steps = _min_optional_int(
                telemetry.bridge_min_steps,
                bridge_path.min_steps,
            )
            telemetry.bridge_progress_after_first_step = max(
                telemetry.bridge_progress_after_first_step,
                bridge_path.progress_after_first_step,
            )

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


def _risk_profile(state: GameState) -> RiskProfile:
    profile = build_search_position_profile(state)
    network_risk = _network_food_risk_profile(state)
    return _risk_profile_from_parts(state, profile, network_risk)


def _risk_profile_from_parts(
    state: GameState,
    profile: SearchPositionProfile,
    network_risk: dict[str, int],
) -> RiskProfile:
    return RiskProfile(
        score_total=score_breakdown(state).total,
        starving_network_count=profile.starving_network_count,
        food_pressure=profile.food_pressure,
        min_network_food=network_risk["min_food"],
        network_count=profile.network_count,
        connected_city_count=profile.connected_city_count,
        isolated_city_count=profile.isolated_city_count,
        starving_isolated_network_count=sum(
            1
            for network in state.networks.values()
            if len(network.city_ids) == 1 and _network_needs_food(network)
        ),
    )


def _risk_probe_decision(
    *,
    state: GameState,
    root_profile: SearchPositionProfile,
    root_risk: RiskProfile,
    greedy_after: RiskProfile,
    greedy_plan: GreedyPlanSnapshot,
    depth_decision: SearchDepthDecision,
) -> RiskProbeDecision:
    if _food_rescue_probe_needed(root_risk, greedy_after):
        if _recent_probe_rejected_without_worsening(
            state,
            SEARCH_INTERVENTION_FOOD_RESCUE,
            root_risk,
        ):
            return RiskProbeDecision(
                trigger=None,
                depth=0,
                reason="recent_food_rescue_probe_rejected",
            )
        return RiskProbeDecision(
            trigger=SEARCH_INTERVENTION_FOOD_RESCUE,
            depth=min(depth_decision.depth, 2),
            reason="greedy_food_risk_not_improved",
        )
    if _connect_probe_needed(state, root_risk, greedy_after, greedy_plan):
        if _recent_probe_rejected_without_worsening(
            state,
            SEARCH_INTERVENTION_CONNECT,
            root_risk,
        ):
            return RiskProbeDecision(
                trigger=None,
                depth=0,
                reason="recent_connect_probe_rejected",
            )
        return RiskProbeDecision(
            trigger=SEARCH_INTERVENTION_CONNECT,
            depth=min(depth_decision.depth, 2),
            reason="greedy_connect_risk_not_improved",
        )
    if _stall_probe_needed(state, root_profile, root_risk, greedy_after, greedy_plan):
        if _recent_probe_rejected_without_worsening(
            state,
            SEARCH_INTERVENTION_STALL,
            root_risk,
        ):
            return RiskProbeDecision(
                trigger=None,
                depth=0,
                reason="recent_stall_probe_rejected",
            )
        return RiskProbeDecision(
            trigger=SEARCH_INTERVENTION_STALL,
            depth=min(depth_decision.depth, 2),
            reason="greedy_stall_signal",
        )
    return RiskProbeDecision(trigger=None, depth=0, reason="healthy_greedy_passthrough")


def _greedy_veto_decision(
    *,
    state: GameState,
    root_profile: SearchPositionProfile,
    root_risk: RiskProfile,
    greedy_plan: GreedyPlanSnapshot,
    greedy_after: RiskProfile,
    simulation_cache: SimulationCache,
) -> GreedyVetoDecision:
    reason = _greedy_veto_reason(
        state=state,
        root_profile=root_profile,
        root_risk=root_risk,
        greedy_plan=greedy_plan,
        greedy_after=greedy_after,
        simulation_cache=simulation_cache,
    )
    if reason is None:
        return GreedyVetoDecision()
    return GreedyVetoDecision(reason=reason, trigger=_veto_probe_trigger(reason, root_risk))


def _probe_decision_after_veto(
    probe_decision: RiskProbeDecision,
    *,
    greedy_veto: GreedyVetoDecision,
    depth_decision: SearchDepthDecision,
    max_depth: int,
) -> RiskProbeDecision:
    if greedy_veto.reason is None or greedy_veto.trigger is None:
        return probe_decision
    if probe_decision.trigger is not None:
        return probe_decision
    return RiskProbeDecision(
        trigger=greedy_veto.trigger,
        depth=max(2, min(max_depth, max(depth_decision.depth, 3))),
        reason=f"greedy_veto:{greedy_veto.reason}",
    )


def _veto_probe_trigger(reason: str, root_risk: RiskProfile) -> str:
    if reason.startswith("skip_"):
        return SEARCH_INTERVENTION_STALL
    if reason.startswith("route_"):
        return SEARCH_INTERVENTION_CONNECT
    if reason.startswith("road_") and (
        root_risk.network_count > 1 or root_risk.isolated_city_count > 0
    ):
        return SEARCH_INTERVENTION_CONNECT
    if root_risk.starving_network_count > 0 or root_risk.food_pressure >= FOOD_CONSUMPTION_PER_CITY:
        return SEARCH_INTERVENTION_FOOD_RESCUE
    if reason.startswith("city_"):
        return SEARCH_INTERVENTION_FOOD_RESCUE
    return SEARCH_INTERVENTION_STALL


def _greedy_veto_reason(
    *,
    state: GameState,
    root_profile: SearchPositionProfile,
    root_risk: RiskProfile,
    greedy_plan: GreedyPlanSnapshot,
    greedy_after: RiskProfile,
    simulation_cache: SimulationCache,
) -> str | None:
    action = greedy_plan.action
    committed_route_action = _preferred_committed_route_action(
        state,
        simulation_cache=simulation_cache,
    )
    if committed_route_action is not None and action != committed_route_action:
        return "route_commitment_deviation"
    if action.action_type is ActionType.BUILD_ROAD:
        return _greedy_road_veto_reason(state, action, simulation_cache=simulation_cache)
    if action.action_type is ActionType.BUILD_CITY and action.coord is not None:
        return _greedy_city_veto_reason(
            state=state,
            root_profile=root_profile,
            root_risk=root_risk,
            action=action,
            greedy_after=greedy_after,
            context=simulation_cache.heuristic_context(state),
        )
    if action.action_type is ActionType.SKIP:
        return _greedy_skip_veto_reason(state, root_risk, simulation_cache=simulation_cache)
    return None


def _greedy_road_veto_reason(
    state: GameState,
    action: Action,
    *,
    simulation_cache: SimulationCache,
) -> str | None:
    if simulation_cache.bridge_path_for_first_action(state, action) is not None:
        return None
    delta = _action_delta_diagnostics(state, action, simulation_cache=simulation_cache)
    connected_delta = int(delta["search_delta_connected_city_count"])
    network_delta = int(delta["search_delta_network_count"])
    food_delta = int(delta["search_delta_food_pressure"])
    overbuild_delta = int(delta["search_delta_road_overbuild"])
    if bool(delta["search_road_after_full_connectivity"]) and connected_delta <= 0:
        return "road_after_full_connectivity"
    if bool(delta["search_road_is_redundant"]):
        return "road_redundant"
    if food_delta > 0 and network_delta >= 0 and connected_delta <= 0:
        return "road_food_pressure_worse"
    if overbuild_delta > 0 and network_delta >= 0 and connected_delta <= 0:
        return "road_overbuild_worse"
    return None


def _greedy_city_veto_reason(
    *,
    state: GameState,
    root_profile: SearchPositionProfile,
    root_risk: RiskProfile,
    action: Action,
    greedy_after: RiskProfile,
    context: HeuristicContext | None = None,
) -> str | None:
    assert action.coord is not None
    context = build_heuristic_context(state) if context is None else context
    coord = action.coord
    budget = site_budget(state, coord, context)
    _forest, _mountain, river, plain, _occupied = resource_ring_counts_for_context(
        context,
        coord,
    )
    river_access = context_is_river_adjacent_site(context, coord)
    distance = _distance_to_existing_network(state, coord)
    connected_to_network = bool(_adjacent_network_ids_for_context(context, coord))
    can_rescue = (
        greedy_after.starving_network_count < root_risk.starving_network_count
        or greedy_after.food_pressure < root_risk.food_pressure
        or greedy_after.min_network_food > root_risk.min_network_food
    )
    if budget.food_balance < 0 and not (connected_to_network and can_rescue):
        return "city_negative_food_balance"
    if plain == 0 and river == 0 and not river_access and (distance is None or distance > 1):
        return "city_no_plain_remote"
    if (
        greedy_after.food_pressure > root_risk.food_pressure + FOOD_CONSUMPTION_PER_CITY
        and budget.food_balance <= 0
        and not can_rescue
    ):
        return "city_food_pressure_worse"
    if root_profile.city_count >= root_profile.safe_target_city_count and budget.food_balance < 2:
        return "city_exceeds_safe_target"
    return None


def _greedy_skip_veto_reason(
    state: GameState,
    root_risk: RiskProfile,
    *,
    simulation_cache: SimulationCache | None = None,
) -> str | None:
    legal_actions = (
        simulation_cache.legal_actions(state)
        if simulation_cache is not None
        else get_legal_actions(state)
    )
    has_non_skip_action = any(action.action_type is not ActionType.SKIP for action in legal_actions)
    if not has_non_skip_action:
        return None
    recent_skip_count = sum(
        1
        for context in state.stats.decision_contexts[-3:]
        if context.get("chosen_action_type") == "skip"
    )
    has_root_risk = (
        root_risk.starving_network_count > 0
        or root_risk.food_pressure >= FOOD_CONSUMPTION_PER_CITY
        or root_risk.network_count > max(1, len(state.cities) // 4)
        or root_risk.isolated_city_count > 0
    )
    if recent_skip_count >= 2 or has_root_risk:
        return "skip_stall_with_legal_actions"
    return None


def _food_rescue_probe_needed(root: RiskProfile, greedy_after: RiskProfile) -> bool:
    has_food_risk = (
        root.starving_network_count > 0
        or root.min_network_food < 0
        or root.starving_isolated_network_count > 0
        or root.food_pressure >= FOOD_CONSUMPTION_PER_CITY * 3
    )
    if not has_food_risk:
        return False
    if greedy_after.starving_network_count > root.starving_network_count:
        return True
    if greedy_after.starving_isolated_network_count >= root.starving_isolated_network_count > 0:
        return True
    return (
        greedy_after.starving_network_count >= root.starving_network_count
        and greedy_after.food_pressure >= root.food_pressure
    )


def _connect_probe_needed(
    state: GameState,
    root: RiskProfile,
    greedy_after: RiskProfile,
    greedy_plan: GreedyPlanSnapshot,
) -> bool:
    if len(state.cities) < 2:
        return False
    has_connect_risk = root.isolated_city_count > 0 or root.network_count > max(
        1,
        len(state.cities) // 4,
    )
    if not has_connect_risk:
        return False
    recent_connection_gain = _recent_search_or_greedy_connection_gain(state)
    if recent_connection_gain and not _has_worsening_starving_isolated_network(
        root,
        greedy_after,
    ):
        return False
    if greedy_plan.stage == SEARCH_MODE_EXPAND and root.starving_network_count == 0:
        return False
    return (
        greedy_after.network_count >= root.network_count
        and greedy_after.isolated_city_count >= root.isolated_city_count
        and greedy_after.connected_city_count <= root.connected_city_count
    )


def _stall_probe_needed(
    state: GameState,
    root_profile: SearchPositionProfile,
    root: RiskProfile,
    greedy_after: RiskProfile,
    greedy_plan: GreedyPlanSnapshot,
) -> bool:
    if greedy_plan.action.action_type is ActionType.SKIP:
        return True
    if (
        sum(
            1
            for context in state.stats.decision_contexts[-3:]
            if context.get("chosen_action_type") == "skip"
        )
        >= 2
    ):
        return True
    if greedy_plan.history.food_rescue_stalled and (
        root.starving_network_count > 0 or root.food_pressure >= FOOD_CONSUMPTION_PER_CITY
    ):
        return True
    greedy_delta = greedy_after.score_total - root.score_total
    if greedy_plan.stage == SEARCH_MODE_RESCUE and greedy_delta < 0:
        return True
    return (
        root_profile.turns_remaining > 12
        and greedy_plan.history.negative_delta_stall
        and greedy_delta <= 0
    )


def _has_worsening_starving_isolated_network(root: RiskProfile, after: RiskProfile) -> bool:
    return (
        root.starving_isolated_network_count > 0
        and after.starving_isolated_network_count >= root.starving_isolated_network_count
    )


def _recent_search_or_greedy_connection_gain(state: GameState) -> bool:
    for context in state.stats.decision_contexts[-3:]:
        connected_delta = context.get("search_delta_connected_city_count")
        network_delta = context.get("search_delta_network_count")
        greedy_network_delta = context.get("greedy_global_network_delta")
        if isinstance(connected_delta, int) and connected_delta > 0:
            return True
        if isinstance(network_delta, int) and network_delta < 0:
            return True
        if isinstance(greedy_network_delta, int) and greedy_network_delta > 0:
            return True
    return False


def _recent_probe_rejected_without_worsening(
    state: GameState,
    trigger: str,
    root: RiskProfile,
) -> bool:
    if root.starving_isolated_network_count > 0:
        return False
    for context in reversed(state.stats.decision_contexts[-8:]):
        if context.get("search_intervention_trigger") != trigger:
            continue
        rejected_reason = context.get("search_probe_rejected_reason")
        if rejected_reason not in {
            "selected_matches_greedy",
            "food_rescue_gate_failed",
            "connect_gate_failed",
            "stall_gate_failed",
        }:
            return False
        previous_starving = _context_int(context, "search_selected_after_starving_network_count")
        previous_pressure = _context_int(context, "search_selected_after_food_pressure")
        previous_networks = _context_int(context, "search_selected_after_network_count")
        previous_isolated = _context_int(context, "search_selected_after_isolated_city_count")
        if previous_starving is not None and root.starving_network_count > previous_starving:
            return False
        pressure_tolerance = FOOD_CONSUMPTION_PER_CITY * 2
        if (
            previous_pressure is not None
            and root.food_pressure > previous_pressure + pressure_tolerance
        ):
            return False
        if previous_networks is not None and root.network_count > previous_networks:
            return False
        if previous_isolated is not None and root.isolated_city_count > previous_isolated:
            return False
        return True
    return False


def _context_int(context: dict[str, object], key: str) -> int | None:
    value = context.get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return None


def _evaluate_probe_result(
    *,
    trigger: str,
    root_risk: RiskProfile,
    greedy_action: Action,
    selected_action: Action,
    greedy_after: RiskProfile,
    selected_after: RiskProfile,
) -> RiskProbeResult:
    if selected_action == greedy_action:
        return RiskProbeResult(
            accepted=False,
            accepted_reason=None,
            rejected_reason="selected_matches_greedy",
        )
    if trigger == SEARCH_INTERVENTION_FOOD_RESCUE:
        if selected_after.starving_network_count < greedy_after.starving_network_count:
            return RiskProbeResult(True, "reduced_starving_networks", None)
        if selected_after.starving_network_count > greedy_after.starving_network_count:
            return RiskProbeResult(False, None, "food_rescue_gate_failed")
        if selected_after.network_count > greedy_after.network_count:
            return RiskProbeResult(False, None, "food_rescue_gate_failed")
        if selected_after.isolated_city_count > greedy_after.isolated_city_count:
            return RiskProbeResult(False, None, "food_rescue_gate_failed")
        pressure_improvement = greedy_after.food_pressure - selected_after.food_pressure
        if pressure_improvement >= FOOD_CONSUMPTION_PER_CITY:
            return RiskProbeResult(True, "reduced_food_pressure", None)
        if (
            greedy_action.action_type is ActionType.SKIP
            and selected_action.action_type is not ActionType.SKIP
            and selected_after.food_pressure <= greedy_after.food_pressure
        ):
            return RiskProbeResult(True, "escaped_skip_stall", None)
        return RiskProbeResult(False, None, "food_rescue_gate_failed")
    if trigger == SEARCH_INTERVENTION_CONNECT:
        if selected_after.network_count < greedy_after.network_count:
            return RiskProbeResult(True, "reduced_network_count", None)
        if selected_after.isolated_city_count < greedy_after.isolated_city_count:
            return RiskProbeResult(True, "reduced_isolated_city_count", None)
        if selected_after.connected_city_count > greedy_after.connected_city_count:
            return RiskProbeResult(True, "increased_connected_city_count", None)
        return RiskProbeResult(False, None, "connect_gate_failed")
    if trigger == SEARCH_INTERVENTION_STALL:
        risk_not_worse = (
            selected_after.starving_network_count <= greedy_after.starving_network_count
            and selected_after.food_pressure <= greedy_after.food_pressure
            and selected_after.network_count
            <= max(greedy_after.network_count, root_risk.network_count)
            and selected_after.isolated_city_count
            <= max(greedy_after.isolated_city_count, root_risk.isolated_city_count)
        )
        if selected_after.score_total >= greedy_after.score_total and risk_not_worse:
            return RiskProbeResult(True, "stall_score_not_worse", None)
        return RiskProbeResult(False, None, "stall_gate_failed")
    return RiskProbeResult(False, None, "unknown_probe")


def _evaluate_bridge_probe_result(
    *,
    root_risk: RiskProfile,
    greedy_action: Action,
    selected_action: Action,
    greedy_after: RiskProfile,
    selected_sequence_after: RiskProfile,
) -> RiskProbeResult | None:
    if selected_action == greedy_action:
        return None
    if selected_sequence_after.starving_network_count > root_risk.starving_network_count:
        return RiskProbeResult(False, None, "bridge_sequence_gate_failed")
    if selected_sequence_after.network_count > root_risk.network_count:
        return RiskProbeResult(False, None, "bridge_sequence_gate_failed")
    if selected_sequence_after.isolated_city_count > root_risk.isolated_city_count:
        return RiskProbeResult(False, None, "bridge_sequence_gate_failed")
    if selected_sequence_after.starving_network_count < greedy_after.starving_network_count:
        return RiskProbeResult(True, "bridge_sequence_reduced_starving_networks", None)
    if selected_sequence_after.starving_network_count < root_risk.starving_network_count:
        return RiskProbeResult(True, "bridge_sequence_reduced_starving_networks", None)
    if selected_sequence_after.network_count < greedy_after.network_count:
        return RiskProbeResult(True, "bridge_sequence_reduced_networks", None)
    if selected_sequence_after.network_count < root_risk.network_count:
        return RiskProbeResult(True, "bridge_sequence_reduced_networks", None)
    if selected_sequence_after.isolated_city_count < greedy_after.isolated_city_count:
        return RiskProbeResult(True, "bridge_sequence_reduced_networks", None)
    if selected_sequence_after.isolated_city_count < root_risk.isolated_city_count:
        return RiskProbeResult(True, "bridge_sequence_reduced_networks", None)
    if selected_sequence_after.connected_city_count > greedy_after.connected_city_count:
        return RiskProbeResult(True, "bridge_sequence_increased_connected_cities", None)
    if selected_sequence_after.connected_city_count > root_risk.connected_city_count:
        return RiskProbeResult(True, "bridge_sequence_increased_connected_cities", None)
    return RiskProbeResult(False, None, "bridge_sequence_gate_failed")


def _evaluate_committed_route_probe_result(
    *,
    state: GameState,
    simulation_cache: SimulationCache | None = None,
    root_risk: RiskProfile,
    greedy_action: Action,
    selected_action: Action,
    greedy_after: RiskProfile,
    selected_after: RiskProfile,
) -> RiskProbeResult | None:
    if selected_action == greedy_action:
        return None
    bridge_path = (
        simulation_cache.bridge_path_for_first_action(state, selected_action)
        if simulation_cache is not None
        else _bridge_path_for_first_action(state, selected_action)
    )
    if bridge_path is None or bridge_path.progress_after_first_step <= 0:
        return None
    if selected_after.starving_network_count > root_risk.starving_network_count:
        return RiskProbeResult(False, None, "committed_route_gate_failed")
    if selected_after.food_pressure > root_risk.food_pressure + FOOD_CONSUMPTION_PER_CITY:
        return RiskProbeResult(False, None, "committed_route_gate_failed")
    if selected_after.network_count > root_risk.network_count:
        return RiskProbeResult(False, None, "committed_route_gate_failed")
    if (
        selected_after.score_total >= greedy_after.score_total
        or selected_after.food_pressure <= greedy_after.food_pressure
        or selected_after.network_count <= greedy_after.network_count
        or bridge_path.min_steps > 3
    ):
        return RiskProbeResult(True, "committed_route_progress", None)
    return RiskProbeResult(False, None, "committed_route_gate_failed")


def _evaluate_greedy_veto_probe_result(
    *,
    state: GameState,
    simulation_cache: SimulationCache | None = None,
    veto_reason: str | None,
    root_risk: RiskProfile,
    greedy_action: Action,
    selected_action: Action,
    greedy_after: RiskProfile,
    selected_after: RiskProfile,
) -> RiskProbeResult | None:
    if veto_reason is None or selected_action == greedy_action:
        return None
    if selected_action.action_type is ActionType.SKIP:
        return RiskProbeResult(False, None, "greedy_veto_gate_failed")
    if selected_after.starving_network_count > root_risk.starving_network_count:
        return RiskProbeResult(False, None, "greedy_veto_gate_failed")
    if selected_after.food_pressure > max(root_risk.food_pressure, greedy_after.food_pressure):
        return RiskProbeResult(False, None, "greedy_veto_gate_failed")
    bridge_path = (
        simulation_cache.bridge_path_for_first_action(state, selected_action)
        if simulation_cache is not None
        else _bridge_path_for_first_action(state, selected_action)
    )
    if bridge_path is not None:
        return RiskProbeResult(True, "greedy_veto_committed_route", None)
    if selected_after.network_count < greedy_after.network_count:
        return RiskProbeResult(True, "greedy_veto_reduced_networks", None)
    if selected_after.connected_city_count > greedy_after.connected_city_count:
        return RiskProbeResult(True, "greedy_veto_increased_connected_cities", None)
    if selected_after.score_total >= greedy_after.score_total:
        return RiskProbeResult(True, "greedy_veto_score_not_worse", None)
    if selected_after.food_pressure < greedy_after.food_pressure:
        return RiskProbeResult(True, "greedy_veto_food_not_worse", None)
    return RiskProbeResult(False, None, "greedy_veto_gate_failed")


def _generate_risk_search_candidates(
    greedy_policy: GreedyPolicy,
    state: GameState,
    trigger: str,
    candidate_limit: int,
    simulation_cache: SimulationCache,
    *,
    blocked_action: Action | None = None,
) -> SearchCandidateSet:
    greedy_plan = simulation_cache.greedy_plan(greedy_policy, state)
    profile = simulation_cache.profile(state)
    context = simulation_cache.heuristic_context(state)
    legal_actions = simulation_cache.legal_actions(state)
    legal_set = set(legal_actions)
    legal_counts = {
        action_type: sum(1 for action in legal_actions if action.action_type is action_type)
        for action_type in ActionType
    }

    candidate_actions = _risk_candidate_actions(
        state=state,
        trigger=trigger,
        candidate_limit=candidate_limit,
        greedy_plan=greedy_plan,
        legal_actions=legal_actions,
        context=context,
        profile=profile,
        simulation_cache=simulation_cache,
        blocked_action=blocked_action,
    )
    candidates = [
        _risk_search_candidate(
            state,
            action,
            trigger,
            context,
            simulation_cache=simulation_cache,
        )
        for action in candidate_actions
        if action in legal_set
    ][:candidate_limit]
    bridge_paths = list(simulation_cache.bridge_paths(state))
    bridge_by_first_action = {path.actions[0]: path for path in bridge_paths}
    candidate_counts = {
        action_type: sum(1 for candidate in candidates if candidate.action_type is action_type)
        for action_type in ActionType
    }
    safe_city_count = sum(
        1
        for candidate in candidates
        if candidate.action.action_type is ActionType.BUILD_CITY
        and candidate.action.coord is not None
        and _risk_action_improves_food(state, candidate.action, simulation_cache=simulation_cache)
    )
    connection_road_count = sum(
        1
        for candidate in candidates
        if candidate.action.action_type is ActionType.BUILD_ROAD
        and (
            candidate.action in bridge_by_first_action
            or _risk_action_improves_connection(
                state,
                candidate.action,
                simulation_cache=simulation_cache,
            )
        )
    )
    rescue_count = sum(
        1
        for candidate in candidates
        if _risk_action_improves_food(
            state,
            candidate.action,
            simulation_cache=simulation_cache,
        )
    )
    return SearchCandidateSet(
        candidates=candidates,
        legal_action_count=len(legal_actions),
        legal_counts_by_type=legal_counts,
        candidate_counts_by_type=candidate_counts,
        profile=profile,
        safe_city_candidate_count=safe_city_count,
        effective_connection_road_candidate_count=connection_road_count,
        rescue_candidate_count=rescue_count,
        effective_city_candidate_count=safe_city_count,
        redundant_road_candidate_count=0,
        high_roi_building_candidate_count=sum(
            1
            for candidate in candidates
            if candidate.action.action_type is ActionType.BUILD_BUILDING
        ),
        gated_candidate_count=max(0, len(legal_actions) - len(candidates)),
    )


def _risk_candidate_actions(
    *,
    state: GameState,
    trigger: str,
    candidate_limit: int,
    greedy_plan: GreedyPlanSnapshot,
    legal_actions: list[Action],
    context: HeuristicContext,
    profile: SearchPositionProfile,
    simulation_cache: SimulationCache,
    blocked_action: Action | None = None,
) -> list[Action]:
    candidates: list[Action] = [] if greedy_plan.action == blocked_action else [greedy_plan.action]
    greedy_quota = max(2, candidate_limit // 3)
    candidates.extend(greedy_plan.selected_candidates[:greedy_quota])
    candidates.extend(greedy_plan.escape_candidates[:greedy_quota])
    candidates.extend(greedy_plan.candidates[:greedy_quota])
    groups = partition_actions(legal_actions)
    bridge_paths = list(simulation_cache.bridge_paths(state))
    bridge_actions = [path.actions[0] for path in bridge_paths]
    supplemental_actions = _supplemental_risk_actions(
        state,
        groups,
        context,
        trigger=trigger,
        limit=max(candidate_limit, 4),
    )
    supplemental_actions = _dedupe_ordered_actions([*bridge_actions, *supplemental_actions])

    if trigger == SEARCH_INTERVENTION_FOOD_RESCUE:
        bridge_quota = _bridge_candidate_quota(candidate_limit, bridge_actions)
        candidates.extend(
            sorted(
                bridge_actions,
                key=lambda action: _risk_action_sort_key(
                    state,
                    action,
                    trigger,
                    context,
                    profile,
                    simulation_cache,
                ),
            )[:bridge_quota]
        )
        candidates.extend(
            sorted(
                (
                    action
                    for action in supplemental_actions
                    if _risk_action_improves_food(
                        state,
                        action,
                        simulation_cache=simulation_cache,
                    )
                    or _risk_action_improves_connection(
                        state,
                        action,
                        simulation_cache=simulation_cache,
                    )
                    or action in bridge_actions
                ),
                key=lambda action: _risk_action_sort_key(
                    state,
                    action,
                    trigger,
                    context,
                    profile,
                    simulation_cache,
                ),
            )[:candidate_limit]
        )
    elif trigger == SEARCH_INTERVENTION_CONNECT:
        bridge_quota = _bridge_candidate_quota(candidate_limit, bridge_actions)
        candidates.extend(
            sorted(
                bridge_actions,
                key=lambda action: _risk_action_sort_key(
                    state,
                    action,
                    trigger,
                    context,
                    profile,
                    simulation_cache,
                ),
            )[:bridge_quota]
        )
        candidates.extend(
            sorted(
                (
                    action
                    for action in supplemental_actions
                    if _risk_action_improves_connection(
                        state,
                        action,
                        simulation_cache=simulation_cache,
                    )
                    or action in bridge_actions
                ),
                key=lambda action: _risk_action_sort_key(
                    state,
                    action,
                    trigger,
                    context,
                    profile,
                    simulation_cache,
                ),
            )[:candidate_limit]
        )
    elif trigger == SEARCH_INTERVENTION_STALL:
        bridge_quota = _bridge_candidate_quota(candidate_limit, bridge_actions)
        candidates.extend(
            sorted(
                bridge_actions,
                key=lambda action: _risk_action_sort_key(
                    state,
                    action,
                    trigger,
                    context,
                    profile,
                    simulation_cache,
                ),
            )[:bridge_quota]
        )
        candidates.extend(
            sorted(
                (
                    action
                    for action in supplemental_actions
                    if action.action_type is not ActionType.SKIP
                    and (
                        _risk_action_score_delta(
                            state,
                            action,
                            simulation_cache=simulation_cache,
                        )
                        >= 0
                        or _risk_action_improves_food(
                            state,
                            action,
                            simulation_cache=simulation_cache,
                        )
                        or _risk_action_improves_connection(
                            state,
                            action,
                            simulation_cache=simulation_cache,
                        )
                        or action in bridge_actions
                    )
                ),
                key=lambda action: _risk_action_sort_key(
                    state,
                    action,
                    trigger,
                    context,
                    profile,
                    simulation_cache,
                ),
            )[:candidate_limit]
        )

    deduped = _dedupe_ordered_actions(candidates)
    if blocked_action is not None:
        deduped = [action for action in deduped if action != blocked_action]
    return deduped[:candidate_limit]


def _bridge_candidate_quota(candidate_limit: int, bridge_actions: list[Action]) -> int:
    if not bridge_actions:
        return 0
    return min(len(bridge_actions), max(1, min(3, candidate_limit // 3)))


def _supplemental_risk_actions(
    state: GameState,
    groups: dict[ActionType, list[Action]],
    context: HeuristicContext,
    *,
    trigger: str,
    limit: int,
) -> list[Action]:
    actions: list[Action] = []
    if trigger in {SEARCH_INTERVENTION_FOOD_RESCUE, SEARCH_INTERVENTION_STALL}:
        food_cities = [
            action
            for action in groups.get(ActionType.BUILD_CITY, [])
            if action.coord is not None
            and _city_anchor_quality(state, action.coord, context)["food_balance"] >= 1
        ]
        actions.extend(
            sorted(
                food_cities,
                key=lambda action: (
                    -_city_anchor_quality(state, _required_coord(action), context)["food_balance"],
                    -resource_ring_bonus_for_context(context, _required_coord(action)),
                    _action_sort_key(action),
                ),
            )[:3]
        )
        farm_actions = [
            action
            for action in groups.get(ActionType.BUILD_BUILDING, [])
            if action.building_type is BuildingType.FARM
        ]
        actions.extend(
            sorted(farm_actions, key=lambda action: -building_action_score(state, action))[:3]
        )
        agriculture_actions = [
            action
            for action in groups.get(ActionType.RESEARCH_TECH, [])
            if action.tech_type is TechType.AGRICULTURE
        ]
        actions.extend(
            sorted(
                agriculture_actions,
                key=lambda action: -research_action_score(state, action),
            )[:2]
        )

    if trigger in {
        SEARCH_INTERVENTION_FOOD_RESCUE,
        SEARCH_INTERVENTION_CONNECT,
        SEARCH_INTERVENTION_STALL,
    }:
        road_actions = [
            action for action in groups.get(ActionType.BUILD_ROAD, []) if action.coord is not None
        ]
        actions.extend(
            sorted(
                road_actions,
                key=lambda action: (
                    -road_site_score_for_context(context, _required_coord(action)),
                    _action_sort_key(action),
                ),
            )[:4]
        )

    return _dedupe_ordered_actions(actions)[:limit]


def _risk_search_candidate(
    state: GameState,
    action: Action,
    trigger: str,
    context: HeuristicContext,
    *,
    simulation_cache: SimulationCache | None = None,
) -> SearchCandidate:
    improvement = _risk_action_improvement_score(
        state,
        action,
        simulation_cache=simulation_cache,
    )
    bridge_path = (
        simulation_cache.bridge_path_for_first_action(state, action)
        if simulation_cache is not None
        else _bridge_path_for_first_action(state, action)
    )
    bridge_bonus = 0
    if bridge_path is not None:
        bridge_bonus = 18 + bridge_path.progress_after_first_step * 6
    rank_score = improvement * 1_000
    if action.action_type is ActionType.BUILD_CITY and action.coord is not None:
        quality = _city_anchor_quality(state, action.coord, context)
        rank_score += quality["ring_bonus"] * 3 + quality["site_score"]
    elif (
        action.action_type is ActionType.BUILD_BUILDING
        and action.building_type is BuildingType.FARM
    ):
        rank_score += 900
    elif (
        action.action_type is ActionType.RESEARCH_TECH and action.tech_type is TechType.AGRICULTURE
    ):
        rank_score += 700
    elif action.action_type is ActionType.BUILD_ROAD:
        rank_score += 800 + (bridge_bonus * 1_000)
    if action.action_type is ActionType.SKIP:
        rank_score -= 10_000
    return SearchCandidate(
        action=action,
        action_type=action.action_type,
        rank_score=rank_score,
        reason="bridge_path_progress" if bridge_path is not None else trigger,
        effective=improvement > 0 or bridge_path is not None,
        risk=False,
    )


def _risk_action_sort_key(
    state: GameState,
    action: Action,
    trigger: str,
    context: HeuristicContext,
    profile: SearchPositionProfile,
    simulation_cache: SimulationCache,
) -> tuple[int, tuple[int, tuple[int, int], int, int, int]]:
    del trigger, profile
    rank = _risk_search_candidate(
        state,
        action,
        SEARCH_INTERVENTION_NONE,
        context,
        simulation_cache=simulation_cache,
    ).rank_score
    return (-rank, _action_sort_key(action))


def _risk_action_improvement_score(
    state: GameState,
    action: Action,
    *,
    simulation_cache: SimulationCache | None = None,
) -> int:
    bridge_path = (
        simulation_cache.bridge_path_for_first_action(state, action)
        if simulation_cache is not None
        else _bridge_path_for_first_action(state, action)
    )
    if bridge_path is not None:
        return 18 + bridge_path.progress_after_first_step * 6
    before = (
        simulation_cache.risk_profile(state)
        if simulation_cache is not None
        else _risk_profile(state)
    )
    try:
        simulated = (
            simulation_cache.simulate(state, action)
            if simulation_cache is not None
            else simulate_action(state, action)
        )
        after = (
            simulation_cache.risk_profile(simulated)
            if simulation_cache is not None
            else _risk_profile(simulated)
        )
    except ValueError:
        return -10_000
    return (
        max(0, before.starving_network_count - after.starving_network_count) * 12
        + max(0, before.food_pressure - after.food_pressure)
        + max(0, before.network_count - after.network_count) * 8
        + max(0, before.isolated_city_count - after.isolated_city_count) * 8
        + max(0, after.connected_city_count - before.connected_city_count) * 6
        + max(0, after.score_total - before.score_total) // 20
    )


def _risk_action_score_delta(
    state: GameState,
    action: Action,
    *,
    simulation_cache: SimulationCache | None = None,
) -> int:
    before = (
        simulation_cache.risk_profile(state)
        if simulation_cache is not None
        else _risk_profile(state)
    )
    try:
        simulated = (
            simulation_cache.simulate(state, action)
            if simulation_cache is not None
            else simulate_action(state, action)
        )
        after = (
            simulation_cache.risk_profile(simulated)
            if simulation_cache is not None
            else _risk_profile(simulated)
        )
    except ValueError:
        return -10_000
    return after.score_total - before.score_total


def _best_veto_fallback_action(
    *,
    state: GameState,
    greedy_action: Action,
    veto_reason: str | None,
    simulation_cache: SimulationCache,
) -> Action | None:
    if veto_reason is None:
        return None
    context = simulation_cache.heuristic_context(state)
    profile = simulation_cache.profile(state)
    scored: list[tuple[int, Action]] = []
    for action in simulation_cache.legal_actions(state):
        if action == greedy_action or action.action_type is ActionType.SKIP:
            continue
        if not _action_is_valid_veto_fallback(
            state,
            action,
            context=context,
            profile=profile,
            simulation_cache=simulation_cache,
        ):
            continue
        try:
            simulated = simulation_cache.simulate(state, action)
        except ValueError:
            continue
        evaluation = simulation_cache.leaf_evaluation(simulated, root_state=state)
        scored.append(
            (
                evaluation.value
                + _veto_fallback_bonus(
                    state,
                    action,
                    context,
                    veto_reason=veto_reason,
                    simulation_cache=simulation_cache,
                ),
                action,
            )
        )
    if not scored:
        return None
    return sorted(scored, key=lambda item: (-item[0], _action_sort_key(item[1])))[0][1]


def _action_is_valid_veto_fallback(
    state: GameState,
    action: Action,
    *,
    context: HeuristicContext,
    profile: SearchPositionProfile,
    simulation_cache: SimulationCache,
) -> bool:
    if action.action_type is ActionType.BUILD_ROAD and action.coord is not None:
        if simulation_cache.bridge_path_for_first_action(state, action) is not None:
            return True
        delta = _action_delta_diagnostics(state, action, simulation_cache=simulation_cache)
        return (
            bool(delta["search_road_merges_networks"])
            or int(delta["search_delta_connected_city_count"]) > 0
            or int(delta["search_delta_network_count"]) < 0
        )
    if action.action_type is ActionType.BUILD_CITY and action.coord is not None:
        budget = site_budget(state, action.coord, context)
        return budget.food_balance >= 1 or _city_can_stabilize_food(state, action.coord, context)
    if action.action_type is ActionType.BUILD_BUILDING:
        return _is_rescue_fill_action(state, action, simulation_cache=simulation_cache)
    if action.action_type is ActionType.RESEARCH_TECH:
        return _is_rescue_fill_action(state, action, simulation_cache=simulation_cache)
    return profile.turns_remaining <= 1


def _veto_fallback_bonus(
    state: GameState,
    action: Action,
    context: HeuristicContext,
    *,
    veto_reason: str,
    simulation_cache: SimulationCache | None = None,
) -> int:
    bridge_path = (
        simulation_cache.bridge_path_for_first_action(state, action)
        if simulation_cache is not None
        else _bridge_path_for_first_action(state, action)
    )
    if action.action_type is ActionType.BUILD_ROAD and bridge_path is not None:
        if veto_reason.startswith(("road_", "route_")):
            return 1_000_000
        return 80_000
    if action.action_type is ActionType.BUILD_CITY and action.coord is not None:
        budget = site_budget(state, action.coord, context)
        ring_bonus = resource_ring_bonus_for_context(context, action.coord)
        city_bonus = (budget.food_balance * 4_000) + (ring_bonus * 20)
        if veto_reason.startswith(("road_", "route_")):
            return min(city_bonus, 0)
        return city_bonus
    if (
        action.action_type is ActionType.BUILD_BUILDING
        and action.building_type is BuildingType.FARM
    ):
        return 12_000
    if action.action_type is ActionType.RESEARCH_TECH and action.tech_type is TechType.AGRICULTURE:
        return 10_000
    return 0


def _city_can_stabilize_food(
    state: GameState,
    coord: Coord,
    context: HeuristicContext,
) -> bool:
    budget = site_budget(state, coord, context)
    _forest, _mountain, river, plain, _occupied = resource_ring_counts_for_context(context, coord)
    return budget.food_balance >= 0 and (
        plain > 0 or river > 0 or context_is_river_adjacent_site(context, coord)
    )


def _is_rescue_fill_action(
    state: GameState,
    action: Action,
    *,
    simulation_cache: SimulationCache | None = None,
) -> bool:
    if action.action_type is ActionType.BUILD_BUILDING:
        return (
            action.building_type is BuildingType.FARM
            or _risk_action_score_delta(state, action, simulation_cache=simulation_cache) >= 0
        )
    if action.action_type is ActionType.RESEARCH_TECH:
        return (
            action.tech_type is TechType.AGRICULTURE
            or _risk_action_score_delta(state, action, simulation_cache=simulation_cache) >= 0
        )
    return False


def _risk_action_improves_food(
    state: GameState,
    action: Action,
    *,
    simulation_cache: SimulationCache | None = None,
) -> bool:
    before = (
        simulation_cache.risk_profile(state)
        if simulation_cache is not None
        else _risk_profile(state)
    )
    try:
        simulated = (
            simulation_cache.simulate(state, action)
            if simulation_cache is not None
            else simulate_action(state, action)
        )
        after = (
            simulation_cache.risk_profile(simulated)
            if simulation_cache is not None
            else _risk_profile(simulated)
        )
    except ValueError:
        return False
    return (
        after.starving_network_count < before.starving_network_count
        or after.food_pressure < before.food_pressure
        or after.min_network_food > before.min_network_food
    )


def _risk_action_improves_connection(
    state: GameState,
    action: Action,
    *,
    simulation_cache: SimulationCache | None = None,
) -> bool:
    before = (
        simulation_cache.risk_profile(state)
        if simulation_cache is not None
        else _risk_profile(state)
    )
    try:
        simulated = (
            simulation_cache.simulate(state, action)
            if simulation_cache is not None
            else simulate_action(state, action)
        )
        after = (
            simulation_cache.risk_profile(simulated)
            if simulation_cache is not None
            else _risk_profile(simulated)
        )
    except ValueError:
        return False
    return (
        after.network_count < before.network_count
        or after.isolated_city_count < before.isolated_city_count
        or after.connected_city_count > before.connected_city_count
    )


def _sequence_bridge_diagnostics(
    previous: BridgeDiagnostics,
    state: GameState,
    action: Action,
    *,
    simulation_cache: SimulationCache | None = None,
) -> BridgeDiagnostics:
    bridge_path = (
        simulation_cache.bridge_path_for_first_action(state, action)
        if simulation_cache is not None
        else _bridge_path_for_first_action(state, action)
    )
    if bridge_path is None:
        return previous
    return BridgeDiagnostics(
        candidate_count=previous.candidate_count + 1,
        min_steps=_min_optional_int(previous.min_steps, bridge_path.min_steps),
        progress_after_first_step=max(
            previous.progress_after_first_step,
            bridge_path.progress_after_first_step,
        ),
    )


def _min_optional_int(first: int | None, second: int) -> int:
    return second if first is None else min(first, second)


def _dedupe_ordered_actions(actions: list[Action]) -> list[Action]:
    result: list[Action] = []
    seen: set[Action] = set()
    for action in actions:
        if action in seen:
            continue
        result.append(action)
        seen.add(action)
    return result


def _bridge_paths_for_state(
    state: GameState,
    *,
    legal_actions: list[Action] | None = None,
    simulation_cache: SimulationCache | None = None,
) -> list[BridgePath]:
    if len(state.networks) < 2:
        return []
    legal_actions = (
        legal_actions
        if legal_actions is not None
        else (
            simulation_cache.legal_actions(state)
            if simulation_cache is not None
            else get_legal_actions(state)
        )
    )
    legal_roads = [
        action
        for action in legal_actions
        if action.action_type is ActionType.BUILD_ROAD and action.coord is not None
    ]
    if not legal_roads:
        return []
    legal_road_coords = {action.coord for action in legal_roads if action.coord is not None}
    buildable_road_coords = _bridge_buildable_road_coords(state)
    risk_network_ids = _bridge_risk_network_ids(state)
    target_network_ids = _bridge_target_network_ids(state, risk_network_ids)
    if not risk_network_ids or not target_network_ids:
        return []

    passable_map = _component_passable_map_by_network(state)
    paths_by_first_action: dict[Action, BridgePath] = {}
    current_connected_pairs: set[tuple[int, int]] = set()
    max_steps = _bridge_max_steps_for_state(state)
    for source_id in sorted(risk_network_ids):
        source_coords = _network_frontier_coords(passable_map, source_id)
        if not source_coords:
            continue
        for target_id in sorted(target_network_ids):
            if target_id == source_id:
                continue
            pair_key = (min(source_id, target_id), max(source_id, target_id))
            if pair_key in current_connected_pairs:
                continue
            target_coords = _network_frontier_coords(passable_map, target_id)
            if not target_coords:
                continue
            blocked_coords = {
                coord
                for coord, network_id in passable_map.items()
                if network_id not in {source_id, target_id}
            }
            coord_path = _short_bridge_path(
                state,
                source_coords=source_coords,
                target_coords=target_coords,
                legal_road_coords=legal_road_coords,
                buildable_road_coords=buildable_road_coords,
                blocked_coords=blocked_coords,
                max_steps=max_steps,
            )
            if coord_path is None:
                if _networks_are_touching(source_coords, target_coords):
                    current_connected_pairs.add(pair_key)
                continue
            actions = tuple(Action.build_road(coord) for coord in coord_path)
            if not actions:
                continue
            first_action = actions[0]
            progress = _bridge_progress_after_first_step(
                state,
                first_action,
                source_network_id=source_id,
                target_network_id=target_id,
                max_steps=max_steps,
                simulation_cache=simulation_cache,
                before_passable_map=passable_map,
                before_legal_road_coords=legal_road_coords,
                before_buildable_road_coords=buildable_road_coords,
            )
            path = BridgePath(
                actions=actions,
                source_network_id=source_id,
                target_network_id=target_id,
                progress_after_first_step=progress,
            )
            if progress <= 0 and path.min_steps > 1:
                continue
            previous = paths_by_first_action.get(first_action)
            if previous is None or _bridge_path_sort_key(path) < _bridge_path_sort_key(previous):
                paths_by_first_action[first_action] = path
    return sorted(paths_by_first_action.values(), key=_bridge_path_sort_key)


def _bridge_max_steps_for_state(state: GameState) -> int:
    map_budget = max(3, state.config.map_size // 3 + 2)
    turn_budget = max(3, _turns_remaining(state) - 1)
    return min(8, map_budget, turn_budget)


def _bridge_risk_network_ids(state: GameState) -> set[int]:
    if len(state.networks) < 2:
        return set()
    return {
        network_id
        for network_id, network in state.networks.items()
        if _network_needs_food(network) or len(network.city_ids) == 1
    }


def _component_passable_map_by_network(state: GameState) -> dict[Coord, int]:
    coord_to_city_id = {city.coord: city_id for city_id, city in state.cities.items()}
    mapping: dict[Coord, int] = {}
    seen: set[Coord] = set()
    for city_coord, city_id in sorted(coord_to_city_id.items()):
        if city_coord in seen:
            continue
        network_id = state.cities[city_id].network_id
        queue = deque([city_coord])
        seen.add(city_coord)
        while queue:
            current = queue.popleft()
            mapping[current] = network_id
            current_is_city = current in coord_to_city_id
            for neighbor in cardinal_neighbors(current):
                if neighbor in seen:
                    continue
                tile = state.board.get(neighbor)
                if tile is None:
                    continue
                if not _is_bridge_passable_tile(state, neighbor):
                    continue
                if current_is_city and neighbor in coord_to_city_id:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
    return mapping


def _is_bridge_passable_tile(state: GameState, coord: Coord) -> bool:
    tile = state.board.get(coord)
    if tile is None:
        return False
    return tile.occupant.value in {"city", "road"} or tile.base_terrain.value == "river"


def _bridge_target_network_ids(state: GameState, risk_network_ids: set[int]) -> set[int]:
    del risk_network_ids
    targets = {
        network_id
        for network_id, network in state.networks.items()
        if _network_has_food_buffer(network)
    }
    if targets:
        return targets
    return {
        network_id
        for network_id, network in state.networks.items()
        if not _network_needs_food(network)
    }


def _bridge_buildable_road_coords(state: GameState) -> set[Coord]:
    return {coord for coord, tile in state.board.items() if tile.occupant.value == "none"}


def _network_needs_food(network: Network) -> bool:
    return (
        network.resources.food <= 0 or city_network_pressure(network) >= FOOD_CONSUMPTION_PER_CITY
    )


def _network_has_food_buffer(network: Network) -> bool:
    return (
        network.resources.food >= max(1, len(network.city_ids)) * FOOD_CONSUMPTION_PER_CITY * 3
        or city_network_pressure(network) < 0
    )


def _network_frontier_coords(passable_map: dict[Coord, int], network_id: int) -> set[Coord]:
    return {
        coord
        for coord, mapped_network_id in passable_map.items()
        if mapped_network_id == network_id
    }


def _networks_are_touching(first: set[Coord], second: set[Coord]) -> bool:
    return any(neighbor in second for coord in first for neighbor in cardinal_neighbors(coord))


def _short_bridge_path(
    state: GameState,
    *,
    source_coords: set[Coord],
    target_coords: set[Coord],
    legal_road_coords: set[Coord],
    buildable_road_coords: set[Coord],
    blocked_coords: set[Coord],
    max_steps: int,
) -> tuple[Coord, ...] | None:
    del state
    queue: list[tuple[int, Coord, tuple[Coord, ...]]] = []
    best_seen: dict[Coord, int] = {}
    for coord in sorted(source_coords):
        heappush(queue, (0, coord, ()))
        best_seen[coord] = 0

    while queue:
        steps, coord, path = heappop(queue)
        if steps > max_steps:
            continue
        if coord in target_coords and path:
            return path
        if steps == max_steps:
            continue
        for neighbor in sorted(cardinal_neighbors(coord)):
            if neighbor in target_coords:
                if path:
                    return path
                continue
            if neighbor in source_coords:
                continue
            if neighbor in blocked_coords:
                continue
            if not path and neighbor not in legal_road_coords:
                continue
            if neighbor not in buildable_road_coords:
                continue
            next_steps = steps + 1
            previous_steps = best_seen.get(neighbor)
            if previous_steps is not None and previous_steps <= next_steps:
                continue
            best_seen[neighbor] = next_steps
            heappush(queue, (next_steps, neighbor, (*path, neighbor)))
    return None


def _bridge_progress_after_first_step(
    state: GameState,
    action: Action,
    *,
    source_network_id: int,
    target_network_id: int,
    max_steps: int,
    simulation_cache: SimulationCache | None = None,
    before_passable_map: dict[Coord, int] | None = None,
    before_legal_road_coords: set[Coord] | None = None,
    before_buildable_road_coords: set[Coord] | None = None,
) -> int:
    before = _network_bridge_steps(
        state,
        source_network_id=source_network_id,
        target_network_id=target_network_id,
        max_steps=max_steps,
        simulation_cache=simulation_cache,
        passable_map=before_passable_map,
        legal_road_coords=before_legal_road_coords,
        buildable_road_coords=before_buildable_road_coords,
    )
    try:
        after_state = (
            simulation_cache.simulate(state, action)
            if simulation_cache is not None
            else simulate_action(state, action)
        )
    except ValueError:
        return 0
    after = _network_bridge_steps(
        after_state,
        source_network_id=source_network_id,
        target_network_id=target_network_id,
        max_steps=max_steps,
        simulation_cache=simulation_cache,
    )
    if before is None or after is None:
        return 0
    return max(0, before - after)


def _network_bridge_steps(
    state: GameState,
    *,
    source_network_id: int,
    target_network_id: int,
    max_steps: int,
    simulation_cache: SimulationCache | None = None,
    passable_map: dict[Coord, int] | None = None,
    legal_road_coords: set[Coord] | None = None,
    buildable_road_coords: set[Coord] | None = None,
) -> int | None:
    passable_map = (
        _component_passable_map_by_network(state) if passable_map is None else passable_map
    )
    source_coords = _network_frontier_coords(passable_map, source_network_id)
    target_coords = _network_frontier_coords(passable_map, target_network_id)
    if not source_coords or not target_coords:
        return None
    if legal_road_coords is None:
        legal_actions = (
            simulation_cache.legal_actions(state)
            if simulation_cache is not None
            else get_legal_actions(state)
        )
        legal_road_coords = {
            action.coord
            for action in legal_actions
            if action.action_type is ActionType.BUILD_ROAD and action.coord is not None
        }
    blocked_coords = {
        coord
        for coord, network_id in passable_map.items()
        if network_id not in {source_network_id, target_network_id}
    }
    path = _short_bridge_path(
        state,
        source_coords=source_coords,
        target_coords=target_coords,
        legal_road_coords=legal_road_coords,
        buildable_road_coords=buildable_road_coords
        if buildable_road_coords is not None
        else _bridge_buildable_road_coords(state),
        blocked_coords=blocked_coords,
        max_steps=max_steps,
    )
    return len(path) if path is not None else None


def _bridge_path_for_first_action(state: GameState, action: Action) -> BridgePath | None:
    if action.action_type is not ActionType.BUILD_ROAD or action.coord is None:
        return None
    for path in _bridge_paths_for_state(state):
        if path.actions and path.actions[0] == action:
            return path
    return None


def _bridge_path_sort_key(path: BridgePath) -> tuple[int, int, int, tuple[int, int]]:
    first_coord = path.actions[0].coord if path.actions[0].coord is not None else (10**9, 10**9)
    return (
        path.min_steps,
        -path.progress_after_first_step,
        path.source_network_id,
        first_coord,
    )


def _required_coord(action: Action) -> Coord:
    assert action.coord is not None
    return action.coord


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
        "search_root_chosen_rank": None,
        "search_root_chosen_value": None,
        "search_root_best_value": None,
        "search_root_value_margin": None,
        "search_root_best_action_type": None,
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


def _action_delta_diagnostics(
    state: GameState,
    action: Action,
    *,
    simulation_cache: SimulationCache | None = None,
) -> dict[str, object]:
    before = (
        simulation_cache.profile(state)
        if simulation_cache is not None
        else build_search_position_profile(state)
    )
    before_risk = (
        simulation_cache.network_food_risk(state)
        if simulation_cache is not None
        else _network_food_risk_profile(state)
    )
    after_state = (
        simulation_cache.simulate(state, action)
        if simulation_cache is not None
        else simulate_action(state, action)
    )
    after = (
        simulation_cache.profile(after_state)
        if simulation_cache is not None
        else build_search_position_profile(after_state)
    )
    after_risk = (
        simulation_cache.network_food_risk(after_state)
        if simulation_cache is not None
        else _network_food_risk_profile(after_state)
    )
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
    city_capacity = _city_capacity_after_action(after_state, action)
    city_plain_capacity = _city_local_plain_capacity(state, action)
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
        "search_city_food_capacity_after_action": city_capacity,
        "search_city_local_plain_capacity": city_plain_capacity,
        **_network_food_risk_diagnostics(after_state, simulation_cache=simulation_cache),
    }


def _city_capacity_after_action(after_state: GameState, action: Action) -> int | None:
    if action.action_type is not ActionType.BUILD_CITY or action.coord is None:
        return None
    for city in after_state.cities.values():
        if city.coord == action.coord:
            return after_state.networks[city.network_id].resources.food
    return None


def _city_local_plain_capacity(state: GameState, action: Action) -> int | None:
    if action.action_type is not ActionType.BUILD_CITY or action.coord is None:
        return None
    context = build_heuristic_context(state)
    _forest, _mountain, river, plain, _occupied = resource_ring_counts_for_context(
        context,
        action.coord,
    )
    center_plain = 1 if state.board[action.coord].base_terrain.value == "plain" else 0
    return center_plain + plain + river


def _route_diagnostics(
    state: GameState,
    action: Action,
    *,
    simulation_cache: SimulationCache | None = None,
) -> dict[str, object]:
    bridge_path = (
        simulation_cache.bridge_path_for_first_action(state, action)
        if simulation_cache is not None
        else _bridge_path_for_first_action(state, action)
    )
    if bridge_path is None:
        return {
            "search_route_target_network_id": None,
            "search_route_remaining_steps": None,
            "search_route_committed": False,
        }
    return {
        "search_route_target_network_id": bridge_path.target_network_id,
        "search_route_remaining_steps": max(0, bridge_path.min_steps - 1),
        "search_route_committed": _route_committed_from_history(state, bridge_path),
    }


def _route_committed_from_history(state: GameState, bridge_path: BridgePath) -> bool:
    for context in reversed(state.stats.decision_contexts[-6:]):
        target_id = _context_int(context, "search_route_target_network_id")
        remaining_steps = _context_int(context, "search_route_remaining_steps")
        committed = context.get("search_route_committed")
        if target_id != bridge_path.target_network_id or committed is not True:
            continue
        return remaining_steps is None or bridge_path.min_steps <= remaining_steps
    return True


def _preferred_committed_route_action(
    state: GameState,
    *,
    simulation_cache: SimulationCache | None = None,
) -> Action | None:
    previous_target_id: int | None = None
    previous_remaining_steps: int | None = None
    for context in reversed(state.stats.decision_contexts[-6:]):
        if context.get("search_route_committed") is not True:
            continue
        previous_target_id = _context_int(context, "search_route_target_network_id")
        previous_remaining_steps = _context_int(context, "search_route_remaining_steps")
        break
    if previous_target_id is None:
        return None

    paths = (
        simulation_cache.bridge_paths(state)
        if simulation_cache is not None
        else _bridge_paths_for_state(state)
    )
    for path in paths:
        if path.target_network_id != previous_target_id:
            continue
        if previous_remaining_steps is not None and path.min_steps > previous_remaining_steps:
            continue
        return path.actions[0] if path.actions else None
    return None


def _post_decision_diagnostics(
    state: GameState,
    decision: PlannedSearchDecision,
) -> dict[str, object]:
    diagnostics = _greedy_anchor_diagnostics(
        root_candidates=decision.root_candidate_diagnostics,
        chosen_action=decision.action,
        greedy_action=decision.greedy_action,
    )
    diagnostics.update(
        _city_anchor_diagnostics(
            state=state,
            chosen_action=decision.action,
            greedy_action=decision.greedy_action,
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


def _adjacent_network_ids_for_context(context: HeuristicContext, coord: Coord) -> set[int]:
    passable_map = context_passable_network_map(context)
    return {
        passable_map[neighbor] for neighbor in cardinal_neighbors(coord) if neighbor in passable_map
    }


def _network_food_risk_diagnostics(
    state: GameState,
    *,
    simulation_cache: SimulationCache | None = None,
) -> dict[str, object]:
    profile = (
        simulation_cache.network_food_risk(state)
        if simulation_cache is not None
        else _network_food_risk_profile(state)
    )
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
    *,
    simulation_cache: SimulationCache | None = None,
) -> int:
    root_profile = (
        simulation_cache.profile(root_state)
        if simulation_cache is not None
        else build_search_position_profile(root_state)
    )
    leaf_profile = (
        simulation_cache.profile(leaf_state)
        if simulation_cache is not None
        else build_search_position_profile(leaf_state)
    )
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
    starvation_increase = max(
        0,
        leaf_profile.starving_network_count - root_profile.starving_network_count,
    )
    network_increase = max(0, leaf_profile.network_count - root_profile.network_count)
    isolated_increase = max(0, leaf_profile.isolated_city_count - root_profile.isolated_city_count)
    pressure_reduction = max(0, root_profile.food_pressure - leaf_profile.food_pressure)
    first_action = sequence[0] if sequence else None
    first_delta = (
        _first_action_delta(root_state, first_action, simulation_cache=simulation_cache)
        if first_action is not None
        else {}
    )
    first_food_delta = int(first_delta.get("food_pressure", 0))
    first_starving_delta = int(first_delta.get("starving_network_count", 0))
    first_network_delta = int(first_delta.get("network_count", 0))
    first_connected_delta = int(first_delta.get("connected_city_count", 0))
    first_road_overbuild_delta = int(first_delta.get("road_overbuild", 0))

    adjustment = 0
    if root_profile.turns_remaining > 3 and skip_actions:
        adjustment -= skip_actions * 5_500
        adjustment -= max(0, skip_actions - 1) * 2_500

    if root_profile.mode in {SEARCH_MODE_RESCUE, SEARCH_MODE_CONNECT}:
        adjustment -= starvation_increase * 58_000
        adjustment -= network_increase * 22_000
        adjustment -= isolated_increase * 22_000

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
            and (
                simulation_cache.bridge_path_for_first_action(root_state, first_action)
                if simulation_cache is not None
                else _bridge_path_for_first_action(root_state, first_action)
            )
            is None
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
            first_bridge_path = (
                simulation_cache.bridge_path_for_first_action(root_state, first_action)
                if simulation_cache is not None
                else _bridge_path_for_first_action(root_state, first_action)
            )
            if first_bridge_path is not None:
                adjustment += 24_000
                adjustment += first_bridge_path.progress_after_first_step * 4_000
            if (
                first_road_overbuild_delta > 0
                and first_connected_delta <= 0
                and first_network_delta >= 0
                and first_bridge_path is None
            ):
                adjustment -= 45_000
            if (
                root_profile.connected_city_count >= root_profile.city_count
                and root_profile.city_count >= 2
                and first_connected_delta <= 0
                and first_network_delta >= 0
                and first_bridge_path is None
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


def _first_action_delta(
    state: GameState,
    action: Action,
    *,
    simulation_cache: SimulationCache | None = None,
) -> dict[str, int]:
    before = (
        simulation_cache.profile(state)
        if simulation_cache is not None
        else build_search_position_profile(state)
    )
    after_state = (
        simulation_cache.simulate(state, action)
        if simulation_cache is not None
        else simulate_action(state, action)
    )
    after = (
        simulation_cache.profile(after_state)
        if simulation_cache is not None
        else build_search_position_profile(after_state)
    )
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
