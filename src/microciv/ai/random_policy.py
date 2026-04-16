"""Random policy placeholder for comparison tests."""

from __future__ import annotations

from random import Random

from microciv.ai.policy import Policy, get_legal_actions
from microciv.game.actions import Action
from microciv.game.models import GameState
from microciv.utils.rng import build_rng


class RandomPolicy(Policy):
    """Reference random policy used for evaluation."""

    def __init__(self, seed: int = 0) -> None:
        self._rng: Random = build_rng(seed)

    def select_action(self, state: GameState) -> Action:
        legal_actions = get_legal_actions(state)
        if not legal_actions:
            return Action.skip()
        return self._rng.choice(legal_actions)

    def explain_decision(self, state: GameState) -> dict[str, object]:
        legal_actions = get_legal_actions(state)
        return {"legal_actions_count": len(legal_actions)}
