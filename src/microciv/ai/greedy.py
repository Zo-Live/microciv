"""One-step lookahead greedy policy."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import cast

from microciv.ai.heuristics import (
    TECH_UNLOCK_PRIORITY,
    HeuristicContext,
    build_heuristic_context,
    building_action_score,
    city_expansion_score_for_context,
    city_key,
    city_network_pressure,
    city_site_score,
    city_site_score_for_context,
    city_terrain_counts,
    context_city_network_pressure,
    context_city_terrain_counts,
    context_is_river_adjacent_site,
    context_network_missing_building_types,
    context_passable_network_map,
    context_total_resources,
    material_targets,
    partition_actions,
    research_action_score,
    resource_ring_counts_for_context,
    road_site_score_for_context,
)
from microciv.ai.policy import Policy, get_legal_actions, simulate_action
from microciv.constants import (
    BUILDING_YIELDS,
    CITY_CENTER_YIELDS,
    FOOD_CONSUMPTION_PER_CITY,
    TERRAIN_YIELDS,
)
from microciv.game.actions import Action
from microciv.game.enums import (
    ActionType,
    BuildingType,
    OccupantType,
    ResourceType,
    TechType,
    TerrainType,
)
from microciv.game.models import GameState, Network, ResourcePool
from microciv.game.networks import map_passable_coords_to_networks
from microciv.game.scoring import (
    ScoreBreakdown,
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

MAX_CITY_CANDIDATES = 8
MAX_BUILDING_CANDIDATES = 8
MAX_RESOURCE_CITY_CANDIDATES = 8
TARGET_INLAND_SHARE = 0.45

STAGE_RESCUE = "rescue"
STAGE_CONSOLIDATE = "consolidate"
STAGE_EXPAND = "expand"
STAGE_FILL = "fill"


@dataclass(slots=True, frozen=True)
class PlannedDecision:
    action: Action
    context: dict[str, object]


@dataclass(slots=True, frozen=True)
class SimulatedEvaluation:
    future_context: HeuristicContext
    future_profile: GreedyStateProfile
    future_resources: ResourcePool
    future_budget: NetworkBudget | None
    rescue_recovery: RescueRecovery


@dataclass(slots=True, frozen=True)
class GreedyStateProfile:
    breakdown_total: int
    breakdown_building_utilization: int
    breakdown_building_mismatch_penalty: int
    breakdown_city_composition_bonus: int
    breakdown_starving_network_penalty: int
    breakdown_fragmented_network_penalty: int
    total_food: int
    total_wood: int
    total_ore: int
    total_science: int
    total_buildings: int
    city_count: int
    network_count: int
    turns_remaining: int
    buildings_per_city: float
    infrastructure_gap: int
    food_buffer_target: int
    connected_city_count: int
    isolated_city_count: int
    starving_network_count: int
    largest_network_size: int
    tech_count: int
    missing_unlocked_buildings: bool
    connected_inland_count: int
    composition_gap: float
    development_saturated: bool
    pressure: int
    food_crisis: bool
    wood_target: int
    ore_target: int
    forest_city_count: int
    mountain_city_count: int
    plain_city_count: int


@dataclass(slots=True, frozen=True)
class CandidateCatalog:
    city_actions: list[Action]
    resource_city_actions: list[Action]
    forest_city_actions: list[Action]
    mountain_city_actions: list[Action]
    plain_city_actions: list[Action]
    interior_gem_actions: list[Action]
    inland_city_actions: list[Action]
    river_city_actions: list[Action]
    road_actions: list[Action]
    building_actions: list[Action]
    gap_building_actions: list[Action]
    research_actions: list[Action]


@dataclass(slots=True, frozen=True)
class CandidateLimits:
    city_limit: int
    road_limit: int
    resource_city_limit: int
    building_limit: int
    research_limit: int


@dataclass(slots=True, frozen=True)
class RescueRecovery:
    starving_delta: int
    network_delta: int
    isolated_delta: int
    pressure_delta: int
    starving_penalty_delta: int
    fragmented_penalty_delta: int

    @property
    def effective(self) -> bool:
        return (
            self.starving_delta > 0
            or self.network_delta > 0
            or self.isolated_delta > 0
        )


@dataclass(slots=True, frozen=True)
class SiteBudget:
    food_yield: int
    wood_yield: int
    ore_yield: int
    science_yield: int
    food_balance: int

    @property
    def total_yield(self) -> int:
        return self.food_yield + self.wood_yield + self.ore_yield + self.science_yield


@dataclass(slots=True, frozen=True)
class NetworkBudget:
    network_id: int
    city_count: int
    food: int
    wood: int
    ore: int
    science: int
    pressure: int
    starving: bool


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
                context={
                    "greedy_stage": STAGE_FILL,
                    "greedy_priority": "no_legal_actions",
                    "greedy_best_action_type": "skip",
                },
            )
            self._cache_key = cache_key
            self._cached_decision = decision
            return decision

        groups = partition_actions(legal_actions)
        current_context = build_heuristic_context(state)
        profile = _build_state_profile(state, current_context)
        stage = _select_stage(profile)
        catalog = _build_candidate_catalog(state, groups, current_context)
        candidates = self._candidate_actions(
            state,
            groups,
            profile,
            catalog,
            stage,
            current_context,
        )
        evaluations: dict[Action, SimulatedEvaluation] = {}

        best_action = Action.skip()
        best_value = -10**18
        best_priority = "skip"
        for action in candidates:
            value = self._evaluate_action(
                state,
                action,
                profile,
                stage,
                current_context,
                evaluations,
            )
            priority = _priority_label(action)
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
            context=_decision_context(
                state=state,
                action=best_action,
                stage=stage,
                priority=best_priority,
                best_value=best_value,
                profile=profile,
                current_context=current_context,
                evaluation=evaluations[best_action],
            ),
        )
        self._cache_key = cache_key
        self._cached_decision = decision
        return decision

    def _candidate_actions(
        self,
        state: GameState,
        groups: dict[ActionType, list[Action]],
        profile: GreedyStateProfile,
        catalog: CandidateCatalog,
        stage: str,
        current_context: HeuristicContext,
    ) -> list[Action]:
        candidates: list[Action] = []
        limits = _candidate_limits(state, profile, stage, len(catalog.research_actions))

        self._extend_stage_core_candidates(candidates, catalog, profile, limits, stage)
        self._extend_stage_city_candidates(
            state,
            candidates,
            catalog,
            profile,
            limits,
            stage,
            current_context,
        )
        candidates.extend(groups.get(ActionType.SKIP, [])[:1])
        return _dedupe_actions(candidates)

    def _extend_stage_core_candidates(
        self,
        candidates: list[Action],
        catalog: CandidateCatalog,
        profile: GreedyStateProfile,
        limits: CandidateLimits,
        stage: str,
    ) -> None:
        farm_actions = [
            action
            for action in catalog.building_actions
            if action.building_type is BuildingType.FARM
        ]
        agriculture = [
            action
            for action in catalog.research_actions
            if action.tech_type is TechType.AGRICULTURE
        ]

        if stage == STAGE_RESCUE:
            candidates.extend(farm_actions[: min(8, len(farm_actions))])
            candidates.extend(agriculture[:1])
            candidates.extend(catalog.road_actions[: limits.road_limit])
            candidates.extend(catalog.gap_building_actions[:8])
            candidates.extend(catalog.building_actions[: limits.building_limit])
            candidates.extend(catalog.research_actions[: limits.research_limit])
            return

        if stage == STAGE_CONSOLIDATE:
            candidates.extend(catalog.road_actions[: limits.road_limit])
            candidates.extend(catalog.gap_building_actions[:8])
            candidates.extend(catalog.building_actions[: limits.building_limit])
            candidates.extend(catalog.research_actions[: limits.research_limit])
            return

        if stage == STAGE_FILL:
            candidates.extend(catalog.gap_building_actions[:8])
            candidates.extend(catalog.building_actions[: limits.building_limit])
            candidates.extend(catalog.research_actions[: limits.research_limit])
            candidates.extend(catalog.road_actions[: limits.road_limit])
            return

        candidates.extend(catalog.gap_building_actions[:8])
        candidates.extend(catalog.research_actions[: limits.research_limit])
        candidates.extend(catalog.building_actions[: limits.building_limit])
        candidates.extend(catalog.road_actions[: limits.road_limit])

    def _extend_stage_city_candidates(
        self,
        state: GameState,
        candidates: list[Action],
        catalog: CandidateCatalog,
        profile: GreedyStateProfile,
        limits: CandidateLimits,
        stage: str,
        current_context: HeuristicContext,
    ) -> None:
        city_actions = _stage_filter_city_actions(
            state,
            catalog.city_actions,
            stage,
            profile,
            limits.city_limit,
            current_context,
        )
        resource_city_actions = _stage_filter_city_actions(
            state,
            catalog.resource_city_actions,
            stage,
            profile,
            limits.resource_city_limit,
            current_context,
        )
        candidates.extend(city_actions)
        candidates.extend(resource_city_actions)

        if stage == STAGE_RESCUE:
            candidates.extend(
                _stage_filter_city_actions(
                    state,
                    catalog.river_city_actions,
                    stage,
                    profile,
                    min(3, limits.resource_city_limit),
                    current_context,
                )
            )
            candidates.extend(
                _stage_filter_city_actions(
                    state,
                    catalog.plain_city_actions,
                    stage,
                    profile,
                    min(3, limits.resource_city_limit),
                    current_context,
                )
            )
            return

        if _inland_share(
            profile.connected_city_count,
            profile.connected_inland_count,
        ) < TARGET_INLAND_SHARE:
            candidates.extend(
                _stage_filter_city_actions(
                    state,
                    catalog.inland_city_actions,
                    stage,
                    profile,
                    min(4, limits.city_limit),
                    current_context,
                )
            )

        if profile.total_wood < profile.wood_target or profile.forest_city_count < 3:
            candidates.extend(
                _stage_filter_city_actions(
                    state,
                    catalog.forest_city_actions,
                    stage,
                    profile,
                    min(4, limits.resource_city_limit),
                    current_context,
                )
            )
        if profile.total_ore < profile.ore_target or profile.mountain_city_count < 3:
            candidates.extend(
                _stage_filter_city_actions(
                    state,
                    catalog.mountain_city_actions,
                    stage,
                    profile,
                    min(4, limits.resource_city_limit),
                    current_context,
                )
            )

        food_target = profile.city_count * FOOD_CONSUMPTION_PER_CITY * 3
        if profile.total_food < food_target or profile.plain_city_count < 3:
            candidates.extend(
                _stage_filter_city_actions(
                    state,
                    catalog.plain_city_actions,
                    stage,
                    profile,
                    min(4, limits.resource_city_limit),
                    current_context,
                )
            )

        river_limit = 4 if stage == STAGE_EXPAND else 2
        candidates.extend(
            _stage_filter_city_actions(
                state,
                catalog.river_city_actions,
                stage,
                profile,
                min(river_limit, limits.resource_city_limit),
                current_context,
            )
        )
        candidates.extend(
            _stage_filter_city_actions(
                state,
                catalog.interior_gem_actions,
                stage,
                profile,
                min(3, limits.resource_city_limit),
                current_context,
            )
        )

    def _evaluate_action(
        self,
        state: GameState,
        action: Action,
        profile: GreedyStateProfile,
        stage: str,
        current_context: HeuristicContext,
        evaluations: dict[Action, SimulatedEvaluation],
    ) -> int:
        evaluation = _get_simulated_evaluation(state, action, profile, evaluations)
        future = evaluation.future_profile
        future_resources = evaluation.future_resources
        future_budget = evaluation.future_budget
        rescue_recovery = evaluation.rescue_recovery if stage == STAGE_RESCUE else None

        value = _stage_action_bias(stage, action)
        delta_score = future.breakdown_total - profile.breakdown_total
        value += future.breakdown_total * 18
        value += delta_score * 46
        value += max(0, future.connected_city_count - profile.connected_city_count) * 110
        value += max(0, profile.isolated_city_count - future.isolated_city_count) * 180
        value += max(0, profile.starving_network_count - future.starving_network_count) * 520
        value += max(0, profile.network_count - future.network_count) * 180
        value += max(0, future.largest_network_size - profile.largest_network_size) * 40
        value += (
            future.breakdown_building_utilization - profile.breakdown_building_utilization
        ) * 18
        value += (
            profile.breakdown_building_mismatch_penalty
            - future.breakdown_building_mismatch_penalty
        ) * 14
        value += (
            future.breakdown_city_composition_bonus
            - profile.breakdown_city_composition_bonus
        ) * 10
        value += max(0, profile.pressure - future.pressure) * 36
        value -= max(0, -future_resources.food) * 18
        value -= future.starving_network_count * 220
        value -= future.isolated_city_count * 18

        if action.action_type is ActionType.BUILD_ROAD:
            value += self._score_road_action(
                state,
                action,
                profile,
                future,
                future_budget,
                rescue_recovery,
                stage,
                current_context,
            )
        elif action.action_type is ActionType.BUILD_BUILDING:
            value += self._score_building_action(
                state,
                action,
                profile,
                future,
                future_budget,
                rescue_recovery,
                stage,
                current_context,
            )
        elif action.action_type is ActionType.RESEARCH_TECH:
            value += self._score_research_action(
                action,
                profile,
                future,
                future_budget,
                rescue_recovery,
                stage,
            )
        elif action.action_type is ActionType.BUILD_CITY:
            value += self._score_city_action(
                state,
                action,
                profile,
                future,
                future_budget,
                rescue_recovery,
                stage,
                current_context,
            )
        elif action.action_type is ActionType.SKIP:
            value += self._score_skip_action(profile, stage)
        return value

    def _score_road_action(
        self,
        state: GameState,
        action: Action,
        profile: GreedyStateProfile,
        future: GreedyStateProfile,
        future_budget: NetworkBudget | None,
        rescue_recovery: RescueRecovery | None,
        stage: str,
        current_context: HeuristicContext,
    ) -> int:
        assert action.coord is not None

        value = 0
        road_structure = _road_structure_score(state, action.coord, current_context)
        value += road_structure * 140
        value += max(0, profile.network_count - future.network_count) * 220
        value += max(0, profile.starving_network_count - future.starving_network_count) * 420
        value += max(0, profile.isolated_city_count - future.isolated_city_count) * 180
        if future_budget is not None:
            value -= max(0, future_budget.pressure) * 40
            if not future_budget.starving:
                value += 90
        if future.connected_city_count == profile.connected_city_count and (
            future.isolated_city_count == profile.isolated_city_count
        ):
            value -= 180
        if future.largest_network_size == profile.largest_network_size:
            value -= 60
        if profile.missing_unlocked_buildings:
            value -= 120
        if profile.tech_count < len(TechType):
            value -= 120
        if stage == STAGE_RESCUE and road_structure < 2:
            value -= 120
        if rescue_recovery is not None:
            value += max(0, rescue_recovery.starving_delta) * 320
            value += max(0, rescue_recovery.network_delta) * 180
            value += max(0, rescue_recovery.isolated_delta) * 120
            value += max(0, rescue_recovery.starving_penalty_delta)
            if not rescue_recovery.effective and rescue_recovery.pressure_delta <= 0:
                value -= 420
        if stage == STAGE_FILL and profile.development_saturated:
            structural_gain = (
                future.connected_city_count > profile.connected_city_count
                or future.isolated_city_count < profile.isolated_city_count
                or future.network_count < profile.network_count
                or future.starving_network_count < profile.starving_network_count
            )
            if not structural_gain:
                value -= 900
            if future.breakdown_total <= profile.breakdown_total:
                value -= 240
        return value

    def _score_building_action(
        self,
        state: GameState,
        action: Action,
        profile: GreedyStateProfile,
        future: GreedyStateProfile,
        future_budget: NetworkBudget | None,
        rescue_recovery: RescueRecovery | None,
        stage: str,
        current_context: HeuristicContext,
    ) -> int:
        assert action.building_type is not None

        value = 0
        per_turn_yield = sum(BUILDING_YIELDS[action.building_type].values())
        value += per_turn_yield * 20
        value += profile.infrastructure_gap * 28
        if _is_gap_build_action(state, action, current_context):
            value += 240
        if profile.development_saturated:
            value -= 90
        if (
            profile.connected_city_count >= 8
            and profile.total_buildings >= profile.city_count * 2
            and profile.composition_gap > 0.15
        ):
            value -= int(profile.composition_gap * 520)
        if future_budget is not None:
            if action.building_type is BuildingType.FARM:
                value += max(0, profile.pressure - future_budget.pressure) * 40
                if future_budget.starving:
                    value -= 120
                else:
                    value += 220
            elif future_budget.starving:
                value -= 260
        if stage == STAGE_RESCUE and action.building_type is not BuildingType.FARM:
            value -= 160
        if stage == STAGE_FILL and action.building_type is BuildingType.LIBRARY:
            value += 90
        if rescue_recovery is not None:
            if action.building_type is BuildingType.FARM:
                value += max(0, rescue_recovery.starving_delta) * 420
                value += max(0, rescue_recovery.pressure_delta) * 24
                value += max(0, rescue_recovery.starving_penalty_delta)
                if (
                    not rescue_recovery.effective
                    and rescue_recovery.pressure_delta <= 0
                    and future.starving_network_count >= profile.starving_network_count
                ):
                    value -= 220
            elif not rescue_recovery.effective:
                value -= 260
        return value

    def _score_research_action(
        self,
        action: Action,
        profile: GreedyStateProfile,
        future: GreedyStateProfile,
        future_budget: NetworkBudget | None,
        rescue_recovery: RescueRecovery | None,
        stage: str,
    ) -> int:
        assert action.tech_type is not None

        value = 140
        value += (len(TechType) - profile.tech_count) * 45
        value += min(profile.turns_remaining, 24) * 4
        if action.tech_type is TechType.AGRICULTURE:
            value += 100
            if stage == STAGE_RESCUE:
                value += 220
        elif stage == STAGE_RESCUE:
            value -= 120
        if (
            future_budget is not None
            and future_budget.starving
            and action.tech_type is not TechType.AGRICULTURE
        ):
            value -= 180
        if stage == STAGE_FILL and action.tech_type is TechType.EDUCATION:
            value += 80
        if profile.breakdown_building_utilization < 0:
            value += 60
        if rescue_recovery is not None:
            if action.tech_type is TechType.AGRICULTURE:
                value += max(0, rescue_recovery.starving_delta) * 360
                value += max(0, rescue_recovery.pressure_delta) * 18
                value += max(0, rescue_recovery.starving_penalty_delta)
                if (
                    not rescue_recovery.effective
                    and rescue_recovery.pressure_delta <= 0
                    and future.starving_network_count >= profile.starving_network_count
                ):
                    value -= 180
            elif not rescue_recovery.effective:
                value -= 220
        return value

    def _score_city_action(
        self,
        state: GameState,
        action: Action,
        profile: GreedyStateProfile,
        future: GreedyStateProfile,
        future_budget: NetworkBudget | None,
        rescue_recovery: RescueRecovery | None,
        stage: str,
        current_context: HeuristicContext,
    ) -> int:
        assert action.coord is not None

        value = 0
        site_budget = _site_budget(state, action.coord, current_context)
        connection_steps = _road_steps_to_network(
            state,
            action.coord,
            max_steps=4,
            context=current_context,
        )
        immediate_connection = connection_steps is not None and connection_steps <= 1
        site_quality = max(0, city_site_score_for_context(current_context, action.coord) - 60)
        bootstrap_expansion = profile.city_count <= 1 and profile.total_buildings == 0

        value += site_quality * 2
        value += site_budget.food_yield * 26
        value += site_budget.wood_yield * 16
        value += site_budget.ore_yield * 18
        value += site_budget.science_yield * 10
        value += site_budget.food_balance * 180

        future_gap = _composition_gap(
            future.connected_city_count,
            future.connected_inland_count,
        )
        value += (profile.composition_gap - future_gap) * 1000

        if profile.development_saturated:
            value += 140
            value += profile.tech_count * 18

        if connection_steps is None:
            value -= 420
        else:
            value += max(0, 5 - connection_steps) * 120
            if immediate_connection:
                value += 180

        if future_budget is not None:
            value -= max(0, future_budget.pressure) * 110
            if future_budget.starving:
                value -= 900
            if future_budget.city_count == 1:
                value += site_budget.food_balance * 80
                if site_budget.food_balance < 0:
                    value -= 420 + (abs(site_budget.food_balance) * 220)
            else:
                value += max(0, profile.network_count - future.network_count) * 120

        if stage == STAGE_RESCUE:
            if not immediate_connection and site_budget.food_balance < 1:
                value -= 720
            if future_budget is not None and future_budget.city_count == 1:
                value -= 360
            if not immediate_connection and not bootstrap_expansion:
                value -= 1200
            if future.network_count > profile.network_count:
                value -= 520
            if (
                not bootstrap_expansion
                and (rescue_recovery is None or not rescue_recovery.effective)
            ):
                value -= 1200
            else:
                value += max(0, rescue_recovery.starving_delta) * 260
                value += max(0, rescue_recovery.network_delta) * 200
                value += max(0, rescue_recovery.isolated_delta) * 160
        elif stage == STAGE_CONSOLIDATE:
            if connection_steps is None or connection_steps > 2:
                value -= 360
            if future_budget is not None and future_budget.city_count == 1:
                value -= 240
        elif stage == STAGE_FILL and future_budget is not None and future_budget.city_count == 1:
            value -= 220

        if profile.infrastructure_gap > 0:
            value -= profile.infrastructure_gap * 70
        if profile.total_buildings < profile.city_count * 1.8:
            value -= int((profile.city_count * 1.8 - profile.total_buildings) * 140)
        if profile.buildings_per_city < 1.4:
            value -= 180
        if profile.total_buildings + 4 < profile.city_count * 2:
            value -= 240
        if profile.missing_unlocked_buildings:
            value -= 220
        if profile.tech_count < len(TechType):
            value -= 120
        if profile.total_food < profile.food_buffer_target:
            value -= 220
        return value

    def _score_skip_action(self, profile: GreedyStateProfile, stage: str) -> int:
        value = -220
        if profile.breakdown_building_utilization < 0:
            value -= 160
        if profile.tech_count < len(TechType):
            value -= 140
        if profile.infrastructure_gap > 0:
            value -= min(260, profile.infrastructure_gap * 35)
        if stage in {STAGE_RESCUE, STAGE_CONSOLIDATE}:
            value -= 120
        return value


def _build_state_profile(
    state: GameState,
    context: HeuristicContext | None = None,
) -> GreedyStateProfile:
    breakdown = score_breakdown(state)
    resources = context_total_resources(context) if context is not None else total_resources(state)
    total_buildings = building_count(state)
    city_count = len(state.cities)
    food_buffer_target = city_count * FOOD_CONSUMPTION_PER_CITY * 3
    connected_cities, connected_inland = _connected_city_mix(state, context)
    terrain_counts = (
        context_city_terrain_counts(context) if context is not None else city_terrain_counts(state)
    )
    wood_target, ore_target = material_targets(state)
    current_tech_count = tech_count(state)
    missing_unlocked_buildings = _has_missing_unlocked_buildings(state, context)
    pressure = max(
        (
            context_city_network_pressure(context, network.network_id)
            if context is not None
            else city_network_pressure(network)
            for network in state.networks.values()
        ),
        default=0,
    )
    starvation_count = starving_network_count(state)
    return GreedyStateProfile(
        breakdown_total=breakdown.total,
        breakdown_building_utilization=breakdown.building_utilization_score,
        breakdown_building_mismatch_penalty=breakdown.building_mismatch_penalty,
        breakdown_city_composition_bonus=breakdown.city_composition_bonus,
        breakdown_starving_network_penalty=breakdown.starving_network_penalty,
        breakdown_fragmented_network_penalty=breakdown.fragmented_network_penalty,
        total_food=resources.food,
        total_wood=resources.wood,
        total_ore=resources.ore,
        total_science=resources.science,
        total_buildings=total_buildings,
        city_count=city_count,
        network_count=len(state.networks),
        turns_remaining=max(0, state.config.turn_limit - state.turn + 1),
        buildings_per_city=total_buildings / max(1, city_count),
        infrastructure_gap=max(0, city_count - total_buildings),
        food_buffer_target=food_buffer_target,
        connected_city_count=connected_city_count(state),
        isolated_city_count=isolated_city_count(state),
        starving_network_count=starvation_count,
        largest_network_size=largest_network_size(state),
        tech_count=current_tech_count,
        missing_unlocked_buildings=missing_unlocked_buildings,
        connected_inland_count=connected_inland,
        composition_gap=_composition_gap(connected_cities, connected_inland),
        development_saturated=(
            city_count > 0
            and current_tech_count == len(TechType)
            and not missing_unlocked_buildings
            and total_buildings >= city_count * 4
            and resources.food >= max(1, food_buffer_target)
        ),
        pressure=pressure,
        food_crisis=resources.food < -(city_count * FOOD_CONSUMPTION_PER_CITY)
        or pressure > FOOD_CONSUMPTION_PER_CITY * 3,
        wood_target=wood_target,
        ore_target=ore_target,
        forest_city_count=terrain_counts[TerrainType.FOREST],
        mountain_city_count=terrain_counts[TerrainType.MOUNTAIN],
        plain_city_count=terrain_counts[TerrainType.PLAIN],
    )


def _get_simulated_evaluation(
    state: GameState,
    action: Action,
    profile: GreedyStateProfile,
    evaluations: dict[Action, SimulatedEvaluation],
) -> SimulatedEvaluation:
    if action in evaluations:
        return evaluations[action]

    simulated = simulate_action(state, action)
    future_context = build_heuristic_context(simulated)
    future_profile = _build_state_profile(simulated, future_context)
    evaluation = SimulatedEvaluation(
        future_context=future_context,
        future_profile=future_profile,
        future_resources=context_total_resources(future_context),
        future_budget=_future_network_budget(simulated, action, future_context),
        rescue_recovery=_rescue_recovery(profile, future_profile),
    )
    evaluations[action] = evaluation
    return evaluation


def _decision_context(
    *,
    state: GameState,
    action: Action,
    stage: str,
    priority: str,
    best_value: int,
    profile: GreedyStateProfile,
    current_context: HeuristicContext,
    evaluation: SimulatedEvaluation,
) -> dict[str, object]:
    future_profile = evaluation.future_profile
    rescue_recovery = evaluation.rescue_recovery
    score_delta = future_profile.breakdown_total - profile.breakdown_total
    site_budget = (
        _site_budget(state, action.coord, current_context)
        if action.coord is not None
        else None
    )
    future_budget = evaluation.future_budget
    connection_steps = (
        _road_steps_to_network(state, action.coord, max_steps=4, context=current_context)
        if action.action_type is ActionType.BUILD_CITY and action.coord is not None
        else None
    )

    context: dict[str, object] = {
        "greedy_stage": stage,
        "greedy_priority": priority,
        "greedy_best_action_type": action.action_type.value,
        "greedy_best_score": round(best_value / 10, 1),
        "greedy_best_delta_score": score_delta,
        "greedy_food_pressure": profile.pressure,
        "greedy_starving_networks": profile.starving_network_count,
        "greedy_connected_cities": profile.connected_city_count,
        "greedy_total_food": profile.total_food,
        "greedy_network_count": profile.network_count,
        "greedy_global_starving_delta": rescue_recovery.starving_delta,
        "greedy_global_network_delta": rescue_recovery.network_delta,
        "greedy_global_isolation_delta": rescue_recovery.isolated_delta,
        "greedy_rescue_effective": rescue_recovery.effective,
        "greedy_score_breakdown": _score_breakdown_dict(score_breakdown(state)),
    }
    if connection_steps is not None:
        context["greedy_best_connection_steps"] = connection_steps
    if site_budget is not None:
        context["greedy_best_site_budget"] = _site_budget_dict(site_budget)
    if future_budget is not None:
        context["greedy_best_future_network_budget"] = _network_budget_dict(future_budget)
        context["greedy_best_future_network_starving"] = future_budget.starving
    return context


def _build_candidate_catalog(
    state: GameState,
    groups: dict[ActionType, list[Action]],
    context: HeuristicContext,
) -> CandidateCatalog:
    city_actions = sorted(
        (
            action
            for action in groups.get(ActionType.BUILD_CITY, [])
            if action.coord is not None
        ),
        key=lambda action: (
            -city_site_score_for_context(context, _action_coord(action)),
            _action_coord(action),
        ),
    )
    resource_city_actions = sorted(
        city_actions,
        key=lambda action: (
            -city_expansion_score_for_context(context, _action_coord(action)),
            _action_coord(action),
        ),
    )
    forest_city_actions = _city_actions_on_terrain(state, resource_city_actions, TerrainType.FOREST)
    mountain_city_actions = _city_actions_on_terrain(
        state,
        resource_city_actions,
        TerrainType.MOUNTAIN,
    )
    plain_city_actions = _city_actions_on_terrain(state, resource_city_actions, TerrainType.PLAIN)
    interior_gem_actions = [
        action
        for action in city_actions
        if action.coord is not None
        and state.board[action.coord].base_terrain in {TerrainType.FOREST, TerrainType.MOUNTAIN}
        and city_site_score_for_context(context, action.coord) >= 100
    ]
    inland_city_actions = [
        action
        for action in resource_city_actions
        if action.coord is not None and not _is_river_adjacent_site(state, action.coord, context)
    ]
    river_city_actions = [
        action
        for action in resource_city_actions
        if action.coord is not None
        and resource_ring_counts_for_context(context, action.coord)[2] > 0
    ]
    road_actions = sorted(
        (
            action
            for action in groups.get(ActionType.BUILD_ROAD, [])
            if action.coord is not None and _road_structure_score(state, action.coord, context) > 0
        ),
        key=lambda action: (
            -_road_structure_score(state, _action_coord(action), context),
            -road_site_score_for_context(context, _action_coord(action)),
            _action_coord(action),
        ),
    )
    building_actions = sorted(
        groups.get(ActionType.BUILD_BUILDING, []),
        key=lambda action: (
            -building_action_score(state, action),
            city_key(state.cities[action.city_id])
            if action.city_id is not None
            else (0, (0, 0), 0),
        ),
    )
    gap_building_actions = [
        action for action in building_actions if _is_gap_build_action(state, action, context)
    ]
    research_actions = sorted(
        groups.get(ActionType.RESEARCH_TECH, []),
        key=lambda action: (
            -research_action_score(state, action),
            TECH_UNLOCK_PRIORITY.index(action.tech_type)
            if action.tech_type is not None
            else len(TECH_UNLOCK_PRIORITY),
        ),
    )
    return CandidateCatalog(
        city_actions=city_actions,
        resource_city_actions=resource_city_actions,
        forest_city_actions=forest_city_actions,
        mountain_city_actions=mountain_city_actions,
        plain_city_actions=plain_city_actions,
        interior_gem_actions=interior_gem_actions,
        inland_city_actions=inland_city_actions,
        river_city_actions=river_city_actions,
        road_actions=road_actions,
        building_actions=building_actions,
        gap_building_actions=gap_building_actions,
        research_actions=research_actions,
    )


def _candidate_limits(
    state: GameState,
    profile: GreedyStateProfile,
    stage: str,
    research_action_count: int,
) -> CandidateLimits:
    city_limit = min(10, MAX_CITY_CANDIDATES + max(0, (state.config.map_size - 16) // 4))
    road_limit = min(6, max(2, len(state.networks) + 1))
    resource_city_limit = min(
        min(6, MAX_RESOURCE_CITY_CANDIDATES + max(0, state.config.map_size - 20)),
        city_limit,
    )
    building_limit = min(14, MAX_BUILDING_CANDIDATES + max(0, profile.city_count // 8))
    research_limit = min(max(2, len(state.networks) + 1), research_action_count)

    if stage == STAGE_RESCUE:
        city_limit = min(2, city_limit)
        resource_city_limit = min(2, resource_city_limit)
        road_limit = min(10, road_limit + 3)
        building_limit = min(18, building_limit + 4)
        research_limit = min(max(3, len(state.networks) + 1), research_action_count)
    elif stage == STAGE_CONSOLIDATE:
        city_limit = min(3, city_limit)
        resource_city_limit = min(2, resource_city_limit)
        road_limit = min(9, road_limit + 2)
        building_limit = min(18, building_limit + 2)
        research_limit = min(max(3, len(state.networks) + 1), research_action_count)
    elif stage == STAGE_FILL:
        city_limit = max(1, city_limit - 3)
        resource_city_limit = max(1, resource_city_limit - 2)
        building_limit = min(18, building_limit + 4)
        research_limit = min(max(3, len(state.networks) + 1), research_action_count)

    if profile.turns_remaining <= 40:
        city_limit = max(1, city_limit - 1)
        resource_city_limit = max(1, resource_city_limit - 1)
        building_limit = min(18, building_limit + 2)
    if profile.tech_count < len(TechType):
        research_limit = min(max(3, len(state.networks) + 2), research_action_count)
    if profile.missing_unlocked_buildings:
        city_limit = max(1, city_limit - 1)
        resource_city_limit = max(1, resource_city_limit - 1)
        building_limit = min(20, building_limit + 2)
    if profile.isolated_city_count >= 2:
        city_limit = min(city_limit, 1)
        resource_city_limit = min(resource_city_limit, 1)
        road_limit = min(10, road_limit + 2)

    return CandidateLimits(
        city_limit=city_limit,
        road_limit=road_limit,
        resource_city_limit=resource_city_limit,
        building_limit=building_limit,
        research_limit=research_limit,
    )


def _select_stage(profile: GreedyStateProfile) -> str:
    if profile.starving_network_count > 0 or profile.food_crisis or profile.total_food < 0:
        return STAGE_RESCUE
    if (
        profile.isolated_city_count > 0
        or profile.network_count > max(1, profile.city_count // 4)
        or profile.missing_unlocked_buildings
    ):
        return STAGE_CONSOLIDATE
    if profile.development_saturated or profile.turns_remaining <= 18:
        return STAGE_FILL
    return STAGE_EXPAND


def _stage_filter_city_actions(
    state: GameState,
    actions: list[Action],
    stage: str,
    profile: GreedyStateProfile,
    limit: int,
    context: HeuristicContext,
) -> list[Action]:
    selected: list[Action] = []
    for action in actions:
        if action.coord is None:
            continue
        if not _city_action_allowed_in_stage(state, action.coord, stage, profile, context):
            continue
        selected.append(action)
        if len(selected) >= limit:
            break
    return selected


def _city_action_allowed_in_stage(
    state: GameState,
    coord: Coord,
    stage: str,
    profile: GreedyStateProfile,
    context: HeuristicContext,
) -> bool:
    site_budget = _site_budget(state, coord, context)
    connection_steps = _road_steps_to_network(state, coord, max_steps=4, context=context)
    immediate_connection = connection_steps is not None and connection_steps <= 1
    site_value = city_site_score_for_context(context, coord)
    bootstrap_expansion = profile.city_count <= 1 and profile.total_buildings == 0

    if stage == STAGE_RESCUE:
        return immediate_connection or (
            bootstrap_expansion and site_budget.food_balance >= 1 and site_value >= 110
        )
    if stage == STAGE_CONSOLIDATE:
        return immediate_connection or (
            connection_steps is not None
            and connection_steps <= 2
            and site_budget.food_balance >= 0
            and site_value >= 100
        )
    if stage == STAGE_FILL:
        return immediate_connection or site_budget.food_balance >= 1 or site_value >= 140
    if profile.network_count > 2 and connection_steps is None and site_budget.food_balance < 0:
        return False
    return immediate_connection or site_budget.food_balance >= -1 or site_value >= 110


def _site_budget(
    state: GameState,
    coord: Coord,
    context: HeuristicContext | None = None,
) -> SiteBudget:
    if context is not None and coord in context.site_budgets:
        return cast(SiteBudget, context.site_budgets[coord])

    food_yield = 0
    wood_yield = 0
    ore_yield = 0
    science_yield = 0

    center_terrain = state.board[coord].base_terrain
    for resource_type, amount in CITY_CENTER_YIELDS[center_terrain].items():
        if resource_type is ResourceType.FOOD:
            food_yield += amount
        elif resource_type is ResourceType.WOOD:
            wood_yield += amount
        elif resource_type is ResourceType.ORE:
            ore_yield += amount
        elif resource_type is ResourceType.SCIENCE:
            science_yield += amount

    for neighbor in moore_neighbors(coord):
        tile = state.board.get(neighbor)
        if tile is None or tile.occupant is not OccupantType.NONE:
            continue
        for resource_type, amount in TERRAIN_YIELDS[tile.base_terrain].items():
            if resource_type is ResourceType.FOOD:
                food_yield += amount
            elif resource_type is ResourceType.WOOD:
                wood_yield += amount
            elif resource_type is ResourceType.ORE:
                ore_yield += amount
            elif resource_type is ResourceType.SCIENCE:
                science_yield += amount

    budget = SiteBudget(
        food_yield=food_yield,
        wood_yield=wood_yield,
        ore_yield=ore_yield,
        science_yield=science_yield,
        food_balance=food_yield - FOOD_CONSUMPTION_PER_CITY,
    )
    if context is not None:
        context.site_budgets[coord] = budget
    return budget


def _future_network_budget(
    simulated: GameState,
    action: Action,
    context: HeuristicContext | None = None,
) -> NetworkBudget | None:
    network_id: int | None = None
    if action.city_id is not None and action.city_id in simulated.cities:
        network_id = simulated.cities[action.city_id].network_id
    elif action.coord is not None:
        passable_map = (
            context_passable_network_map(context)
            if context is not None
            else map_passable_coords_to_networks(simulated)
        )
        network_id = passable_map.get(action.coord)
    if network_id is None:
        return None
    return _network_budget(simulated.networks[network_id])


def _network_budget(network: Network) -> NetworkBudget:
    return NetworkBudget(
        network_id=network.network_id,
        city_count=len(network.city_ids),
        food=network.resources.food,
        wood=network.resources.wood,
        ore=network.resources.ore,
        science=network.resources.science,
        pressure=city_network_pressure(network),
        starving=network.resources.food <= 0,
    )


def _score_breakdown_dict(breakdown: ScoreBreakdown) -> dict[str, int]:
    return {
        "city_score": int(breakdown.city_score),
        "connected_city_score": int(breakdown.connected_city_score),
        "resource_ring_score": int(breakdown.resource_ring_score),
        "river_access_score": int(breakdown.river_access_score),
        "city_composition_bonus": int(breakdown.city_composition_bonus),
        "building_score": int(breakdown.building_score),
        "tech_score": int(breakdown.tech_score),
        "building_utilization_score": int(breakdown.building_utilization_score),
        "food_score": int(breakdown.food_score),
        "wood_score": int(breakdown.wood_score),
        "ore_score": int(breakdown.ore_score),
        "science_score": int(breakdown.science_score),
        "resource_score": int(breakdown.resource_score),
        "library_science_bonus": int(breakdown.library_science_bonus),
        "building_mismatch_penalty": int(breakdown.building_mismatch_penalty),
        "starving_network_penalty": int(breakdown.starving_network_penalty),
        "fragmented_network_penalty": int(breakdown.fragmented_network_penalty),
        "isolated_city_penalty": int(breakdown.isolated_city_penalty),
        "unproductive_road_penalty": int(breakdown.unproductive_road_penalty),
        "total": int(breakdown.total),
    }


def _site_budget_dict(site_budget: SiteBudget) -> dict[str, int]:
    return {
        "food_yield": site_budget.food_yield,
        "wood_yield": site_budget.wood_yield,
        "ore_yield": site_budget.ore_yield,
        "science_yield": site_budget.science_yield,
        "food_balance": site_budget.food_balance,
        "total_yield": site_budget.total_yield,
    }


def _network_budget_dict(network_budget: NetworkBudget) -> dict[str, int]:
    return {
        "network_id": network_budget.network_id,
        "city_count": network_budget.city_count,
        "food": network_budget.food,
        "wood": network_budget.wood,
        "ore": network_budget.ore,
        "science": network_budget.science,
        "pressure": network_budget.pressure,
    }


def _stage_action_bias(stage: str, action: Action) -> int:
    if stage == STAGE_RESCUE:
        weights = {
            ActionType.BUILD_CITY: -280,
            ActionType.BUILD_ROAD: 220,
            ActionType.BUILD_BUILDING: 260,
            ActionType.RESEARCH_TECH: 140,
            ActionType.SKIP: -180,
        }
    elif stage == STAGE_CONSOLIDATE:
        weights = {
            ActionType.BUILD_CITY: -140,
            ActionType.BUILD_ROAD: 180,
            ActionType.BUILD_BUILDING: 140,
            ActionType.RESEARCH_TECH: 90,
            ActionType.SKIP: -100,
        }
    elif stage == STAGE_FILL:
        weights = {
            ActionType.BUILD_CITY: -80,
            ActionType.BUILD_ROAD: 40,
            ActionType.BUILD_BUILDING: 180,
            ActionType.RESEARCH_TECH: 130,
            ActionType.SKIP: -120,
        }
    else:
        weights = {
            ActionType.BUILD_CITY: 140,
            ActionType.BUILD_ROAD: 70,
            ActionType.BUILD_BUILDING: 40,
            ActionType.RESEARCH_TECH: 30,
            ActionType.SKIP: -80,
        }
    return weights[action.action_type]


def _city_actions_on_terrain(
    state: GameState,
    actions: list[Action],
    terrain: TerrainType,
) -> list[Action]:
    return [
        action
        for action in actions
        if action.coord is not None and state.board[action.coord].base_terrain is terrain
    ]


def _dedupe_actions(actions: list[Action]) -> list[Action]:
    deduped: list[Action] = []
    seen: set[Action] = set()
    for action in actions:
        if action not in seen:
            deduped.append(action)
            seen.add(action)
    return deduped


def _priority_label(action: Action) -> str:
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


def _action_coord(action: Action) -> Coord:
    assert action.coord is not None
    return action.coord


def _is_river_adjacent_site(
    state: GameState,
    coord: Coord,
    context: HeuristicContext | None = None,
) -> bool:
    if context is not None:
        return context_is_river_adjacent_site(context, coord)
    return any(
        (tile := state.board.get(neighbor)) is not None
        and tile.base_terrain is TerrainType.RIVER
        for neighbor in cardinal_neighbors(coord)
    )


def _connected_city_mix(
    state: GameState,
    context: HeuristicContext | None = None,
) -> tuple[int, int]:
    connected = 0
    inland = 0
    for city in state.cities.values():
        network = state.networks[city.network_id]
        if len(network.city_ids) < 2:
            continue
        connected += 1
        if not _is_river_adjacent_site(state, city.coord, context):
            inland += 1
    return connected, inland


def _inland_share(connected_cities: int, connected_inland: int) -> float:
    if connected_cities <= 0:
        return 0.0
    return connected_inland / connected_cities


def _composition_gap(connected_cities: int, connected_inland: int) -> float:
    if connected_cities < 6:
        return max(0.0, TARGET_INLAND_SHARE - _inland_share(connected_cities, connected_inland))
    return abs(_inland_share(connected_cities, connected_inland) - TARGET_INLAND_SHARE)


def _rescue_recovery(
    profile: GreedyStateProfile,
    future: GreedyStateProfile,
) -> RescueRecovery:
    return RescueRecovery(
        starving_delta=profile.starving_network_count - future.starving_network_count,
        network_delta=profile.network_count - future.network_count,
        isolated_delta=profile.isolated_city_count - future.isolated_city_count,
        pressure_delta=profile.pressure - future.pressure,
        starving_penalty_delta=(
            profile.breakdown_starving_network_penalty - future.breakdown_starving_network_penalty
        ),
        fragmented_penalty_delta=(
            profile.breakdown_fragmented_network_penalty
            - future.breakdown_fragmented_network_penalty
        ),
    )


def _road_steps_to_network(
    state: GameState,
    coord: Coord,
    max_steps: int,
    context: HeuristicContext | None = None,
) -> int | None:
    if context is not None and (coord, max_steps) in context.road_steps:
        return context.road_steps[(coord, max_steps)]

    passable_map = (
        context_passable_network_map(context)
        if context is not None
        else map_passable_coords_to_networks(state)
    )
    if coord in passable_map:
        if context is not None:
            context.road_steps[(coord, max_steps)] = 0
        return 0

    frontier: deque[tuple[Coord, int]] = deque([(coord, 0)])
    seen = {coord}
    while frontier:
        current, steps = frontier.popleft()
        if steps >= max_steps:
            continue
        for neighbor in cardinal_neighbors(current):
            if neighbor in seen:
                continue
            tile = state.board.get(neighbor)
            if tile is None:
                continue
            if neighbor in passable_map:
                result = steps + 1
                if context is not None:
                    context.road_steps[(coord, max_steps)] = result
                return result
            if tile.occupant is not OccupantType.NONE:
                continue
            if tile.base_terrain not in {
                TerrainType.PLAIN,
                TerrainType.FOREST,
                TerrainType.MOUNTAIN,
                TerrainType.RIVER,
            }:
                continue
            seen.add(neighbor)
            frontier.append((neighbor, steps + 1))
    if context is not None:
        context.road_steps[(coord, max_steps)] = None
    return None


def _has_missing_unlocked_buildings(
    state: GameState,
    context: HeuristicContext | None = None,
) -> bool:
    return any(
        _network_missing_building_types(state, network_id, context)
        for network_id in state.networks
    )


def _network_missing_building_types(
    state: GameState,
    network_id: int,
    context: HeuristicContext | None = None,
) -> set[BuildingType]:
    if context is not None:
        return context_network_missing_building_types(context, network_id)

    network = state.networks[network_id]
    missing: set[BuildingType] = set()
    for tech_type in network.unlocked_techs:
        building_type = TECH_UNLOCK_PRIORITY_TO_BUILDING[tech_type]
        total = sum(
            state.cities[city_id].buildings.for_type(building_type)
            for city_id in network.city_ids
        )
        if total == 0:
            missing.add(building_type)
    return missing


def _is_gap_build_action(
    state: GameState,
    action: Action,
    context: HeuristicContext | None = None,
) -> bool:
    if action.city_id is None or action.building_type is None:
        return False
    city = state.cities[action.city_id]
    return action.building_type in _network_missing_building_types(state, city.network_id, context)


def _road_structure_score(
    state: GameState,
    coord: Coord,
    context: HeuristicContext | None = None,
) -> int:
    structural_score = 0
    passable_map = (
        context_passable_network_map(context)
        if context is not None
        else map_passable_coords_to_networks(state)
    )
    adjacent_network_ids = {
        passable_map[neighbor]
        for neighbor in cardinal_neighbors(coord)
        if neighbor in passable_map
    }
    if adjacent_network_ids:
        structural_score += 2
    if len(adjacent_network_ids) >= 2:
        structural_score += 4 + sum(
            len(state.networks[network_id].city_ids)
            for network_id in adjacent_network_ids
        ) // 2
    if any(len(state.networks[network_id].city_ids) == 1 for network_id in adjacent_network_ids):
        structural_score += 3
    for neighbor in moore_neighbors(coord):
        tile = state.board.get(neighbor)
        if tile is None or tile.occupant is not OccupantType.NONE:
            continue
        if tile.base_terrain not in {TerrainType.PLAIN, TerrainType.FOREST, TerrainType.MOUNTAIN}:
            continue
        site_score = (
            city_site_score_for_context(context, neighbor)
            if context is not None
            else city_site_score(state, neighbor)
        )
        if site_score < 120:
            continue
        has_prior_access = any(
            (adjacent := state.board.get(n2)) is not None
            and (
                adjacent.occupant in {OccupantType.CITY, OccupantType.ROAD}
                or adjacent.base_terrain is TerrainType.RIVER
            )
            for n2 in cardinal_neighbors(neighbor)
            if n2 != coord
        )
        if not has_prior_access:
            structural_score += 2
            break
    return structural_score


TECH_UNLOCK_PRIORITY_TO_BUILDING: dict[TechType, BuildingType] = {
    TechType.AGRICULTURE: BuildingType.FARM,
    TechType.LOGGING: BuildingType.LUMBER_MILL,
    TechType.MINING: BuildingType.MINE,
    TechType.EDUCATION: BuildingType.LIBRARY,
}
