from __future__ import annotations

from microciv.game.enums import OccupantType, TechType, TerrainType
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
from microciv.game.scoring import (
    building_count,
    calculate_score,
    city_count,
    city_resource_ring_score,
    score_breakdown,
    tech_count,
    total_resources,
)


def test_scoring_uses_unique_techs_and_total_resources() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.cities = {
        1: City(
            city_id=1, coord=(0, 0), founded_turn=1, network_id=1, buildings=BuildingCounts(farm=2)
        ),
        2: City(
            city_id=2,
            coord=(2, 0),
            founded_turn=2,
            network_id=2,
            buildings=BuildingCounts(library=1),
        ),
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(food=11, wood=5),
            unlocked_techs={TechType.AGRICULTURE},
        ),
        2: Network(
            network_id=2,
            city_ids={2},
            resources=ResourcePool(ore=4, science=40),
            unlocked_techs={TechType.AGRICULTURE, TechType.LOGGING},
        ),
    }

    assert city_count(state) == 2
    assert building_count(state) == 3
    assert tech_count(state) == 2
    assert total_resources(state).food == 11
    assert total_resources(state).wood == 5
    assert total_resources(state).ore == 4
    assert total_resources(state).science == 40
    breakdown = score_breakdown(state)
    assert breakdown.city_score == 28
    assert breakdown.building_score == 54
    assert breakdown.tech_score == 240
    assert breakdown.tech_utilization_score == 18
    assert breakdown.fragmented_network_penalty == 10
    assert breakdown.unproductive_road_penalty == 0
    assert calculate_score(state) == 192


def test_scoring_penalizes_roads_in_single_city_networks() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.ROAD),
    }
    state.cities = {1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)}
    state.roads = {1: Road(road_id=1, coord=(1, 0), built_turn=1)}
    state.networks = {1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=4))}

    breakdown = score_breakdown(state)

    assert breakdown.unproductive_road_penalty == 4


def test_scoring_rewards_cities_nested_inside_resource_rings() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (4, 4): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (3, 3): Tile(base_terrain=TerrainType.FOREST),
        (3, 4): Tile(base_terrain=TerrainType.FOREST),
        (3, 5): Tile(base_terrain=TerrainType.MOUNTAIN),
        (4, 3): Tile(base_terrain=TerrainType.FOREST),
        (4, 5): Tile(base_terrain=TerrainType.MOUNTAIN),
        (5, 3): Tile(base_terrain=TerrainType.FOREST),
        (5, 4): Tile(base_terrain=TerrainType.MOUNTAIN),
        (5, 5): Tile(base_terrain=TerrainType.FOREST),
    }
    state.cities = {1: City(city_id=1, coord=(4, 4), founded_turn=1, network_id=1)}
    state.networks = {1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=4))}

    breakdown = score_breakdown(state)

    assert city_resource_ring_score(state) == 67
    assert breakdown.resource_ring_score == 67


def test_scoring_counts_river_tiles_inside_resource_ring() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (4, 4): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (3, 4): Tile(base_terrain=TerrainType.RIVER),
        (4, 3): Tile(base_terrain=TerrainType.RIVER),
        (5, 4): Tile(base_terrain=TerrainType.FOREST),
        (4, 5): Tile(base_terrain=TerrainType.MOUNTAIN),
    }
    state.cities = {1: City(city_id=1, coord=(4, 4), founded_turn=1, network_id=1)}
    state.networks = {1: Network(network_id=1, city_ids={1}, resources=ResourcePool(food=4))}

    assert city_resource_ring_score(state) == 21
