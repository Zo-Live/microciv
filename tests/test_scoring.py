from __future__ import annotations

from microciv.game.enums import TechType
from microciv.game.models import BuildingCounts, City, GameConfig, GameState, Network, ResourcePool
from microciv.game.scoring import (
    building_count,
    calculate_score,
    city_count,
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
    assert calculate_score(state) == 149
