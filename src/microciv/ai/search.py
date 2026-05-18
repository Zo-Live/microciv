"""Rolling-horizon beam-search policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from microciv.ai.policy import Policy, simulate_action
from microciv.ai.search_support import (
    SEARCH_MODE_CONNECT,
    SEARCH_MODE_EXPAND,
    SEARCH_MODE_RESCUE,
    SearchCandidateConfig,
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

SEARCH_DEPTH_REASON_FIXED = "fixed"
SEARCH_DEPTH_REASON_FOOD_RESCUE = "food_rescue"
SEARCH_DEPTH_REASON_NETWORK_CONNECT = "network_connect"
SEARCH_DEPTH_REASON_GROWTH_STALL = "growth_stall"
SEARCH_DEPTH_REASON_FOOD_WATCH = "food_watch"
SEARCH_DEPTH_REASON_ENDGAME_PUSH = "endgame_push"
SEARCH_DEPTH_REASON_STEADY = "steady"

_SEARCH_PRESSURE_COMPONENT_KEYS: tuple[str, ...] = (
    "isolated_penalty",
    "starving_penalty",
    "starving_turn_penalty",
    "food_pressure_penalty",
    "fragmentation_penalty",
    "expansion_deficit_penalty",
    "early_fill_penalty",
    "road_overbuild_penalty",
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
        return dict(self._plan_action(state).context)

    def _plan_action(self, state: GameState) -> PlannedSearchDecision:
        cache_key = self._build_cache_key(state)
        if self._cache_key == cache_key and self._cached_decision is not None:
            return self._cached_decision

        depth_decision = self._choose_depth(state)
        candidate_config = SearchCandidateConfig(candidate_limit=self.search_candidate_limit)
        telemetry = SearchTelemetry()
        best_node = self._run_beam_search(
            state=state,
            depth=depth_decision.depth,
            candidate_config=candidate_config,
            telemetry=telemetry,
        )

        if best_node is None or not best_node.sequence:
            action = Action.skip()
            best_evaluation = evaluate_search_leaf(state)
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
                "search_depth": depth_decision.depth,
                "search_base_depth": self.search_depth,
                "search_max_depth": self.search_max_depth,
                "search_depth_reason": depth_decision.reason,
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
                "search_root_safe_city_candidate_count": (
                    telemetry.root_safe_city_candidate_count
                ),
                "search_root_effective_connection_road_candidate_count": (
                    telemetry.root_effective_connection_road_candidate_count
                ),
                "search_root_rescue_candidate_count": telemetry.root_rescue_candidate_count,
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
        )
        self._cache_key = cache_key
        self._cached_decision = decision
        return decision

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
        root_evaluation = evaluate_search_leaf(state)
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
                    telemetry.root_profile = candidate_set.profile
                    telemetry.root_legal_action_count = candidate_set.legal_action_count
                    telemetry.root_legal_counts_by_type = candidate_set.legal_counts_by_type
                    telemetry.root_candidate_counts_by_type = candidate_set.candidate_counts_by_type
                    telemetry.root_safe_city_candidate_count = (
                        candidate_set.safe_city_candidate_count
                    )
                    telemetry.root_effective_connection_road_candidate_count = (
                        candidate_set.effective_connection_road_candidate_count
                    )
                    telemetry.root_rescue_candidate_count = candidate_set.rescue_candidate_count
                telemetry.nodes_expanded += 1
                telemetry.candidates_considered += len(candidate_set.candidates)

                if not candidate_set.candidates:
                    best_node = _better_node(best_node, node)
                    continue

                for candidate in candidate_set.candidates:
                    simulated_state = simulate_action(node.state, candidate.action)
                    leaf_evaluation = evaluate_search_leaf(simulated_state)
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
    after_state = simulate_action(state, action)
    after = build_search_position_profile(after_state)
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
        "search_road_merges_networks": road_merges_networks,
        "search_road_connected_city_delta": (
            road_connected_city_delta if action.action_type is ActionType.BUILD_ROAD else 0
        ),
        "search_road_is_redundant": road_is_redundant,
        "search_road_after_full_connectivity": road_after_full_connectivity,
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

    adjustment = 0
    if root_profile.turns_remaining > 3 and skip_actions:
        adjustment -= skip_actions * 5_500
        adjustment -= max(0, skip_actions - 1) * 2_500

    if root_profile.mode == SEARCH_MODE_EXPAND:
        adjustment += min(city_actions, root_profile.expansion_deficit) * 12_000
        adjustment += connected_gain * 2_500
        if root_profile.turns_remaining > 10 and root_profile.expansion_deficit > 0:
            adjustment -= fill_actions * 2_800
            if connected_gain == 0 and network_reduction == 0:
                adjustment -= road_actions * 1_800
            adjustment -= skip_actions * 4_000
    elif root_profile.mode == SEARCH_MODE_CONNECT:
        adjustment += connected_gain * 4_200
        adjustment += network_reduction * 3_500
        if connected_gain > 0 or network_reduction > 0:
            adjustment += road_actions * 800
        else:
            adjustment -= road_actions * 1_400
        adjustment -= skip_actions * 2_500
    elif root_profile.mode == SEARCH_MODE_RESCUE:
        adjustment += starvation_reduction * 6_500
        adjustment += pressure_reduction * 160
        if root_profile.food_pressure >= FOOD_CONSUMPTION_PER_CITY * 2:
            adjustment -= city_actions * 1_800
        adjustment -= skip_actions * 3_000
    elif root_profile.turns_remaining > 10 and root_profile.expansion_deficit > 0:
        adjustment += min(city_actions, root_profile.expansion_deficit) * 3_500
        adjustment -= skip_actions * 2_500

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
