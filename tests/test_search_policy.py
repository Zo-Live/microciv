from __future__ import annotations

import pytest

import microciv.session as session_module
from microciv.ai.search import (
    DEFAULT_SEARCH_BEAM_WIDTH,
    DEFAULT_SEARCH_CANDIDATE_LIMIT,
    DEFAULT_SEARCH_DEPTH,
    SearchDepthContext,
    SearchDepthDecision,
    SearchPolicy,
)
from microciv.game.actions import Action, validate_action
from microciv.game.engine import GameEngine
from microciv.game.enums import OccupantType, PlaybackMode, PolicyType, TechType, TerrainType
from microciv.game.mapgen import MapGenerator
from microciv.game.models import City, GameConfig, GameState, Network, ResourcePool, Tile
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
    assert context["search_depth"] == DEFAULT_SEARCH_DEPTH
    assert context["search_base_depth"] == DEFAULT_SEARCH_DEPTH
    assert context["search_max_depth"] == DEFAULT_SEARCH_DEPTH
    assert context["search_depth_reason"] == "fixed"
    assert context["search_beam_width"] == DEFAULT_SEARCH_BEAM_WIDTH
    assert context["search_candidate_limit"] == DEFAULT_SEARCH_CANDIDATE_LIMIT
    assert context["search_nodes_expanded"] > 0
    assert context["search_candidates_considered"] >= context["search_leaf_count"]
    assert context["search_leaf_count"] > 0
    assert isinstance(context["search_best_value"], int)
    best_sequence = context["search_best_sequence"]
    assert isinstance(best_sequence, list)
    assert best_sequence
    assert _entry_matches_action(best_sequence[0], action)


def test_search_policy_does_not_mutate_input_state() -> None:
    state = _mixed_action_state()
    before = _state_signature(state)

    SearchPolicy(search_depth=2, search_beam_width=2, search_candidate_limit=5).select_action(state)

    assert _state_signature(state) == before


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


def test_search_policy_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError, match="search_depth"):
        SearchPolicy(search_depth=0)
    with pytest.raises(ValueError, match="search_beam_width"):
        SearchPolicy(search_beam_width=0)
    with pytest.raises(ValueError, match="search_candidate_limit"):
        SearchPolicy(search_candidate_limit=0)
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
    policy = SearchPolicy(search_depth=2, search_beam_width=2, search_candidate_limit=6)

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
        search_beam_width=3,
        search_candidate_limit=5,
    )

    session = create_game_session(config)

    assert isinstance(session.policy, SearchPolicy)
    assert session.policy.search_depth == 2
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
    assert state.stats.decision_contexts[0]["search_nodes_expanded"] == 99


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
