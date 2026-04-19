"""Weighted-random policy for baseline comparison."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from microciv.ai.heuristics import (
    TECH_UNLOCK_PRIORITY,
    HeuristicContext,
    build_heuristic_context,
    building_action_score,
    city_network_pressure,
    city_site_score_for_context,
    context_total_resources,
    partition_actions,
    research_action_score,
    road_site_score_for_context,
)
from microciv.ai.policy import Policy, get_legal_actions
from microciv.game.actions import Action
from microciv.game.enums import ActionType, BuildingType, TechType
from microciv.game.models import GameState
from microciv.game.scoring import connected_city_count, starving_network_count
from microciv.utils.rng import build_rng


@dataclass(slots=True, frozen=True)
class PlannedRandomDecision:
    action: Action
    context: dict[str, object]


class RandomPolicy(Policy):
    """Seeded weighted-random policy used as a stochastic baseline."""

    def __init__(self, seed: int = 0) -> None:
        self._rng: Random = build_rng(seed)
        self._cache_key: tuple[int, int, int, int, int, int] | None = None
        self._cached_decision: PlannedRandomDecision | None = None

    def select_action(self, state: GameState) -> Action:
        return self._plan_action(state).action

    def explain_decision(self, state: GameState) -> dict[str, object]:
        return dict(self._plan_action(state).context)

    def _plan_action(self, state: GameState) -> PlannedRandomDecision:
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
            decision = PlannedRandomDecision(action=Action.skip(), context={})
            self._cache_key = cache_key
            self._cached_decision = decision
            return decision

        context = build_heuristic_context(state)
        groups = partition_actions(legal_actions)
        type_weights = self._type_weights(context, groups)
        chosen_type = _weighted_choice(self._rng, type_weights)
        chosen_actions = groups.get(chosen_type, [Action.skip()])
        action_weights = self._action_weights(context, chosen_type, chosen_actions)
        chosen_action = _weighted_choice(self._rng, action_weights)

        decision = PlannedRandomDecision(
            action=chosen_action,
            context={
                "random_type_weights": {
                    action_type.value: round(weight, 3)
                    for action_type, weight in type_weights.items()
                    if weight > 0
                }
            },
        )
        self._cache_key = cache_key
        self._cached_decision = decision
        return decision

    def _type_weights(
        self,
        context: HeuristicContext,
        groups: dict[ActionType, list[Action]],
    ) -> dict[ActionType, float]:
        state = context.state
        resources = context_total_resources(context)
        starving = starving_network_count(state)
        connected = connected_city_count(state)
        pressure = max(
            (city_network_pressure(network) for network in state.networks.values()),
            default=0,
        )
        city_count = len(state.cities)
        road_count = len(state.roads)
        best_road_score = max(
            (
                road_site_score_for_context(context, action.coord)
                for action in groups.get(ActionType.BUILD_ROAD, [])
                if action.coord is not None
            ),
            default=0,
        )

        weights: dict[ActionType, float] = {
            ActionType.BUILD_CITY: 1.0,
            ActionType.BUILD_ROAD: 0.45,
            ActionType.BUILD_BUILDING: 1.0,
            ActionType.RESEARCH_TECH: 0.8,
            ActionType.SKIP: 0.05,
        }

        if pressure > 0 or starving > 0:
            weights[ActionType.BUILD_CITY] *= 0.3
            weights[ActionType.BUILD_ROAD] *= 1.2
            weights[ActionType.BUILD_BUILDING] *= 1.9
            weights[ActionType.RESEARCH_TECH] *= 1.4
        if city_count >= 10:
            weights[ActionType.BUILD_CITY] *= 0.65
        if city_count >= 20:
            weights[ActionType.BUILD_CITY] *= 0.6
        if resources.food < 0:
            weights[ActionType.BUILD_CITY] *= 0.25
        if road_count < max(1, city_count // 3):
            weights[ActionType.BUILD_ROAD] *= 1.5
        if connected < max(0, city_count // 4):
            weights[ActionType.BUILD_ROAD] *= 1.3
        if road_count >= max(2, city_count):
            weights[ActionType.BUILD_ROAD] *= 0.35
        if best_road_score < 100:
            weights[ActionType.BUILD_ROAD] *= 0.35
        elif best_road_score >= 170:
            weights[ActionType.BUILD_ROAD] *= 1.25
        if groups.get(ActionType.BUILD_BUILDING):
            weights[ActionType.BUILD_BUILDING] *= 1.25
        if groups.get(ActionType.RESEARCH_TECH):
            weights[ActionType.RESEARCH_TECH] *= 1.15

        for action_type in ActionType:
            if not groups.get(action_type):
                weights[action_type] = 0.0
        return weights

    def _action_weights(
        self,
        context: HeuristicContext,
        action_type: ActionType,
        actions: list[Action],
    ) -> dict[Action, float]:
        state = context.state
        weights: dict[Action, float] = {}
        for action in actions:
            if action_type is ActionType.BUILD_CITY and action.coord is not None:
                weights[action] = max(0.2, city_site_score_for_context(context, action.coord) / 25)
            elif action_type is ActionType.BUILD_ROAD and action.coord is not None:
                weights[action] = max(
                    0.05,
                    road_site_score_for_context(context, action.coord) / 80,
                )
            elif action_type is ActionType.BUILD_BUILDING:
                base = building_action_score(state, action) / 35
                if action.building_type is BuildingType.FARM:
                    base *= 1.3
                weights[action] = max(0.2, base)
            elif action_type is ActionType.RESEARCH_TECH:
                base = research_action_score(state, action) / 35
                if action.tech_type is not None:
                    base *= (
                        1.0
                        + (
                            len(TECH_UNLOCK_PRIORITY)
                            - TECH_UNLOCK_PRIORITY.index(action.tech_type)
                        )
                        * 0.05
                    )
                    if action.tech_type is TechType.AGRICULTURE:
                        base *= 1.2
                weights[action] = max(0.2, base)
            else:
                weights[action] = 1.0
        return weights


def _weighted_choice[T](rng: Random, weights: dict[T, float]) -> T:
    total = sum(max(weight, 0.0) for weight in weights.values())
    if total <= 0:
        return next(iter(weights))

    target = rng.random() * total
    cumulative = 0.0
    for item, weight in weights.items():
        cumulative += max(weight, 0.0)
        if cumulative >= target:
            return item
    return next(reversed(weights))
