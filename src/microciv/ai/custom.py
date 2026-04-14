"""Placeholder for LLM-driven custom policy."""

from __future__ import annotations

from microciv.ai.greedy import GreedyPolicy
from microciv.ai.policy import Policy
from microciv.game.actions import Action
from microciv.game.models import GameState


class CustomPolicy(Policy):
    """A policy that will eventually translate natural language goals into parameters.

    Currently falls back to GreedyPolicy as a stable placeholder.
    """

    def __init__(self, goal_text: str = "") -> None:
        self.goal_text = goal_text
        self._fallback = GreedyPolicy()

    def select_action(self, state: GameState) -> Action:
        """Choose an action for the given game state."""
        return self._fallback.select_action(state)
