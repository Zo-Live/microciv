"""Session helpers for the Textual application."""

from __future__ import annotations

from dataclasses import dataclass

from microciv.ai.baseline import BaselinePolicy
from microciv.ai.policy import Policy
from microciv.game.engine import GameEngine
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


def create_game_session(config: GameConfig) -> GameSession:
    """Create a new playable session from a frozen game config."""
    state = build_state_from_config(config)

    policy: Policy | None = None
    if config.mode.value == "autoplay":
        policy = BaselinePolicy()

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
