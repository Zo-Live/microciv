"""Shared AI policy interfaces and helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Protocol

from microciv.game.actions import Action, list_legal_actions
from microciv.game.engine import GameEngine
from microciv.game.models import GameState


class Policy(Protocol):
    """A policy that selects the next legal game action."""

    def select_action(self, state: GameState) -> Action:
        """Choose an action for the given game state."""


def get_legal_actions(state: GameState, *, include_skip: bool = True) -> list[Action]:
    """Return the canonical legal-action list for policy selection."""
    return list_legal_actions(state, include_skip=include_skip)


def simulate_action(state: GameState, action: Action) -> GameState:
    """Return a deep-copied successor state for the provided action."""
    simulated_state = deepcopy(state)
    result = GameEngine(simulated_state).apply_action(action)
    if not result.success:
        raise ValueError(f"Cannot simulate invalid action: {action!r}")
    return simulated_state
