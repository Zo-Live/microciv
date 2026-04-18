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
    building_mismatch_penalty,
    building_utilization_score,
    calculate_score,
    city_composition_bonus,
    city_count,
    city_resource_ring_score,
    river_access_score,
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
    assert breakdown.building_utilization_score == -36
    assert breakdown.fragmented_network_penalty == 16
    assert breakdown.isolated_city_penalty == 24
    assert breakdown.unproductive_road_penalty == 0
    assert breakdown.starving_network_penalty == 140
    assert calculate_score(state) == 108


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
    assert breakdown.isolated_city_penalty == 12


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

    assert city_resource_ring_score(state) == 95
    assert breakdown.resource_ring_score == 95


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

    assert city_resource_ring_score(state) == 16


def test_river_access_score_decays_per_river_component() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (2, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (3, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (4, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.RIVER),
        (1, 1): Tile(base_terrain=TerrainType.RIVER),
        (2, 1): Tile(base_terrain=TerrainType.RIVER),
        (3, 1): Tile(base_terrain=TerrainType.RIVER),
        (4, 1): Tile(base_terrain=TerrainType.RIVER),
    }
    state.cities = {
        city_id: City(city_id=city_id, coord=(city_id - 1, 0), founded_turn=city_id, network_id=1)
        for city_id in range(1, 6)
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids=set(state.cities),
            resources=ResourcePool(),
        )
    }

    assert river_access_score(state) == 64


def test_river_access_score_counts_each_river_component_separately() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (4, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.RIVER),
        (1, 1): Tile(base_terrain=TerrainType.RIVER),
        (4, 1): Tile(base_terrain=TerrainType.RIVER),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
        2: City(city_id=2, coord=(1, 0), founded_turn=2, network_id=1),
        3: City(city_id=3, coord=(4, 0), founded_turn=3, network_id=1),
    }
    state.networks = {1: Network(network_id=1, city_ids={1, 2, 3}, resources=ResourcePool())}

    assert river_access_score(state) == 60


def test_city_composition_bonus_ignores_isolated_cities() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.board = {
        (0, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (1, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (2, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (3, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (4, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (5, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (10, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (11, 0): Tile(base_terrain=TerrainType.PLAIN, occupant=OccupantType.CITY),
        (0, 1): Tile(base_terrain=TerrainType.RIVER),
        (1, 1): Tile(base_terrain=TerrainType.RIVER),
        (2, 1): Tile(base_terrain=TerrainType.RIVER),
    }
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1),
        2: City(city_id=2, coord=(1, 0), founded_turn=2, network_id=1),
        3: City(city_id=3, coord=(2, 0), founded_turn=3, network_id=1),
        4: City(city_id=4, coord=(3, 0), founded_turn=4, network_id=1),
        5: City(city_id=5, coord=(4, 0), founded_turn=5, network_id=1),
        6: City(city_id=6, coord=(5, 0), founded_turn=6, network_id=1),
        7: City(city_id=7, coord=(10, 0), founded_turn=7, network_id=2),
        8: City(city_id=8, coord=(11, 0), founded_turn=8, network_id=3),
    }
    state.networks = {
        1: Network(network_id=1, city_ids={1, 2, 3, 4, 5, 6}, resources=ResourcePool()),
        2: Network(network_id=2, city_ids={7}, resources=ResourcePool()),
        3: Network(network_id=3, city_ids={8}, resources=ResourcePool()),
    }

    assert city_composition_bonus(state) == 54


def test_building_utilization_score_is_calculated_per_network() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.cities = {
        1: City(
            city_id=1,
            coord=(0, 0),
            founded_turn=1,
            network_id=1,
            buildings=BuildingCounts(),
        ),
        2: City(
            city_id=2,
            coord=(1, 0),
            founded_turn=2,
            network_id=2,
            buildings=BuildingCounts(farm=3),
        ),
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(),
            unlocked_techs={TechType.AGRICULTURE},
        ),
        2: Network(
            network_id=2,
            city_ids={2},
            resources=ResourcePool(),
            unlocked_techs={TechType.AGRICULTURE},
        ),
    }

    assert building_utilization_score(state) == -6


def test_building_mismatch_penalty_is_capped_and_uses_network_resources() -> None:
    state = GameState.empty(GameConfig.for_play())
    state.cities = {
        1: City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1, buildings=BuildingCounts()),
    }
    state.networks = {
        1: Network(
            network_id=1,
            city_ids={1},
            resources=ResourcePool(wood=400),
            unlocked_techs={TechType.LOGGING},
        ),
    }

    assert building_mismatch_penalty(state) == 18
