from __future__ import annotations

from microciv.game.enums import MapDifficulty, TerrainType
from microciv.game.mapgen import MapGenerator
from microciv.game.models import GameConfig
from microciv.utils.grid import moore_neighbors


def test_map_generation_is_reproducible_for_same_seed() -> None:
    generator = MapGenerator()
    config = GameConfig.for_play(map_size=12, seed=42)

    first = generator.generate(config)
    second = generator.generate(config)

    assert first.terrain_signature() == second.terrain_signature()
    assert first.region_seeds == second.region_seeds
    assert first.river_paths == second.river_paths


def test_generated_square_map_matches_declared_size() -> None:
    generated = MapGenerator().generate(GameConfig.for_play(map_size=16, seed=1))

    assert generated.cell_count == 16 * 16
    assert generated.region_count >= 4


def test_generated_maps_satisfy_new_quality_rules() -> None:
    generator = MapGenerator()
    configs = [
        GameConfig.for_play(map_size=12, seed=0, map_difficulty=MapDifficulty.NORMAL),
        GameConfig.for_play(map_size=14, seed=7, map_difficulty=MapDifficulty.NORMAL),
        GameConfig.for_play(map_size=18, seed=11, map_difficulty=MapDifficulty.HARD),
        GameConfig.for_play(map_size=20, seed=19, map_difficulty=MapDifficulty.HARD),
    ]

    for config in configs:
        generated = generator.generate(config)
        counts = generated.terrain_counts()
        total = generated.cell_count

        assert counts[TerrainType.PLAIN] >= 1
        assert all(tile.occupant.value == "none" for tile in generated.board.values())

        if config.map_difficulty is MapDifficulty.NORMAL:
            assert generated.buildable_ratio() >= 0.54
            assert counts[TerrainType.PLAIN] / total >= 0.14
            assert counts[TerrainType.WASTELAND] / total <= 0.28
        else:
            assert generated.buildable_ratio() >= 0.42
            assert counts[TerrainType.PLAIN] / total >= 0.08
            assert counts[TerrainType.WASTELAND] / total <= 0.35

        river_cells = {coord for path in generated.river_paths for coord in path}
        for coord in river_cells:
            for neighbor in moore_neighbors(coord):
                tile = generated.board.get(neighbor)
                assert tile is None or tile.base_terrain is not TerrainType.WASTELAND


def test_hard_maps_generate_two_rivers_while_normal_maps_generate_one() -> None:
    generator = MapGenerator()
    normal = generator.generate(
        GameConfig.for_play(map_size=18, seed=23, map_difficulty=MapDifficulty.NORMAL)
    )
    hard = generator.generate(
        GameConfig.for_play(map_size=18, seed=23, map_difficulty=MapDifficulty.HARD)
    )

    assert len(normal.river_paths) == 1
    assert len(hard.river_paths) == 2
