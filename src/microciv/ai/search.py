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
)
from microciv.game.actions import Action
from microciv.game.enums import ActionType, BuildingType, TechType
from microciv.game.models import GameState

SEARCH_DEPTH_REASON_FIXED = "fixed"

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
        search_max_depth: int | None = None,
    ) -> None:
        self.search_depth = _require_positive(search_depth, "search_depth")
        self.search_beam_width = _require_positive(search_beam_width, "search_beam_width")
        self.search_candidate_limit = _require_positive(
            search_candidate_limit, "search_candidate_limit"
        )
        self.search_max_depth = (
            self.search_depth
            if search_max_depth is None
            else _require_positive(search_max_depth, "search_max_depth")
        )
        if self.search_max_depth < self.search_depth:
            raise ValueError("search_max_depth must be greater than or equal to search_depth")
        self.search_depth_strategy = search_depth_strategy or FixedSearchDepthStrategy()

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
            best_value = evaluate_search_leaf(state).value
            best_sequence: list[dict[str, object]] = []
        else:
            action = best_node.sequence[0]
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
