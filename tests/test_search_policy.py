from __future__ import annotations

from dataclasses import replace

import pytest

import microciv.session as session_module
from microciv.ai.greedy import GreedyPolicy
from microciv.ai.search import (
    DEFAULT_SEARCH_BEAM_WIDTH,
    DEFAULT_SEARCH_CANDIDATE_LIMIT,
    DEFAULT_SEARCH_DEPTH,
    DEFAULT_SEARCH_MAX_DEPTH,
    SEARCH_DEPTH_REASON_FOOD_RESCUE,
    SEARCH_DEPTH_REASON_GROWTH_STALL,
    SEARCH_DEPTH_REASON_NETWORK_CONNECT,
    SEARCH_DEPTH_REASON_STEADY,
    SEARCH_INTERVENTION_FOOD_RESCUE,
    RiskProbeResult,
    RiskProfile,
    SearchDepthContext,
    SearchDepthDecision,
    SearchPolicy,
    _bridge_paths_for_state,
    _evaluate_probe_result,
    _regret_guard_decision,
    _route_commitment_guard_reason,
)
from microciv.game.actions import Action, validate_action
from microciv.game.engine import GameEngine
from microciv.game.enums import (
    ActionType,
    BuildingType,
    OccupantType,
    PlaybackMode,
    PolicyType,
    TechType,
    TerrainType,
)
from microciv.game.mapgen import MapGenerator
from microciv.game.models import (
    BuildingCounts,
    City,
    GameConfig,
    GameState,
    Network,
    ResourcePool,
    Road,
    Tile,
)
from microciv.session import GameSession, create_game_session


class TestDepthStrategy:
    def choose_depth(self, context: SearchDepthContext) -> SearchDepthDecision:
        return SearchDepthDecision(depth=context.base_depth + 1, reason="test_deepen")


class TooDeepStrategy:
    def choose_depth(self, context: SearchDepthContext) -> SearchDepthDecision:
        return SearchDepthDecision(depth=context.max_depth + 1, reason="too_deep")


def test_search_policy_returns_legal_action_and_default_diagnostics() -> None:
    state = _mixed_action_state()
    policy = SearchPolicy()

    action = policy.select_action(state)
    context = policy.explain_decision(state)

    assert validate_action(state, action).is_valid
    assert action.action_type is not ActionType.SKIP
    assert context["search_mode"] == "expand"
    assert context["search_depth"] == DEFAULT_SEARCH_DEPTH
    assert isinstance(context["search_actual_depth"], int)
    assert context["search_base_depth"] == DEFAULT_SEARCH_DEPTH
    assert context["search_max_depth"] == DEFAULT_SEARCH_MAX_DEPTH
    assert context["search_depth_reason"] == SEARCH_DEPTH_REASON_STEADY
    assert isinstance(context["search_deep_search_enabled"], bool)
    assert isinstance(context["search_planning_mode"], str)
    assert isinstance(context["search_planning_reason"], str)
    assert context["search_beam_width"] == DEFAULT_SEARCH_BEAM_WIDTH
    assert context["search_candidate_limit"] == DEFAULT_SEARCH_CANDIDATE_LIMIT
    assert context["search_root_legal_skip_count"] == 1
    assert context["search_root_candidate_skip_count"] == 0
    assert context["search_root_candidate_build_city_count"] == 0
    assert context["search_nodes_expanded"] == 0
    assert context["search_candidates_considered"] >= context["search_leaf_count"]
    assert context["search_leaf_count"] == 0
    assert context["search_planning_mode"] == "greedy_passthrough"
    assert context["search_intervention_trigger"] == "none"
    assert context["search_overrode_greedy"] is False
    assert context["search_probe_rejected_reason"] == "healthy_greedy_passthrough"
    assert context["search_greedy_veto_reason"] is None
    assert context["search_regret_guard_reason"] is None
    assert isinstance(context["search_hard_risk_improvement"], bool)
    assert isinstance(context["search_selected_score_gap_vs_greedy_after_action"], int)
    assert context["search_selected_city_site_delta_vs_greedy"] is None or isinstance(
        context["search_selected_city_site_delta_vs_greedy"], int
    )
    assert context["search_route_plain_cost"] is None or isinstance(
        context["search_route_plain_cost"], int
    )
    assert context["search_route_progress_delta"] is None or isinstance(
        context["search_route_progress_delta"], int
    )
    assert isinstance(context["search_best_value"], int)
    assert isinstance(context["search_value_components"], dict)
    assert isinstance(context["search_sequence_adjustment"], int)
    assert context["search_dominant_pressure"] is None or isinstance(
        context["search_dominant_pressure"], str
    )
    assert isinstance(context["search_dominant_pressure_value"], int)
    assert isinstance(context["search_risk_pressure_total"], int)
    assert isinstance(context["search_is_risk_dominated"], bool)
    assert isinstance(context["search_is_sequence_adjusted"], bool)
    assert isinstance(context["search_best_score_total"], int)
    assert isinstance(context["search_best_food_pressure"], int)
    assert isinstance(context["search_best_starving_turns"], int)
    assert isinstance(context["search_root_candidate_cut_ratio"], float)
    assert isinstance(context["search_root_safe_city_candidate_count"], int)
    assert isinstance(context["search_root_effective_connection_road_candidate_count"], int)
    assert isinstance(context["search_root_rescue_candidate_count"], int)
    assert context["search_root_chosen_rank"] is None
    assert context["search_root_chosen_value"] is None
    assert context["search_root_best_value"] is None
    assert context["search_root_value_margin"] is None
    assert context["search_root_best_action_type"] is None
    assert isinstance(context["search_root_chosen_action_type"], str)
    assert isinstance(context["search_delta_food_pressure"], int)
    assert isinstance(context["search_delta_worst_network_food_pressure"], int)
    assert isinstance(context["search_delta_min_network_food"], int)
    assert isinstance(context["search_delta_connected_city_count"], int)
    assert isinstance(context["search_delta_road_overbuild"], int)
    assert isinstance(context["search_road_merges_networks"], bool)
    assert isinstance(context["search_road_is_redundant"], bool)
    assert context["search_city_food_capacity_after_action"] is None or isinstance(
        context["search_city_food_capacity_after_action"], int
    )
    assert context["search_city_local_plain_capacity"] is None or isinstance(
        context["search_city_local_plain_capacity"], int
    )
    assert context["search_route_target_network_id"] is None or isinstance(
        context["search_route_target_network_id"], int
    )
    assert context["search_route_remaining_steps"] is None or isinstance(
        context["search_route_remaining_steps"], int
    )
    assert isinstance(context["search_route_committed"], bool)
    assert isinstance(context["search_greedy_action_type"], str)
    assert isinstance(context["search_matches_greedy_action"], bool)
    assert isinstance(context["search_greedy_action_in_root_candidates"], bool)
    assert isinstance(context["search_min_network_food_after_action"], int)
    assert isinstance(context["search_worst_network_food_pressure_after_action"], int)
    assert isinstance(context["search_profile_city_count"], int)
    assert isinstance(context["search_profile_safe_expansion_deficit"], int)
    assert isinstance(context["search_greedy_after_score_total"], int)
    assert isinstance(context["search_selected_after_score_total"], int)
    assert isinstance(context["search_simulation_cache_hits"], int)
    assert isinstance(context["search_simulation_cache_misses"], int)
    if action.action_type is ActionType.BUILD_CITY:
        assert isinstance(context["search_chosen_city_site_score"], int)
        assert isinstance(context["search_chosen_city_resource_ring_bonus"], int)
        assert isinstance(context["search_chosen_city_food_balance"], int)
    best_sequence = context["search_best_sequence"]
    assert isinstance(best_sequence, list)
    assert best_sequence
    assert _entry_matches_action(best_sequence[0], action)


def test_search_policy_does_not_mutate_input_state() -> None:
    state = _mixed_action_state()
    before = _state_signature(state)

    SearchPolicy(search_depth=2, search_beam_width=2, search_candidate_limit=5).select_action(state)

    assert _state_signature(state) == before


def test_search_policy_suppresses_early_skip_when_actions_exist() -> None:
    state = _mixed_action_state()
    policy = SearchPolicy(search_depth=2, search_max_depth=2, search_beam_width=2)

    action = policy.select_action(state)
    context = policy.explain_decision(state)

    assert action.action_type is not ActionType.SKIP
    assert context["search_root_candidate_skip_count"] == 0


def test_search_policy_keeps_healthy_expand_state_at_steady_depth() -> None:
    state = _healthy_mild_pressure_expand_state()
    policy = SearchPolicy(
        search_depth=2,
        search_max_depth=6,
        search_beam_width=1,
        search_candidate_limit=5,
    )

    context = policy.explain_decision(state)

    assert context["search_mode"] == "expand"
    assert context["search_depth"] == 2
    assert context["search_planning_mode"] == "greedy_passthrough"
    assert context["search_actual_depth"] == 0
    assert context["search_leaf_count"] == 0
    assert context["search_overrode_greedy"] is False
    assert context["search_deep_search_enabled"] is False
    assert context["search_depth_reason"] == SEARCH_DEPTH_REASON_STEADY


def test_search_policy_healthy_expand_uses_greedy_city_anchor() -> None:
    state = _healthy_mild_pressure_expand_state()
    policy = SearchPolicy(
        search_depth=2,
        search_max_depth=6,
        search_beam_width=1,
        search_candidate_limit=5,
    )

    action = policy.select_action(state)
    context = policy.explain_decision(state)

    assert action.action_type is ActionType.BUILD_CITY
    assert action == GreedyPolicy().select_action(state)
    assert context["search_planning_mode"] == "greedy_passthrough"
    assert context["search_planning_reason"] == "greedy_direct"
    assert context["search_matches_greedy_action"] is True
    assert context["search_greedy_action_in_root_candidates"] is False
    assert context["search_chosen_city_site_score_delta_vs_greedy"] == 0


def test_greedy_plan_snapshot_best_action_matches_select_action() -> None:
    state = _mixed_action_state()
    policy = GreedyPolicy()

    snapshot = policy.plan_for_search(state)

    assert snapshot.action == policy.select_action(state)
    assert snapshot.context == policy.explain_decision(state)
    assert snapshot.selected_candidates
    assert snapshot.action in snapshot.selected_candidates


def test_search_policy_food_rescue_probe_rejects_tiny_integrated_improvement() -> None:
    state = _food_rescue_override_state()
    greedy_action = GreedyPolicy().select_action(state)
    policy = SearchPolicy()

    action = policy.select_action(state)
    context = policy.explain_decision(state)

    assert action == greedy_action
    assert context["search_planning_mode"] == "beam_search"
    assert context["search_intervention_trigger"] == "food_rescue_probe"
    assert context["search_overrode_greedy"] is False
    assert context["search_probe_accepted_reason"] is None
    assert context["search_probe_rejected_reason"] in {
        "food_rescue_gate_failed",
        "selected_matches_greedy",
    }
    assert context["search_leaf_count"] > 0
    assert (
        context["search_greedy_after_food_pressure"]
        == context["search_selected_after_food_pressure"]
    )


def test_food_rescue_probe_rejects_tiny_pressure_improvement() -> None:
    root = RiskProfile(
        score_total=1000,
        starving_network_count=1,
        food_pressure=44,
        min_network_food=-2,
        network_count=2,
        connected_city_count=3,
        isolated_city_count=1,
    )
    greedy_after = RiskProfile(
        score_total=1116,
        starving_network_count=1,
        food_pressure=43,
        min_network_food=-1,
        network_count=2,
        connected_city_count=3,
        isolated_city_count=1,
    )
    tiny_improvement_after = RiskProfile(
        score_total=1116,
        starving_network_count=1,
        food_pressure=42,
        min_network_food=0,
        network_count=2,
        connected_city_count=3,
        isolated_city_count=1,
    )
    clear_improvement_after = RiskProfile(
        score_total=1116,
        starving_network_count=1,
        food_pressure=39,
        min_network_food=2,
        network_count=2,
        connected_city_count=3,
        isolated_city_count=1,
    )

    tiny_result = _evaluate_probe_result(
        trigger=SEARCH_INTERVENTION_FOOD_RESCUE,
        root_risk=root,
        greedy_action=Action.build_building(1, BuildingType.FARM),
        selected_action=Action.build_building(2, BuildingType.FARM),
        greedy_after=greedy_after,
        selected_after=tiny_improvement_after,
    )
    clear_result = _evaluate_probe_result(
        trigger=SEARCH_INTERVENTION_FOOD_RESCUE,
        root_risk=root,
        greedy_action=Action.build_building(1, BuildingType.FARM),
        selected_action=Action.build_building(2, BuildingType.FARM),
        greedy_after=greedy_after,
        selected_after=clear_improvement_after,
    )

    assert tiny_result.accepted is False
    assert tiny_result.rejected_reason == "food_rescue_gate_failed"
    assert clear_result.accepted is True
    assert clear_result.accepted_reason == "reduced_food_pressure"


def test_regret_guard_rejects_low_score_non_risk_override() -> None:
    state = _mixed_action_state()
    state.turn = 20
    greedy_plan = GreedyPolicy().plan_for_search(state)
    root = _risk(
        score_total=1000,
        starving_network_count=0,
        food_pressure=0,
        min_network_food=20,
        network_count=1,
        connected_city_count=1,
        isolated_city_count=0,
    )
    greedy_after = _risk(
        score_total=1100,
        starving_network_count=0,
        food_pressure=0,
        min_network_food=20,
        network_count=1,
        connected_city_count=1,
        isolated_city_count=0,
    )
    selected_after = _risk(
        score_total=1000,
        starving_network_count=0,
        food_pressure=0,
        min_network_food=20,
        network_count=1,
        connected_city_count=1,
        isolated_city_count=0,
    )

    guard = _regret_guard_decision(
        state=state,
        trigger="stall_probe",
        root_risk=root,
        greedy_plan=greedy_plan,
        selected_action=Action.skip(),
        greedy_after=greedy_after,
        selected_after=selected_after,
        selected_sequence_after=selected_after,
        probe_result=RiskProbeResult(True, "test_accept", None),
    )

    assert guard.reason == "regret_score_gap"
    assert guard.hard_risk_improvement is False
    assert guard.selected_score_gap_vs_greedy_after_action == -100


def test_regret_guard_rejects_early_low_quality_city_override() -> None:
    state = _early_city_quality_gap_state()
    greedy_plan = replace(
        GreedyPolicy().plan_for_search(state),
        action=Action.build_city((1, 0)),
    )
    selected_action = Action.build_city((3, 3))
    root = _risk(
        score_total=1000,
        starving_network_count=0,
        food_pressure=0,
        min_network_food=30,
        network_count=1,
        connected_city_count=1,
        isolated_city_count=0,
    )
    greedy_after = _risk(
        score_total=1120,
        starving_network_count=0,
        food_pressure=0,
        min_network_food=30,
        network_count=1,
        connected_city_count=1,
        isolated_city_count=0,
    )
    selected_after = _risk(
        score_total=1110,
        starving_network_count=0,
        food_pressure=0,
        min_network_food=30,
        network_count=1,
        connected_city_count=1,
        isolated_city_count=0,
    )

    guard = _regret_guard_decision(
        state=state,
        trigger="stall_probe",
        root_risk=root,
        greedy_plan=greedy_plan,
        selected_action=selected_action,
        greedy_after=greedy_after,
        selected_after=selected_after,
        selected_sequence_after=selected_after,
        probe_result=RiskProbeResult(True, "test_accept", None),
    )

    assert greedy_plan.action == Action.build_city((1, 0))
    assert guard.reason in {"early_low_city_quality", "city_remote_low_food_capacity"}
    assert guard.hard_risk_improvement is False
    assert guard.selected_city_site_delta_vs_greedy is not None


def test_regret_guard_rejects_remote_low_food_capacity_city() -> None:
    state = _remote_low_food_city_state()
    state.turn = 20
    greedy_plan = GreedyPolicy().plan_for_search(state)
    root = _risk(
        score_total=1000,
        starving_network_count=0,
        food_pressure=0,
        min_network_food=30,
        network_count=1,
        connected_city_count=1,
        isolated_city_count=0,
    )
    after = _risk(
        score_total=1040,
        starving_network_count=0,
        food_pressure=0,
        min_network_food=30,
        network_count=1,
        connected_city_count=1,
        isolated_city_count=0,
    )

    guard = _regret_guard_decision(
        state=state,
        trigger="stall_probe",
        root_risk=root,
        greedy_plan=greedy_plan,
        selected_action=Action.build_city((3, 3)),
        greedy_after=after,
        selected_after=after,
        selected_sequence_after=after,
        probe_result=RiskProbeResult(True, "test_accept", None),
    )

    assert guard.reason == "city_remote_low_food_capacity"


def test_regret_guard_rejects_road_on_last_low_capacity_plain() -> None:
    state = _last_plain_road_state()
    greedy_plan = replace(GreedyPolicy().plan_for_search(state), action=Action.skip())
    root = _risk(
        score_total=1000,
        starving_network_count=0,
        food_pressure=8,
        min_network_food=2,
        network_count=1,
        connected_city_count=0,
        isolated_city_count=1,
    )
    after = _risk(
        score_total=1010,
        starving_network_count=0,
        food_pressure=8,
        min_network_food=2,
        network_count=1,
        connected_city_count=0,
        isolated_city_count=1,
    )

    guard = _regret_guard_decision(
        state=state,
        trigger="stall_probe",
        root_risk=root,
        greedy_plan=greedy_plan,
        selected_action=Action.build_road((0, 1)),
        greedy_after=after,
        selected_after=after,
        selected_sequence_after=after,
        probe_result=RiskProbeResult(True, "test_accept", None),
    )

    assert guard.reason == "road_last_plain_low_capacity"


def test_route_commitment_guard_requires_monotonic_remaining_steps() -> None:
    state = _long_route_bridge_state()
    state.stats.decision_contexts = [
        {
            "search_route_target_network_id": 2,
            "search_route_remaining_steps": 3,
            "search_route_committed": True,
        }
    ]
    root = _risk(
        score_total=1000,
        starving_network_count=1,
        food_pressure=8,
        min_network_food=-8,
        network_count=2,
        connected_city_count=0,
        isolated_city_count=2,
    )
    after = _risk(
        score_total=1010,
        starving_network_count=1,
        food_pressure=8,
        min_network_food=-8,
        network_count=2,
        connected_city_count=0,
        isolated_city_count=2,
    )

    reason = _route_commitment_guard_reason(
        state=state,
        selected_action=Action.build_road((0, 1)),
        selected_after=after,
        root_risk=root,
    )

    assert reason == "route_progress_not_monotonic"


def test_search_policy_stall_probe_rejects_when_gate_fails() -> None:
    state = _mixed_action_state()
    state.stats.decision_contexts = [
        {"turn": 1, "chosen_action_type": "skip"},
        {"turn": 2, "chosen_action_type": "skip"},
        {"turn": 3, "chosen_action_type": "skip"},
    ]
    greedy_action = GreedyPolicy().select_action(state)
    policy = SearchPolicy()

    action = policy.select_action(state)
    context = policy.explain_decision(state)

    assert action == greedy_action
    assert context["search_planning_mode"] == "beam_search"
    assert context["search_intervention_trigger"] == "stall_probe"
    assert context["search_overrode_greedy"] is False
    assert context["search_probe_rejected_reason"] in {
        "stall_gate_failed",
        "selected_matches_greedy",
    }
    assert context["search_leaf_count"] > 0
    assert context["search_simulation_cache_hits"] > 0


def test_search_policy_keeps_multistep_bridge_first_road_candidate() -> None:
    state = _two_step_bridge_state()
    greedy_action = GreedyPolicy().select_action(state)
    policy = SearchPolicy(search_depth=2, search_max_depth=4, search_beam_width=2)

    paths = _bridge_paths_for_state(state)
    action = policy.select_action(state)
    context = policy.explain_decision(state)

    assert paths
    assert paths[0].min_steps == 2
    assert paths[0].actions[0] == Action.build_road((1, 0))
    assert greedy_action != paths[0].actions[0]
    assert action == paths[0].actions[0]
    assert context["search_planning_mode"] == "beam_search"
    assert context["search_bridge_candidate_count"] >= 1
    assert context["search_bridge_min_steps"] == 2
    assert context["search_bridge_progress_after_first_step"] > 0
    assert context["search_route_target_network_id"] == 2
    assert context["search_route_remaining_steps"] == 1
    assert context["search_route_committed"] is True
    assert context["search_route_plain_cost"] == 2
    assert context["search_route_progress_delta"] == 1
    assert context["search_probe_accepted_reason"] in {
        "bridge_sequence_reduced_starving_networks",
        "bridge_sequence_reduced_networks",
        "bridge_sequence_increased_connected_cities",
    }


def test_search_policy_bridge_second_step_reduces_network_risk() -> None:
    state = _two_step_bridge_state()
    policy = SearchPolicy(search_depth=2, search_max_depth=4, search_beam_width=2)
    engine = GameEngine(state)

    first_action = policy.select_action(state)
    assert first_action == Action.build_road((1, 0))
    assert engine.apply_action(first_action).success
    before_network_count = len(state.networks)
    before_isolated = sum(1 for network in state.networks.values() if len(network.city_ids) == 1)

    second_action = policy.select_action(state)
    assert second_action == Action.build_road((1, 1))
    assert engine.apply_action(second_action).success

    after_isolated = sum(1 for network in state.networks.values() if len(network.city_ids) == 1)
    assert len(state.networks) < before_network_count
    assert after_isolated < before_isolated


def test_search_policy_commits_long_bridge_route_after_veto() -> None:
    state = _long_route_bridge_state()
    policy = SearchPolicy(search_depth=2, search_max_depth=4, search_beam_width=2)
    engine = GameEngine(state)

    paths = _bridge_paths_for_state(state)
    first_action = policy.select_action(state)
    first_context = policy.explain_decision(state)

    assert paths
    assert paths[0].min_steps == 5
    assert paths[0].actions[0] == Action.build_road((0, 1))
    assert first_action == Action.build_road((0, 1))
    assert first_context["search_greedy_veto_reason"] == "road_redundant"
    assert first_context["search_route_target_network_id"] == 2
    assert first_context["search_route_remaining_steps"] == 4
    assert first_context["search_route_committed"] is True

    state.stats.decision_contexts.append(first_context)
    assert engine.apply_action(first_action).success

    second_action = policy.select_action(state)
    second_context = policy.explain_decision(state)

    assert second_action == Action.build_road((0, 2))
    assert second_context["search_greedy_veto_reason"] in {
        "route_commitment_deviation",
        None,
    }
    assert second_context["search_route_target_network_id"] == 2
    assert second_context["search_route_remaining_steps"] == 3
    assert second_context["search_route_committed"] is True
    assert second_context["search_route_progress_delta"] == 1


def test_search_policy_recent_food_probe_rejection_does_not_block_worsening_bridge() -> None:
    state = _two_step_bridge_state()
    state.stats.decision_contexts = [
        {
            "search_intervention_trigger": "food_rescue_probe",
            "search_probe_rejected_reason": "food_rescue_gate_failed",
            "search_selected_after_starving_network_count": 1,
            "search_selected_after_food_pressure": 12,
            "search_selected_after_network_count": 2,
            "search_selected_after_isolated_city_count": 2,
        }
    ]
    policy = SearchPolicy(search_depth=2, search_max_depth=4, search_beam_width=2)

    action = policy.select_action(state)
    context = policy.explain_decision(state)

    assert action == Action.build_road((1, 0))
    assert context["search_intervention_trigger"] == "food_rescue_probe"
    assert context["search_probe_rejected_reason"] != "recent_food_rescue_probe_rejected"


def test_search_policy_uses_custom_depth_strategy() -> None:
    state = _mixed_action_state()
    policy = SearchPolicy(
        search_depth=1,
        search_max_depth=2,
        search_beam_width=1,
        search_candidate_limit=3,
        search_depth_strategy=TestDepthStrategy(),
    )

    context = policy.explain_decision(state)

    assert context["search_depth"] == 2
    assert context["search_base_depth"] == 1
    assert context["search_max_depth"] == 2
    assert context["search_depth_reason"] == "test_deepen"


def test_search_policy_uses_fixed_depth_when_max_equals_base() -> None:
    state = _mixed_action_state()
    policy = SearchPolicy(search_depth=2, search_max_depth=2)

    context = policy.explain_decision(state)

    assert context["search_depth"] == 2
    assert context["search_max_depth"] == 2
    assert context["search_depth_reason"] == "fixed"


def test_search_policy_dynamic_depth_prioritizes_food_rescue() -> None:
    state = _mixed_action_state()
    state.networks[1].resources.food = -2
    policy = SearchPolicy(
        search_depth=2,
        search_max_depth=6,
        search_beam_width=1,
        search_candidate_limit=3,
    )

    context = policy.explain_decision(state)

    assert context["search_depth"] == 6
    assert context["search_depth_reason"] == SEARCH_DEPTH_REASON_FOOD_RESCUE


def test_search_policy_dynamic_depth_detects_network_connect_need() -> None:
    state = _two_isolated_city_state()
    policy = SearchPolicy(
        search_depth=2,
        search_max_depth=6,
        search_beam_width=1,
        search_candidate_limit=3,
    )

    context = policy.explain_decision(state)

    assert context["search_depth"] == 5
    assert context["search_depth_reason"] == SEARCH_DEPTH_REASON_NETWORK_CONNECT


def test_search_policy_dynamic_depth_detects_growth_stall() -> None:
    state = _mixed_action_state()
    state.stats.decision_contexts = [
        {"turn": 1, "chosen_action_type": "skip"},
        {"turn": 2, "chosen_action_type": "build_building"},
        {"turn": 3, "chosen_action_type": "skip"},
    ]
    policy = SearchPolicy(
        search_depth=2,
        search_max_depth=6,
        search_beam_width=1,
        search_candidate_limit=3,
    )

    context = policy.explain_decision(state)

    assert context["search_depth"] == 6
    assert context["search_depth_reason"] == SEARCH_DEPTH_REASON_GROWTH_STALL


def test_search_policy_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError, match="search_depth"):
        SearchPolicy(search_depth=0)
    with pytest.raises(ValueError, match="search_beam_width"):
        SearchPolicy(search_beam_width=0)
    with pytest.raises(ValueError, match="search_candidate_limit"):
        SearchPolicy(search_candidate_limit=0)
    with pytest.raises(ValueError, match="search_max_depth"):
        SearchPolicy(search_max_depth=0)
    with pytest.raises(ValueError, match="search_max_depth"):
        SearchPolicy(search_depth=3, search_max_depth=2)


def test_search_policy_rejects_invalid_depth_strategy_result() -> None:
    state = _mixed_action_state()
    policy = SearchPolicy(
        search_depth=1,
        search_max_depth=1,
        search_depth_strategy=TooDeepStrategy(),
    )

    with pytest.raises(ValueError, match="greater than search_max_depth"):
        policy.select_action(state)


def test_search_policy_can_finish_short_fixed_seed_game() -> None:
    config = GameConfig.for_play(seed=1, turn_limit=30, map_size=12)
    generated = MapGenerator().generate(config)
    state = GameState.empty(config)
    state.board = {
        coord: Tile(base_terrain=tile.base_terrain, occupant=tile.occupant)
        for coord, tile in generated.board.items()
    }
    engine = GameEngine(state)
    policy = SearchPolicy(
        search_depth=2,
        search_max_depth=2,
        search_beam_width=2,
        search_candidate_limit=6,
    )

    while not state.is_game_over:
        action = policy.select_action(state)
        validation = validate_action(state, action)
        assert validation.is_valid, validation.message
        result = engine.apply_action(action)
        assert result.success, result.message

    assert state.turn == 30
    assert state.is_game_over is True


def test_create_game_session_constructs_search_policy_from_config() -> None:
    config = GameConfig.for_autoplay(
        map_size=12,
        turn_limit=30,
        policy_type=PolicyType.SEARCH,
        playback_mode=PlaybackMode.SPEED,
        search_depth=2,
        search_max_depth=5,
        search_beam_width=3,
        search_candidate_limit=5,
    )

    session = create_game_session(config)

    assert isinstance(session.policy, SearchPolicy)
    assert session.policy.search_depth == 2
    assert session.policy.search_max_depth == 5
    assert session.policy.search_beam_width == 3
    assert session.policy.search_candidate_limit == 5


def test_step_autoplay_counts_select_action_time_before_recording_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TimedPolicy:
        def select_action(self, state: GameState) -> Action:
            assert state.stats.decision_contexts == []
            return Action.skip()

        def explain_decision(self, state: GameState) -> dict[str, object]:
            assert state.stats.decision_count == 1
            return {"search_nodes_expanded": 99}

    state = GameState.empty(
        GameConfig.for_autoplay(
            map_size=12,
            turn_limit=30,
            policy_type=PolicyType.SEARCH,
            playback_mode=PlaybackMode.SPEED,
        )
    )
    timestamps = iter([10.0, 10.125])
    monkeypatch.setattr(session_module, "perf_counter", lambda: next(timestamps))
    session = GameSession(
        state=state,
        engine=GameEngine(state),
        policy=TimedPolicy(),  # type: ignore[arg-type]
        started_at=0.0,
    )

    session.step_autoplay()

    assert state.stats.decision_count == 1
    assert state.stats.decision_time_ms_total == pytest.approx(125.0)
    assert state.stats.decision_contexts[0]["chosen_action_type"] == "skip"
    assert state.stats.decision_contexts[0]["decision_time_ms"] == pytest.approx(125.0)
    assert state.stats.decision_contexts[0]["search_nodes_expanded"] == 99


def _risk(
    *,
    score_total: int,
    starving_network_count: int,
    food_pressure: int,
    min_network_food: int,
    network_count: int,
    connected_city_count: int,
    isolated_city_count: int,
) -> RiskProfile:
    return RiskProfile(
        score_total=score_total,
        starving_network_count=starving_network_count,
        food_pressure=food_pressure,
        min_network_food=min_network_food,
        network_count=network_count,
        connected_city_count=connected_city_count,
        isolated_city_count=isolated_city_count,
    )


def _mixed_action_state() -> GameState:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.FOREST),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (0, 2): Tile(base_terrain=TerrainType.MOUNTAIN),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN),
        (1, 1): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 2): Tile(base_terrain=TerrainType.RIVER),
        (2, 0): Tile(base_terrain=TerrainType.FOREST),
        (2, 1): Tile(base_terrain=TerrainType.MOUNTAIN),
        (2, 2): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {1: City(city_id=1, coord=(1, 1), founded_turn=1, network_id=1)}
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=50, wood=50, ore=50, science=50),
            unlocked_techs={TechType.AGRICULTURE},
        )
    }
    state.next_city_id = 2
    state.next_network_id = 2
    return state


def _early_city_quality_gap_state() -> GameState:
    state = GameState.empty(GameConfig.for_play(turn_limit=60, map_size=12))
    state.turn = 4
    state.board = {
        (row, col): Tile(base_terrain=TerrainType.MOUNTAIN) for row in range(6) for col in range(6)
    }
    state.board[(0, 0)] = Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY)
    state.board[(0, 1)] = Tile(base_terrain=TerrainType.PLAIN)
    state.board[(1, 0)] = Tile(base_terrain=TerrainType.PLAIN)
    state.board[(1, 1)] = Tile(base_terrain=TerrainType.RIVER)
    state.board[(0, 2)] = Tile(base_terrain=TerrainType.FOREST)
    state.board[(2, 0)] = Tile(base_terrain=TerrainType.FOREST)
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=80, wood=80, ore=80))
    }
    state.next_city_id = 2
    state.next_network_id = 2
    return state


def _remote_low_food_city_state() -> GameState:
    state = GameState.empty(GameConfig.for_play(turn_limit=60, map_size=12))
    state.board = {
        (row, col): Tile(base_terrain=TerrainType.FOREST) for row in range(5) for col in range(5)
    }
    state.board[(0, 0)] = Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY)
    state.board[(0, 1)] = Tile(base_terrain=TerrainType.PLAIN)
    state.board[(1, 0)] = Tile(base_terrain=TerrainType.PLAIN)
    state.board[(1, 1)] = Tile(base_terrain=TerrainType.PLAIN)
    state.board[(3, 3)] = Tile(base_terrain=TerrainType.MOUNTAIN)
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=80, wood=80, ore=80))
    }
    state.next_city_id = 2
    state.next_network_id = 2
    return state


def _last_plain_road_state() -> GameState:
    state = GameState.empty(GameConfig.for_play(turn_limit=40, map_size=12))
    state.turn = 10
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 0): Tile(base_terrain=TerrainType.FOREST),
        (1, 1): Tile(base_terrain=TerrainType.MOUNTAIN),
        (2, 0): Tile(base_terrain=TerrainType.FOREST),
        (2, 1): Tile(base_terrain=TerrainType.MOUNTAIN),
    }
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.networks = {1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=2))}
    state.next_city_id = 2
    state.next_road_id = 1
    state.next_network_id = 2
    return state


def _two_isolated_city_state() -> GameState:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (0, 2): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.FOREST),
        (1, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 2): Tile(base_terrain=TerrainType.MOUNTAIN),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
        2: City(city_id=2, coord=(0, 2), founded_turn=2, network_id=2),
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=40)),
        2: Network(network_id=2, city_ids={2}, resources=ResourcePool(food=40)),
    }
    state.next_city_id = 3
    state.next_network_id = 3
    return state


def _healthy_mild_pressure_expand_state() -> GameState:
    state = GameState.empty(GameConfig.for_play(turn_limit=30))
    state.turn = 5
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN),
        (0, 1): Tile(base_terrain=TerrainType.FOREST),
        (0, 2): Tile(base_terrain=TerrainType.PLAIN),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 1): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.ROAD),
        (1, 2): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (2, 0): Tile(base_terrain=TerrainType.FOREST),
        (2, 1): Tile(base_terrain=TerrainType.MOUNTAIN),
        (2, 2): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {
        1: City(
            city_id=1,
            coord=(1, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(farm=2, lumber_mill=2, mine=2, library=2),
        ),
        2: City(
            city_id=2,
            coord=(1, 2),
            founded_turn=2,
            network_id=1,
            buildings=BuildingCounts(farm=2, lumber_mill=2, mine=2, library=2),
        ),
    }
    state.roads = {1: Road(road_id=1, coord=(1, 1), built_turn=3)}
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1, 2},
            resources=ResourcePool(food=30, wood=120, ore=120, science=0),
            unlocked_techs=set(TechType),
        )
    }
    state.next_city_id = 3
    state.next_road_id = 2
    state.next_network_id = 2
    return state


def _food_rescue_override_state() -> GameState:
    state = GameState.empty(GameConfig.for_play(turn_limit=30))
    state.turn = 6
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 0): Tile(base_terrain=TerrainType.FOREST),
        (1, 1): Tile(base_terrain=TerrainType.MOUNTAIN),
    }
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(),
        )
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=-2, wood=50, ore=50, science=50),
            unlocked_techs={TechType.AGRICULTURE},
        )
    }
    return state


def _two_step_bridge_state() -> GameState:
    state = GameState.empty(GameConfig.for_play(turn_limit=30))
    state.turn = 6
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 2): Tile(base_terrain=TerrainType.FOREST),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN),
        (1, 1): Tile(base_terrain=TerrainType.PLAIN),
        (1, 2): Tile(base_terrain=TerrainType.MOUNTAIN),
        (2, 0): Tile(base_terrain=TerrainType.FOREST),
        (2, 1): Tile(base_terrain=TerrainType.MOUNTAIN),
        (2, 2): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
        2: City(city_id=2, coord=(0, 1), founded_turn=2, network_id=2),
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=-8)),
        2: Network(
            network_id=2,
            city_ids={2},
            resources=ResourcePool(food=80, wood=80, ore=80, science=80),
            unlocked_techs={TechType.AGRICULTURE},
        ),
    }
    state.next_city_id = 3
    state.next_road_id = 1
    state.next_network_id = 3
    return state


def _long_route_bridge_state() -> GameState:
    state = GameState.empty(GameConfig.for_play(turn_limit=40, map_size=18))
    state.turn = 6
    state.board = {
        (row, col): Tile(base_terrain=TerrainType.PLAIN) for row in range(2) for col in range(7)
    }
    state.board[(0, 0)].occupant = OccupantType.CITY
    state.board[(0, 6)].occupant = OccupantType.CITY
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
        2: City(city_id=2, coord=(0, 6), founded_turn=2, network_id=2),
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=-8)),
        2: Network(
            network_id=2,
            city_ids={2},
            resources=ResourcePool(food=100, wood=100, ore=100, science=0),
        ),
    }
    state.next_city_id = 3
    state.next_road_id = 1
    state.next_network_id = 3
    return state


def _entry_matches_action(entry: object, action: Action) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("action_type") != action.action_type.value:
        return False
    if action.coord is not None and (
        entry.get("x") != action.coord[0] or entry.get("y") != action.coord[1]
    ):
        return False
    if action.city_id is not None and entry.get("city_id") != action.city_id:
        return False
    if (
        action.building_type is not None
        and entry.get("building_type") != action.building_type.value
    ):
        return False
    if action.tech_type is not None and entry.get("tech_type") != action.tech_type.value:
        return False
    return True


def _state_signature(state: GameState) -> dict[str, object]:
    return {
        "turn": state.turn,
        "score": state.score,
        "is_game_over": state.is_game_over,
        "board": {
            coord: (tile.base_terrain.value, tile.occupant.value)
            for coord, tile in sorted(state.board.items())
        },
        "cities": {
            city_id: (
                city.coord,
                city.founded_turn,
                city.network_id,
                city.buildings.farm,
                city.buildings.lumber_mill,
                city.buildings.mine,
                city.buildings.library,
            )
            for city_id, city in sorted(state.cities.items())
        },
        "roads": {
            road_id: (road.coord, road.built_turn) for road_id, road in sorted(state.roads.items())
        },
        "networks": {
            network_id: (
                sorted(network.city_ids),
                network.resources.food,
                network.resources.wood,
                network.resources.ore,
                network.resources.science,
                sorted(tech.value for tech in network.unlocked_techs),
                network.consecutive_starving_turns,
            )
            for network_id, network in sorted(state.networks.items())
        },
        "next_ids": (state.next_city_id, state.next_road_id, state.next_network_id),
    }
