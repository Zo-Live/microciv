"""Shared AI policy interfaces and helpers."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from microciv.game.actions import Action, list_legal_actions
from microciv.game.engine import GameEngine
from microciv.game.models import (
    BuildingCounts,
    City,
    GameState,
    Network,
    ResourcePool,
    Road,
    SelectionState,
    Tile,
)


class Policy(Protocol):
    """A policy that selects the next legal game action."""

    def select_action(self, state: GameState) -> Action:
        """Choose an action for the given game state."""


def get_legal_actions(state: GameState, *, include_skip: bool = True) -> list[Action]:
    """Return the canonical legal-action list for policy selection."""
    return list_legal_actions(state, include_skip=include_skip)


def clone_game_state_for_simulation(state: GameState) -> GameState:
    """Clone mutable state for AI simulation without using generic deepcopy."""
    board = {
        coord: Tile(base_terrain=tile.base_terrain, occupant=tile.occupant)
        for coord, tile in state.board.items()
    }
    cities = {
        city_id: City(
            city_id=city.city_id,
            coord=city.coord,
            founded_turn=city.founded_turn,
            network_id=city.network_id,
            buildings=BuildingCounts(
                farm=city.buildings.farm,
                lumber_mill=city.buildings.lumber_mill,
                mine=city.buildings.mine,
                library=city.buildings.library,
            ),
        )
        for city_id, city in state.cities.items()
    }
    roads = {
        road_id: Road(road_id=road.road_id, coord=road.coord, built_turn=road.built_turn)
        for road_id, road in state.roads.items()
    }
    networks = {
        network_id: Network(
            network_id=network.network_id,
            city_ids=set(network.city_ids),
            resources=ResourcePool(
                food=network.resources.food,
                wood=network.resources.wood,
                ore=network.resources.ore,
                science=network.resources.science,
            ),
            unlocked_techs=set(network.unlocked_techs),
            consecutive_starving_turns=network.consecutive_starving_turns,
        )
        for network_id, network in state.networks.items()
    }
    selection = SelectionState(
        selected_coord=state.selection.selected_coord,
        selected_city_id=state.selection.selected_city_id,
    )
    stats = replace(
        state.stats,
        action_log=list(state.stats.action_log),
        turn_snapshots=list(state.stats.turn_snapshots),
        decision_contexts=list(state.stats.decision_contexts),
    )
    return GameState(
        config=state.config,
        board=board,
        cities=cities,
        roads=roads,
        networks=networks,
        turn=state.turn,
        score=state.score,
        message=state.message,
        selection=selection,
        is_game_over=state.is_game_over,
        stats=stats,
        next_city_id=state.next_city_id,
        next_road_id=state.next_road_id,
        next_network_id=state.next_network_id,
    )


def simulate_action(state: GameState, action: Action) -> GameState:
    """Return a cloned successor state for the provided action."""
    simulated_state = clone_game_state_for_simulation(state)
    result = GameEngine(simulated_state).apply_action(action)
    if not result.success:
        raise ValueError(f"Cannot simulate invalid action: {action!r}")
    return simulated_state
