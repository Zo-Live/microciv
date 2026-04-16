"""Runtime session helpers shared by the curses UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from microciv.ai.greedy import GreedyPolicy
from microciv.ai.policy import Policy
from microciv.ai.random_policy import RandomPolicy
from microciv.game.actions import Action
from microciv.game.engine import GameEngine
from microciv.game.enums import PolicyType
from microciv.game.mapgen import MapGenerator
from microciv.game.models import GameConfig, GameState, Tile
from microciv.records.models import RecordEntry


@dataclass(slots=True)
class GameSession:
    """In-memory state for a running play or autoplay session."""

    state: GameState
    engine: GameEngine
    policy: Policy | None = None
    saved_record: RecordEntry | None = None
    started_at: float = field(default_factory=perf_counter)

    def apply_action(self, action: Action) -> None:
        """Apply an action and refresh aggregate session timing when the game ends."""
        self.state.stats.record_action(self.state.turn, action)
        self.engine.apply_action(action)
        if self.state.is_game_over:
            self.state.stats.session_elapsed_ms = (perf_counter() - self.started_at) * 1000

    def step_autoplay(self) -> None:
        """Advance a single autoplay turn and record decision timing."""
        if self.policy is None or self.state.is_game_over:
            return
        from microciv.game.actions import ActionType, list_legal_actions
        from microciv.game.scoring import building_count, city_count, tech_count, total_resources

        legal_actions = list_legal_actions(self.state)
        resources = total_resources(self.state)
        self.state.stats.record_turn_snapshot(
            turn=self.state.turn,
            score=self.state.score,
            food=resources.food,
            wood=resources.wood,
            ore=resources.ore,
            science=resources.science,
            city_count=city_count(self.state),
            building_count=building_count(self.state),
            tech_count=tech_count(self.state),
            road_count=len(self.state.roads),
            network_count=len(self.state.networks),
            legal_actions_count=len(legal_actions),
        )
        policy_context = (
            self.policy.explain_decision(self.state)
            if hasattr(self.policy, "explain_decision")
            else None
        )
        self.state.stats.record_decision_context(
            turn=self.state.turn,
            legal_actions_count=len(legal_actions),
            legal_build_city_count=sum(
                1 for a in legal_actions if a.action_type is ActionType.BUILD_CITY
            ),
            legal_build_road_count=sum(
                1 for a in legal_actions if a.action_type is ActionType.BUILD_ROAD
            ),
            legal_build_building_count=sum(
                1 for a in legal_actions if a.action_type is ActionType.BUILD_BUILDING
            ),
            legal_research_tech_count=sum(
                1 for a in legal_actions if a.action_type is ActionType.RESEARCH_TECH
            ),
            legal_skip_count=sum(
                1 for a in legal_actions if a.action_type is ActionType.SKIP
            ),
            policy_context=policy_context,
        )

        decision_started_at = perf_counter()
        action = self.policy.select_action(self.state)
        self.state.stats.record_decision_time((perf_counter() - decision_started_at) * 1000)
        self.apply_action(action)


def create_game_session(config: GameConfig) -> GameSession:
    """Create a new playable session from a frozen game config."""
    state = build_state_from_config(config)

    policy: Policy | None = None
    if config.policy_type is PolicyType.GREEDY:
        policy = GreedyPolicy()
    elif config.policy_type is PolicyType.RANDOM:
        policy = RandomPolicy(seed=config.seed)

    return GameSession(state=state, engine=GameEngine(state), policy=policy)


def build_state_from_config(config: GameConfig) -> GameState:
    """Build a fresh game state with a generated board."""
    generated = MapGenerator().generate(config)
    state = GameState.empty(config)
    state.board = {
        coord: Tile(base_terrain=tile.base_terrain, occupant=tile.occupant)
        for coord, tile in generated.board.items()
    }
    return state


def selected_city_id_for_coord(state: GameState, coord: tuple[int, int] | None) -> int | None:
    """Return the city id at the selected coordinate, if any."""
    if coord is None:
        return None
    for city_id, city in state.cities.items():
        if city.coord == coord:
            return city_id
    return None
