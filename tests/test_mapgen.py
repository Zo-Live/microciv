from __future__ import annotations

from microciv.game.enums import MapDifficulty, TerrainType
from microciv.game.mapgen import MapGenerator
from microciv.game.models import GameConfig
from microciv.utils.hexgrid import neighbors


def test_map_generation_is_reproducible_for_same_seed() -> None:
    generator = MapGenerator()
    config = GameConfig.for_play(map_size=6, seed=42)

    first = generator.generate(config)
    second = generator.generate(config)

    assert first.terrain_signature() == second.terrain_signature()
    assert first.region_seeds == second.region_seeds
    assert first.river_paths == second.river_paths


def test_region_count_matches_formula() -> None:
    generator = MapGenerator()
    generated = generator.generate(GameConfig.for_play(map_size=6, seed=1))

    assert generated.region_count == 5


def test_generated_maps_satisfy_frozen_quality_rules() -> None:
    generator = MapGenerator()
    configs = [
        GameConfig.for_play(map_size=6, seed=0, map_difficulty=MapDifficulty.NORMAL),
        GameConfig.for_play(map_size=6, seed=7, map_difficulty=MapDifficulty.NORMAL),
        GameConfig.for_play(map_size=8, seed=11, map_difficulty=MapDifficulty.HARD),
        GameConfig.for_play(map_size=8, seed=19, map_difficulty=MapDifficulty.HARD),
    ]

    for config in configs:
        generated = generator.generate(config)
        counts = generated.terrain_counts()
        total = generated.cell_count

        assert counts[TerrainType.PLAIN] >= 1
        assert all(tile.occupant.value == "none" for tile in generated.board.values())

        if config.map_difficulty is MapDifficulty.NORMAL:
            assert generated.buildable_ratio() >= 0.55
            assert counts[TerrainType.PLAIN] / total >= 0.15
            assert counts[TerrainType.WASTELAND] / total <= 0.25
            assert generated.largest_component_size(TerrainType.WASTELAND) / total <= 0.18
        else:
            assert generated.buildable_ratio() >= 0.45
            assert counts[TerrainType.PLAIN] / total >= 0.10
            assert counts[TerrainType.WASTELAND] / total <= 0.33
            assert generated.largest_component_size(TerrainType.WASTELAND) / total <= 0.25

        assert all(counts[terrain] / total <= 0.45 for terrain in (TerrainType.PLAIN, TerrainType.FOREST, TerrainType.MOUNTAIN, TerrainType.WASTELAND))
        assert all(len(path) / total <= 0.40 for path in generated.river_paths)

        river_cells = {coord for path in generated.river_paths for coord in path}
        for coord in river_cells:
            for neighbor in neighbors(coord):
                tile = generated.board.get(neighbor)
                assert tile is None or tile.base_terrain is not TerrainType.WASTELAND


def test_hard_map_size_eight_generates_two_rivers_while_normal_generates_one() -> None:
    generator = MapGenerator()
    normal = generator.generate(
        GameConfig.for_play(map_size=8, seed=23, map_difficulty=MapDifficulty.NORMAL)
    )
    hard = generator.generate(
        GameConfig.for_play(map_size=8, seed=23, map_difficulty=MapDifficulty.HARD)
    )

    assert len(normal.river_paths) == 1
    assert len(hard.river_paths) == 2
