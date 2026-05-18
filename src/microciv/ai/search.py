"""Rolling-horizon beam-search policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from microciv.ai.policy import Policy, simulate_action
from microciv.ai.search_support import (
    SearchCandidateConfig,
    SearchLeafEvaluation,
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
        if _has_network_connect_need(state):
            return SearchDepthDecision(
                depth=min(context.max_depth, 5),
                reason=SEARCH_DEPTH_REASON_NETWORK_CONNECT,
            )
        if _has_growth_stall(state):
            return SearchDepthDecision(
                depth=context.max_depth,
                reason=SEARCH_DEPTH_REASON_GROWTH_STALL,
            )
        if _max_food_pressure(state) >= FOOD_CONSUMPTION_PER_CITY:
            return SearchDepthDecision(
                depth=min(context.max_depth, context.base_depth + 2),
                reason=SEARCH_DEPTH_REASON_FOOD_WATCH,
            )
        if _turns_remaining(state) <= 18:
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
    leaf_evaluation: SearchLeafEvaluation


@dataclass(slots=True)
class SearchTelemetry:
    nodes_expanded: int = 0
    candidates_considered: int = 0
    leaf_count: int = 0


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
            best_sequence: list[dict[str, object]] = []
        else:
            action = best_node.sequence[0]
            best_evaluation = best_node.leaf_evaluation
            best_value = best_node.value
            best_sequence = [_action_to_dict(item) for item in best_node.sequence]

        decision = PlannedSearchDecision(
            action=action,
            context={
                "search_depth": depth_decision.depth,
                "search_base_depth": self.search_depth,
                "search_max_depth": self.search_max_depth,
                "search_depth_reason": depth_decision.reason,
                "search_beam_width": self.search_beam_width,
                "search_candidate_limit": self.search_candidate_limit,
                "search_nodes_expanded": telemetry.nodes_expanded,
                "search_candidates_considered": telemetry.candidates_considered,
                "search_leaf_count": telemetry.leaf_count,
                "search_best_value": best_value,
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
                telemetry.nodes_expanded += 1
                telemetry.candidates_considered += len(candidate_set.candidates)

                if not candidate_set.candidates:
                    best_node = _better_node(best_node, node)
                    continue

                for candidate in candidate_set.candidates:
                    simulated_state = simulate_action(node.state, candidate.action)
                    leaf_evaluation = evaluate_search_leaf(simulated_state)
                    telemetry.leaf_count += 1
                    child = SearchNode(
                        state=simulated_state,
                        sequence=(*node.sequence, candidate.action),
                        value=leaf_evaluation.value,
                        leaf_evaluation=leaf_evaluation,
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
