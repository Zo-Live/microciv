"""Game engine orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from microciv.constants import BUILDING_COSTS, TECH_COSTS
from microciv.game.actions import Action, validate_action
from microciv.game.enums import ActionType, BuildingType, OccupantType, TechType, TerrainType
from microciv.game.models import City, GameState, Network, Road
from microciv.game.networks import map_passable_coords_to_networks, recompute_networks
from microciv.game.resources import (
    SettlementSummary,
    charge_river_road_cost,
    choose_river_road_payment_network,
    cover_reward_for_tile,
    recompute_resource_ownership,
    settle_resources,
)
from microciv.game.scoring import calculate_score


@dataclass(slots=True)
class EngineResult:
    """The result of applying an action to the current state."""

    success: bool
    message: str
    state: GameState
    settlement: SettlementSummary | None = None


class GameEngine:
    """Own the state transitions and turn loop."""

    def __init__(self, state: GameState) -> None:
        self.state = state

    def apply_action(self, action: Action) -> EngineResult:
        started_at = perf_counter()
        validation = validate_action(self.state, action)
        if not validation.is_valid:
            self.state.message = validation.message
            return EngineResult(False, validation.message, self.state)

        if action.action_type is ActionType.BUILD_CITY:
            self._apply_build_city(action)
            self.state.stats.build_city_count += 1
        elif action.action_type is ActionType.BUILD_ROAD:
            self._apply_build_road(action)
            self.state.stats.build_road_count += 1
        elif action.action_type is ActionType.BUILD_BUILDING:
            self._apply_build_building(action)
        elif action.action_type is ActionType.RESEARCH_TECH:
            self._apply_research_tech(action)
        elif action.action_type is ActionType.SKIP:
            self.state.stats.skip_count += 1
        else:
            self.state.message = "Unsupported action"
            return EngineResult(False, self.state.message, self.state)

        ownership = recompute_resource_ownership(self.state)
        settlement = settle_resources(self.state, ownership=ownership)
        self.state.score = calculate_score(self.state)
        self.state.message = ""

        if self.state.turn >= self.state.config.turn_limit:
            self.state.is_game_over = True
        else:
            self.state.turn += 1

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        self.state.stats.record_turn_time(elapsed_ms)
        return EngineResult(True, "", self.state, settlement)

    def _apply_build_city(self, action: Action) -> None:
        assert action.coord is not None
        tile = self.state.board[action.coord]
        reward = cover_reward_for_tile(tile)

        city_id = self.state.next_city_id
        network_id = self.state.next_network_id
        self.state.next_city_id += 1
        self.state.next_network_id += 1

        tile.occupant = OccupantType.CITY
        self.state.cities[city_id] = City(
            city_id=city_id,
            coord=action.coord,
            founded_turn=self.state.turn,
            network_id=network_id,
        )
        self.state.networks[network_id] = Network(network_id=network_id, city_ids={city_id})
        recompute_networks(self.state)

        connected_network_id = map_passable_coords_to_networks(self.state)[action.coord]
        self.state.networks[connected_network_id].resources.merge(reward)

    def _apply_build_road(self, action: Action) -> None:
        assert action.coord is not None
        tile = self.state.board[action.coord]
        reward = cover_reward_for_tile(tile)

        if tile.base_terrain is TerrainType.RIVER:
            payment_network_id = choose_river_road_payment_network(self.state, action.coord)
            if payment_network_id is None:
                raise ValueError("River road should have been rejected by validation.")
            charge_river_road_cost(self.state.networks[payment_network_id])

        road_id = self.state.next_road_id
        self.state.next_road_id += 1

        tile.occupant = OccupantType.ROAD
        self.state.roads[road_id] = Road(
            road_id=road_id, coord=action.coord, built_turn=self.state.turn
        )
        recompute_networks(self.state)

        connected_network_id = map_passable_coords_to_networks(self.state)[action.coord]
        self.state.networks[connected_network_id].resources.merge(reward)

    def _apply_build_building(self, action: Action) -> None:
        assert action.city_id is not None
        assert action.building_type is not None
        city = self.state.cities[action.city_id]
        network = self.state.networks[city.network_id]

        network.resources.spend(BUILDING_COSTS[action.building_type])
        city.buildings.add(action.building_type)
        self._increment_building_stat(action.building_type)

    def _apply_research_tech(self, action: Action) -> None:
        assert action.city_id is not None
        assert action.tech_type is not None
        city = self.state.cities[action.city_id]
        network = self.state.networks[city.network_id]

        network.resources.science -= TECH_COSTS[action.tech_type]
        network.unlocked_techs.add(action.tech_type)
        self._increment_research_stat(action.tech_type)

    def _increment_building_stat(self, building_type: BuildingType) -> None:
        if building_type is BuildingType.FARM:
            self.state.stats.build_farm_count += 1
        elif building_type is BuildingType.LUMBER_MILL:
            self.state.stats.build_lumber_mill_count += 1
        elif building_type is BuildingType.MINE:
            self.state.stats.build_mine_count += 1
        elif building_type is BuildingType.LIBRARY:
            self.state.stats.build_library_count += 1

    def _increment_research_stat(self, tech_type: TechType) -> None:
        if tech_type is TechType.AGRICULTURE:
            self.state.stats.research_agriculture_count += 1
        elif tech_type is TechType.LOGGING:
            self.state.stats.research_logging_count += 1
        elif tech_type is TechType.MINING:
            self.state.stats.research_mining_count += 1
        elif tech_type is TechType.EDUCATION:
            self.state.stats.research_education_count += 1
