"""Procedural square-map generation."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from heapq import heappop, heappush
from random import Random

from microciv.game.enums import MapDifficulty, TerrainType
from microciv.game.models import GameConfig, Tile
from microciv.utils.grid import (
    Coord,
    cardinal_neighbors,
    chebyshev_distance,
    coord_sort_key,
    enumerate_coords,
    is_valid_coord,
    manhattan_distance,
    moore_neighbors,
    sort_coords,
)
from microciv.utils.rng import build_rng

ORDINARY_TERRAINS: tuple[TerrainType, ...] = (
    TerrainType.PLAIN,
    TerrainType.FOREST,
    TerrainType.MOUNTAIN,
    TerrainType.WASTELAND,
)

TARGET_TERRAIN_RATIOS: dict[MapDifficulty, dict[TerrainType, float]] = {
    MapDifficulty.NORMAL: {
        TerrainType.PLAIN: 0.40,
        TerrainType.FOREST: 0.22,
        TerrainType.MOUNTAIN: 0.18,
        TerrainType.WASTELAND: 0.08,
    },
    MapDifficulty.HARD: {
        TerrainType.PLAIN: 0.28,
        TerrainType.FOREST: 0.20,
        TerrainType.MOUNTAIN: 0.24,
        TerrainType.WASTELAND: 0.20,
    },
}

QUALITY_THRESHOLDS: dict[MapDifficulty, dict[str, float]] = {
    MapDifficulty.NORMAL: {
        "buildable_ratio_min": 0.54,
        "plain_ratio_min": 0.14,
        "wasteland_ratio_max": 0.28,
    },
    MapDifficulty.HARD: {
        "buildable_ratio_min": 0.42,
        "plain_ratio_min": 0.08,
        "wasteland_ratio_max": 0.35,
    },
}

MAX_MAP_RETRIES = 20


@dataclass(slots=True, frozen=True)
class GeneratedMap:
    """A reproducible generated map with metadata for later systems."""

    board: dict[Coord, Tile]
    region_assignments: dict[Coord, int]
    region_seeds: tuple[Coord, ...]
    region_primary_terrains: dict[int, TerrainType]
    river_paths: tuple[tuple[Coord, ...], ...]

    @property
    def cell_count(self) -> int:
        return len(self.board)

    @property
    def region_count(self) -> int:
        return len(self.region_seeds)

    def terrain_counts(self) -> dict[TerrainType, int]:
        counts = Counter(tile.base_terrain for tile in self.board.values())
        return {terrain: counts.get(terrain, 0) for terrain in TerrainType}

    def terrain_signature(self) -> tuple[tuple[Coord, str], ...]:
        return tuple(
            (coord, self.board[coord].base_terrain.value)
            for coord in sorted(self.board, key=coord_sort_key)
        )

    def buildable_ratio(self) -> float:
        counts = self.terrain_counts()
        buildable = (
            counts[TerrainType.PLAIN] + counts[TerrainType.FOREST] + counts[TerrainType.MOUNTAIN]
        )
        return buildable / self.cell_count

    def largest_component_size(self, terrain_type: TerrainType) -> int:
        matching = {
            coord for coord, tile in self.board.items() if tile.base_terrain is terrain_type
        }
        if not matching:
            return 0

        largest = 0
        seen: set[Coord] = set()
        for start in sort_coords(matching):
            if start in seen:
                continue
            component = 0
            queue = deque([start])
            seen.add(start)
            while queue:
                current = queue.popleft()
                component += 1
                for neighbor in cardinal_neighbors(current):
                    if neighbor in matching and neighbor not in seen:
                        seen.add(neighbor)
                        queue.append(neighbor)
            largest = max(largest, component)
        return largest


class MapGenerator:
    """Generate a reproducible initial map from a game config."""

    def generate(self, config: GameConfig) -> GeneratedMap:
        rng = build_rng(config.seed)
        last_errors: list[str] = []

        for _ in range(MAX_MAP_RETRIES):
            generated = self._generate_once(config, rng)
            repaired = self._repair_quality(generated, config)
            errors = self._quality_errors(repaired, config)
            if not errors:
                return repaired
            last_errors = errors

        raise RuntimeError(f"Unable to generate a valid map after retries: {last_errors}")

    def _generate_once(self, config: GameConfig, rng: Random) -> GeneratedMap:
        coords = enumerate_coords(config.map_size)
        region_count = self._compute_region_count(config.map_size)
        region_seeds = self._pick_region_seeds(coords, region_count, rng)
        region_assignments = self._assign_regions(coords, region_seeds)
        region_cells = self._group_region_cells(region_assignments)
        region_primary_terrains = self._assign_primary_terrains(
            region_cells, config.map_difficulty, rng
        )

        terrain_map = {
            coord: region_primary_terrains[region_assignments[coord]]
            for coord in sort_coords(region_assignments)
        }
        self._inject_secondary_patches(
            terrain_map=terrain_map,
            region_cells=region_cells,
            difficulty=config.map_difficulty,
            rng=rng,
        )
        self._smooth_terrain(terrain_map, config.map_size)

        river_paths = self._generate_rivers(config, terrain_map, rng)
        for river_path in river_paths:
            for coord in river_path:
                terrain_map[coord] = TerrainType.RIVER

        self._repair_river_adjacent_wasteland(terrain_map, config.map_size)
        self._ensure_plain_exists(terrain_map)

        board = {coord: Tile(base_terrain=terrain_map[coord]) for coord in sort_coords(terrain_map)}
        return GeneratedMap(
            board=board,
            region_assignments=region_assignments,
            region_seeds=tuple(region_seeds),
            region_primary_terrains=region_primary_terrains,
            river_paths=tuple(tuple(path) for path in river_paths),
        )

    def _compute_region_count(self, map_size: int) -> int:
        return max(4, min(9, round((map_size * map_size) / 72)))

    def _pick_region_seeds(
        self, coords: list[Coord], region_count: int, rng: Random
    ) -> list[Coord]:
        sorted_coords_list = sort_coords(coords)
        seeds = [rng.choice(sorted_coords_list)]

        while len(seeds) < region_count:
            best_distance = -1
            candidates: list[Coord] = []
            for coord in sorted_coords_list:
                if coord in seeds:
                    continue
                distance = min(chebyshev_distance(coord, seed) for seed in seeds)
                if distance > best_distance:
                    best_distance = distance
                    candidates = [coord]
                elif distance == best_distance:
                    candidates.append(coord)
            seeds.append(rng.choice(candidates))

        return seeds

    def _assign_regions(self, coords: list[Coord], region_seeds: list[Coord]) -> dict[Coord, int]:
        assignments: dict[Coord, int] = {}
        for coord in sort_coords(coords):
            best_region_id = min(
                range(len(region_seeds)),
                key=lambda region_id: (
                    manhattan_distance(coord, region_seeds[region_id]),
                    coord_sort_key(region_seeds[region_id]),
                    region_id,
                ),
            )
            assignments[coord] = best_region_id
        return assignments

    def _group_region_cells(self, region_assignments: dict[Coord, int]) -> dict[int, list[Coord]]:
        region_cells: dict[int, list[Coord]] = defaultdict(list)
        for coord, region_id in region_assignments.items():
            region_cells[region_id].append(coord)
        return {region_id: sort_coords(cells) for region_id, cells in region_cells.items()}

    def _assign_primary_terrains(
        self,
        region_cells: dict[int, list[Coord]],
        difficulty: MapDifficulty,
        rng: Random,
    ) -> dict[int, TerrainType]:
        total_cells = sum(len(cells) for cells in region_cells.values())
        target_counts = self._terrain_target_counts(total_cells, difficulty)
        ordered_regions = sorted(
            region_cells,
            key=lambda region_id: (
                -len(region_cells[region_id]),
                coord_sort_key(region_cells[region_id][0]),
            ),
        )
        forced_plain_region = ordered_regions[0]
        assigned: dict[int, TerrainType] = {}
        assigned_sizes: Counter[TerrainType] = Counter()

        for region_id in ordered_regions:
            if region_id == forced_plain_region:
                chosen = TerrainType.PLAIN
            else:
                deficits = {
                    terrain: target_counts[terrain] - assigned_sizes[terrain]
                    for terrain in ORDINARY_TERRAINS
                }
                eligible = [
                    terrain for terrain in ORDINARY_TERRAINS if deficits[terrain] > 0
                ] or list(ORDINARY_TERRAINS)
                best_deficit = max(deficits[terrain] for terrain in eligible)
                best_candidates = [
                    terrain for terrain in eligible if deficits[terrain] == best_deficit
                ]
                chosen = rng.choice(best_candidates)

            assigned[region_id] = chosen
            assigned_sizes[chosen] += len(region_cells[region_id])

        return assigned

    def _inject_secondary_patches(
        self,
        *,
        terrain_map: dict[Coord, TerrainType],
        region_cells: dict[int, list[Coord]],
        difficulty: MapDifficulty,
        rng: Random,
    ) -> None:
        target_counts = self._terrain_target_counts(len(terrain_map), difficulty)
        global_counts: Counter[TerrainType] = Counter(terrain_map.values())

        for _region_id, cells in sorted(region_cells.items()):
            if len(cells) < 8:
                continue
            budget = max(2, len(cells) // 8)
            patch_size = min(budget, max(2, len(cells) // 6))
            seed = rng.choice(cells)
            patch = self._grow_patch(seed, patch_size, set(cells))
            candidates = sorted(
                ORDINARY_TERRAINS,
                key=lambda terrain: (target_counts[terrain] - global_counts[terrain], rng.random()),
                reverse=True,
            )
            replacement = candidates[0]
            for coord in patch:
                global_counts[terrain_map[coord]] -= 1
                terrain_map[coord] = replacement
                global_counts[replacement] += 1

    def _grow_patch(self, seed: Coord, target_size: int, allowed: set[Coord]) -> list[Coord]:
        queue = deque([seed])
        seen = {seed}
        patch: list[Coord] = []

        while queue and len(patch) < target_size:
            current = queue.popleft()
            patch.append(current)
            for neighbor in cardinal_neighbors(current):
                if neighbor in allowed and neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        return patch

    def _smooth_terrain(self, terrain_map: dict[Coord, TerrainType], map_size: int) -> None:
        original = dict(terrain_map)
        for coord, current in original.items():
            neighbor_terrains = [
                original[neighbor]
                for neighbor in cardinal_neighbors(coord)
                if is_valid_coord(neighbor, map_size)
            ]
            if not neighbor_terrains:
                continue
            most_common, count = Counter(neighbor_terrains).most_common(1)[0]
            if count >= 3:
                terrain_map[coord] = most_common
            else:
                terrain_map[coord] = current

    def _generate_rivers(
        self,
        config: GameConfig,
        terrain_map: dict[Coord, TerrainType],
        rng: Random,
    ) -> list[list[Coord]]:
        river_count = 1 if config.map_difficulty is MapDifficulty.NORMAL else 2
        available = set(terrain_map)
        paths: list[list[Coord]] = []

        for index in range(river_count):
            horizontal = index % 2 == 0
            start, end = self._choose_river_endpoints(
                config.map_size, horizontal=horizontal, rng=rng
            )
            path = self._find_river_path(config.map_size, start, end, available, rng)
            for coord in path:
                if coord in available:
                    available.remove(coord)
            paths.append(path)

        return paths

    def _choose_river_endpoints(
        self, map_size: int, *, horizontal: bool, rng: Random
    ) -> tuple[Coord, Coord]:
        if horizontal:
            y_start = rng.randint(0, map_size - 1)
            y_end = min(map_size - 1, max(0, y_start + rng.randint(-2, 2)))
            return (0, y_start), (map_size - 1, y_end)
        x_start = rng.randint(0, map_size - 1)
        x_end = min(map_size - 1, max(0, x_start + rng.randint(-2, 2)))
        return (x_start, 0), (x_end, map_size - 1)

    def _find_river_path(
        self,
        map_size: int,
        start: Coord,
        end: Coord,
        available: set[Coord],
        rng: Random,
    ) -> list[Coord]:
        frontier: list[tuple[int, float, Coord]] = []
        heappush(frontier, (manhattan_distance(start, end), rng.random(), start))
        came_from: dict[Coord, Coord | None] = {start: None}
        cost_so_far: dict[Coord, int] = {start: 0}

        while frontier:
            _, _, current = heappop(frontier)
            if current == end:
                break

            for neighbor in cardinal_neighbors(current):
                if not is_valid_coord(neighbor, map_size):
                    continue
                if neighbor not in available and neighbor != end:
                    continue
                next_cost = cost_so_far[current] + 1
                if neighbor not in cost_so_far or next_cost < cost_so_far[neighbor]:
                    cost_so_far[neighbor] = next_cost
                    priority = next_cost + manhattan_distance(neighbor, end)
                    came_from[neighbor] = current
                    heappush(frontier, (priority, rng.random(), neighbor))

        if end not in came_from:
            return [start, end]

        path: list[Coord] = []
        current: Coord | None = end
        while current is not None:
            path.append(current)
            current = came_from[current]
        path.reverse()
        return path

    def _repair_river_adjacent_wasteland(
        self, terrain_map: dict[Coord, TerrainType], map_size: int
    ) -> None:
        for coord, terrain in list(terrain_map.items()):
            if terrain is not TerrainType.RIVER:
                continue
            for neighbor in moore_neighbors(coord):
                if (
                    is_valid_coord(neighbor, map_size)
                    and terrain_map.get(neighbor) is TerrainType.WASTELAND
                ):
                    terrain_map[neighbor] = TerrainType.PLAIN

    def _ensure_plain_exists(self, terrain_map: dict[Coord, TerrainType]) -> None:
        if any(terrain is TerrainType.PLAIN for terrain in terrain_map.values()):
            return
        first_coord = min(terrain_map, key=coord_sort_key)
        terrain_map[first_coord] = TerrainType.PLAIN

    def _terrain_target_counts(
        self,
        total_cells: int,
        difficulty: MapDifficulty,
    ) -> dict[TerrainType, int]:
        ratios = TARGET_TERRAIN_RATIOS[difficulty]
        counts = {terrain: int(total_cells * ratios[terrain]) for terrain in ORDINARY_TERRAINS}
        deficit = total_cells - sum(counts.values())
        ordered = sorted(ORDINARY_TERRAINS, key=lambda terrain: ratios[terrain], reverse=True)
        for index in range(deficit):
            counts[ordered[index % len(ordered)]] += 1
        return counts

    def _repair_quality(self, generated: GeneratedMap, config: GameConfig) -> GeneratedMap:
        terrain_map = {coord: tile.base_terrain for coord, tile in generated.board.items()}
        self._repair_river_adjacent_wasteland(terrain_map, config.map_size)
        self._ensure_plain_exists(terrain_map)

        counts = Counter(terrain_map.values())
        thresholds = QUALITY_THRESHOLDS[config.map_difficulty]
        total = len(terrain_map)
        buildable = (
            counts[TerrainType.PLAIN] + counts[TerrainType.FOREST] + counts[TerrainType.MOUNTAIN]
        )
        if buildable / total < thresholds["buildable_ratio_min"]:
            for coord in sort_coords(terrain_map):
                if terrain_map[coord] is TerrainType.WASTELAND:
                    terrain_map[coord] = TerrainType.PLAIN
                    buildable += 1
                    counts[TerrainType.WASTELAND] -= 1
                    counts[TerrainType.PLAIN] += 1
                    if buildable / total >= thresholds["buildable_ratio_min"]:
                        break

        board = {coord: Tile(base_terrain=terrain_map[coord]) for coord in sort_coords(terrain_map)}
        return GeneratedMap(
            board=board,
            region_assignments=generated.region_assignments,
            region_seeds=generated.region_seeds,
            region_primary_terrains=generated.region_primary_terrains,
            river_paths=generated.river_paths,
        )

    def _quality_errors(self, generated: GeneratedMap, config: GameConfig) -> list[str]:
        counts = generated.terrain_counts()
        total = generated.cell_count
        thresholds = QUALITY_THRESHOLDS[config.map_difficulty]
        errors: list[str] = []

        if counts[TerrainType.PLAIN] == 0:
            errors.append("No plains generated.")
        if generated.buildable_ratio() < thresholds["buildable_ratio_min"]:
            errors.append("Buildable ratio below threshold.")
        if counts[TerrainType.PLAIN] / total < thresholds["plain_ratio_min"]:
            errors.append("Plain ratio below threshold.")
        if counts[TerrainType.WASTELAND] / total > thresholds["wasteland_ratio_max"]:
            errors.append("Wasteland ratio above threshold.")

        for coord, tile in generated.board.items():
            if tile.base_terrain is not TerrainType.RIVER:
                continue
            for neighbor in moore_neighbors(coord):
                adjacent = generated.board.get(neighbor)
                if adjacent is not None and adjacent.base_terrain is TerrainType.WASTELAND:
                    errors.append("River-adjacent wasteland detected.")
                    return errors

        return errors
