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


def test_normal_and_hard_can_both_generate_one_or_two_rivers() -> None:
    generator = MapGenerator()
    for difficulty in (MapDifficulty.NORMAL, MapDifficulty.HARD):
        counts = {
            len(
                generator.generate(
                    GameConfig.for_play(map_size=18, seed=seed, map_difficulty=difficulty)
                ).river_paths
            )
            for seed in range(20)
        }
        assert counts == {1, 2}


def test_double_river_layouts_include_crossing_and_non_crossing_patterns() -> None:
    generator = MapGenerator()
    found_crossing = False
    found_non_crossing = False
    found_length_gap = False

    for difficulty in (MapDifficulty.NORMAL, MapDifficulty.HARD):
        for seed in range(20):
            generated = generator.generate(
                GameConfig.for_play(map_size=18, seed=seed, map_difficulty=difficulty)
            )
            if len(generated.river_paths) != 2:
                continue
            first, second = generated.river_paths
            if set(first) & set(second):
                found_crossing = True
            else:
                found_non_crossing = True
            lengths = sorted((len(first), len(second)), reverse=True)
            if lengths[0] - lengths[1] >= 6:
                found_length_gap = True

    assert found_crossing
    assert found_non_crossing
    assert found_length_gap


def test_generated_rivers_meander_more_than_before() -> None:
    generator = MapGenerator()
    curvature_scores = []
    span_ratios = []
    coverage_ratios = []
    reversal_ratios = []
    for seed in range(1, 11):
        generated = generator.generate(
            GameConfig.for_play(map_size=16, seed=seed, map_difficulty=MapDifficulty.NORMAL)
        )
        metrics = generated.river_metrics()
        curvature_scores.append(metrics.curvature_score)
        span_ratios.append(metrics.secondary_span_ratio)
        coverage_ratios.append(metrics.secondary_coverage_ratio)
        reversal_ratios.append(metrics.secondary_reversal_ratio)

    assert sum(curvature_scores) / len(curvature_scores) >= 0.5
    assert sum(span_ratios) / len(span_ratios) >= 0.4
    assert sum(coverage_ratios) / len(coverage_ratios) >= 0.38
    assert sum(reversal_ratios) / len(reversal_ratios) >= 0.45


def test_hard_maps_are_structurally_less_buildable_than_normal_maps() -> None:
    generator = MapGenerator()
    normal_ratios = []
    hard_ratios = []

    for seed in range(1, 11):
        normal = generator.generate(
            GameConfig.for_play(map_size=16, seed=seed, map_difficulty=MapDifficulty.NORMAL)
        )
        hard = generator.generate(
            GameConfig.for_play(map_size=16, seed=seed, map_difficulty=MapDifficulty.HARD)
        )
        normal_ratios.append(normal.buildable_ratio())
        hard_ratios.append(hard.buildable_ratio())

    assert sum(normal_ratios) / len(normal_ratios) > sum(hard_ratios) / len(hard_ratios)
