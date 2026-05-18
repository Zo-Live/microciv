from __future__ import annotations

from microciv.ai.heuristics import (
    build_heuristic_context,
    future_network_budget,
    site_budget,
)
from microciv.ai.policy import simulate_action
from microciv.ai.search_support import (
    SearchCandidateConfig,
    evaluate_search_leaf,
    generate_search_candidates,
)
from microciv.game.actions import Action, validate_action
from microciv.game.enums import ActionType, OccupantType, TechType, TerrainType
from microciv.game.models import City, GameConfig, GameState, Network, ResourcePool, Tile


def test_search_candidates_are_legal_stable_and_mixed() -> None:
    state = _mixed_action_state()
    config = SearchCandidateConfig(candidate_limit=5)

    candidate_set = generate_search_candidates(state, config)
    repeated = generate_search_candidates(state, config)

    assert len(candidate_set.candidates) <= config.candidate_limit
    assert [candidate.action for candidate in candidate_set.candidates] == [
        candidate.action for candidate in repeated.candidates
    ]
    assert all(
        validate_action(state, candidate.action).is_valid for candidate in candidate_set.candidates
    )
    assert {candidate.action_type for candidate in candidate_set.candidates} == {
        ActionType.BUILD_CITY,
        ActionType.BUILD_ROAD,
        ActionType.BUILD_BUILDING,
        ActionType.RESEARCH_TECH,
        ActionType.SKIP,
    }
    assert candidate_set.legal_action_count >= len(candidate_set.candidates)
    assert candidate_set.legal_counts_by_type[ActionType.SKIP] == 1


def test_search_candidate_limit_one_skips_skip_when_other_actions_exist() -> None:
    state = _mixed_action_state()

    candidate_set = generate_search_candidates(state, SearchCandidateConfig(candidate_limit=1))

    assert len(candidate_set.candidates) == 1
    assert candidate_set.candidates[0].action_type is not ActionType.SKIP


def test_search_candidate_limit_one_returns_skip_when_only_skip_is_legal() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {(0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY)}
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.networks = {1: Network(network_id=1, city_ids={1}, resources=ResourcePool())}

    candidate_set = generate_search_candidates(state, SearchCandidateConfig(candidate_limit=1))

    assert [candidate.action for candidate in candidate_set.candidates] == [Action.skip()]


def test_search_city_candidates_prefer_food_safe_site_over_risky_resource_site() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (row, col): Tile(base_terrain=TerrainType.FOREST)
        for row in range(5)
        for col in range(5)
    }
    for coord in [(3, 3), (3, 4), (4, 3), (4, 4)]:
        state.board[coord] = Tile(base_terrain=TerrainType.PLAIN)
    state.board[(2, 2)] = Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY)
    state.cities = {1: City(city_id=1, coord=(2, 2), founded_turn=1, network_id=1)}
    state.networks = {1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=0))}

    candidate_set = generate_search_candidates(state, SearchCandidateConfig(candidate_limit=30))
    city_candidates = {
        candidate.action.coord: candidate
        for candidate in candidate_set.candidates
        if candidate.action_type is ActionType.BUILD_CITY
    }

    assert city_candidates[(4, 4)].rank_score > city_candidates[(0, 0)].rank_score


def test_budget_helpers_report_site_and_future_network_budget() -> None:
    state = _mixed_action_state()
    context = build_heuristic_context(state)

    budget = site_budget(state, (0, 1), context)

    assert budget.total_yield > 0
    assert context.site_budgets[(0, 1)] is budget

    action = Action.build_city((0, 1))
    simulated = simulate_action(state, action)
    future_context = build_heuristic_context(simulated)
    network_budget = future_network_budget(simulated, action, future_context)

    assert network_budget is not None
    assert network_budget.city_count >= 1
    assert network_budget.food == simulated.networks[network_budget.network_id].resources.food


def test_search_leaf_evaluation_rewards_connected_non_starving_state() -> None:
    connected = _two_city_state(connected=True, food=40)
    isolated = _two_city_state(connected=False, food=40)
    starving = _two_city_state(connected=True, food=-8)

    connected_value = evaluate_search_leaf(connected)
    isolated_value = evaluate_search_leaf(isolated)
    starving_value = evaluate_search_leaf(starving)

    assert connected_value.value > isolated_value.value
    assert connected_value.value > starving_value.value
    assert connected_value.connected_city_count == 2
    assert isolated_value.isolated_city_count == 2
    assert starving_value.starving_network_count == 1


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


def _two_city_state(*, connected: bool, food: int) -> GameState:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.FOREST),
        (0, 2): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.MOUNTAIN),
        (1, 1): Tile(base_terrain=TerrainType.RIVER),
        (1, 2): Tile(base_terrain=TerrainType.PLAIN),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
        2: City(city_id=2, coord=(0, 2), founded_turn=2, network_id=1 if connected else 2),
    }
    if connected:
        state.networks = {
            1: Network(network_id=1, city_ids={1, 2}, resources=ResourcePool(food=food))
        }
    else:
        state.networks = {
            1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=food // 2)),
            2: Network(network_id=2, city_ids={2}, resources=ResourcePool(food=food // 2)),
        }
    return state
