from __future__ import annotations

import pytest

from microciv.constants import BUILDING_LIMIT_PER_CITY, MAX_TURN_LIMIT, MIN_MAP_SIZE
from microciv.game.enums import (
    BuildingType,
    MapDifficulty,
    Mode,
    PlaybackMode,
    PolicyType,
    ResourceType,
    TechType,
    TerrainType,
)
from microciv.game.models import (
    BuildingCounts,
    City,
    GameConfig,
    GameState,
    Network,
    ResourcePool,
    SelectionState,
    Stats,
    Tile,
)


def test_game_config_factories_follow_new_mode_rules() -> None:
    play_config = GameConfig.for_play(seed=7)
    autoplay_config = GameConfig.for_autoplay(
        map_difficulty=MapDifficulty.HARD,
        playback_mode=PlaybackMode.SPEED,
        policy_type=PolicyType.RANDOM,
        seed=8,
    )

    assert play_config.mode is Mode.PLAY
    assert play_config.policy_type is PolicyType.NONE
    assert play_config.playback_mode is PlaybackMode.NONE

    assert autoplay_config.mode is Mode.AUTOPLAY
    assert autoplay_config.policy_type is PolicyType.RANDOM
    assert autoplay_config.playback_mode is PlaybackMode.SPEED
    assert autoplay_config.map_difficulty is MapDifficulty.HARD


def test_game_config_rejects_invalid_ranges_and_mode_combinations() -> None:
    with pytest.raises(ValueError):
        GameConfig(map_size=MIN_MAP_SIZE - 2)

    with pytest.raises(ValueError):
        GameConfig(turn_limit=MAX_TURN_LIMIT + 1)

    with pytest.raises(ValueError):
        GameConfig(mode=Mode.PLAY, policy_type=PolicyType.GREEDY)

    with pytest.raises(ValueError):
        GameConfig(
            mode=Mode.AUTOPLAY, policy_type=PolicyType.NONE, playback_mode=PlaybackMode.NORMAL
        )

    with pytest.raises(ValueError):
        GameConfig(
            mode=Mode.AUTOPLAY, policy_type=PolicyType.GREEDY, playback_mode=PlaybackMode.NONE
        )

    with pytest.raises(ValueError):
        GameConfig(mode=Mode.AUTOPLAY, policy_type=PolicyType.NONE, playback_mode=PlaybackMode.NONE)


def test_resource_pool_supports_lookup_merge_and_spend() -> None:
    left = ResourcePool(food=4, wood=6)
    right = ResourcePool(food=3, ore=2, science=5)

    left.merge(right)
    assert left.as_dict() == {
        ResourceType.FOOD: 7,
        ResourceType.WOOD: 6,
        ResourceType.ORE: 2,
        ResourceType.SCIENCE: 5,
    }

    assert left.can_afford({ResourceType.WOOD: 4, ResourceType.ORE: 1})
    left.spend({ResourceType.WOOD: 4, ResourceType.ORE: 1})
    assert left.wood == 2
    assert left.ore == 1

    with pytest.raises(ValueError):
        left.spend({ResourceType.SCIENCE: 99})


def test_building_counts_follow_building_limit() -> None:
    counts = BuildingCounts()

    counts.add(BuildingType.FARM, 2)
    counts.add(BuildingType.LIBRARY)

    assert counts.total == 3
    assert counts.for_type(BuildingType.FARM) == 2
    assert counts.can_add_more()

    counts.add(BuildingType.MINE, BUILDING_LIMIT_PER_CITY - counts.total)
    assert counts.total == BUILDING_LIMIT_PER_CITY
    assert not counts.can_add_more()


def test_city_network_and_selection_helpers_behave_as_expected() -> None:
    city = City(city_id=1, coord=(0, 0), founded_turn=1, network_id=1)
    network = Network(network_id=1, city_ids={1}, unlocked_techs={TechType.AGRICULTURE})
    other_network = Network(network_id=2, city_ids={2}, resources=ResourcePool(food=5))
    selection = SelectionState(selected_coord=(1, 1), selected_city_id=1)

    network.merge_from(other_network)
    selection.clear()

    assert city.total_buildings == 0
    assert network.city_ids == {1, 2}
    assert network.resources.food == 5
    assert selection.selected_coord is None
    assert selection.selected_city_id is None


def test_game_state_defaults_and_sorted_city_ids_are_stable() -> None:
    state = GameState.empty(GameConfig())
    state.cities = {
        2: City(city_id=2, coord=(0, 1), founded_turn=2, network_id=1),
        1: City(city_id=1, coord=(-1, 0), founded_turn=1, network_id=1),
        3: City(city_id=3, coord=(0, -1), founded_turn=3, network_id=1),
    }

    assert state.turn == 1
    assert state.next_city_id == 1
    assert state.sorted_city_ids() == [1, 3, 2]


def test_stats_record_decision_and_turn_time_updates_aggregates() -> None:
    stats = Stats()

    stats.record_decision_time(30)
    stats.record_decision_time(10)
    stats.build_city_count = 1
    stats.record_turn_time(40)
    stats.skip_count = 1
    stats.record_turn_time(20)

    assert stats.decision_count == 2
    assert stats.decision_time_ms_total == 40
    assert stats.decision_time_ms_avg == 20
    assert stats.decision_time_ms_max == 30
    assert stats.turn_elapsed_ms_total == 60
    assert stats.turn_elapsed_ms_avg == 30
    assert stats.turn_elapsed_ms_max == 40


def test_tile_occupancy_defaults_to_none() -> None:
    tile = Tile(base_terrain=TerrainType.PLAIN)

    assert tile.base_terrain is TerrainType.PLAIN
    assert tile.occupant.value == "none"
