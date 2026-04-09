"""Procedural hex map generation."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from heapq import heappop, heappush
from math import ceil, floor
from random import Random

from microciv.game.enums import MapDifficulty, TerrainType
from microciv.game.models import GameConfig, Tile
from microciv.utils.hexgrid import (
    Coord,
    HEX_DIRECTIONS,
    add_coords,
    coord_sort_key,
    enumerate_hex_coords,
    hex_distance,
    is_valid_hex,
    neighbors,
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
        TerrainType.PLAIN: 0.30,
        TerrainType.FOREST: 0.25,
        TerrainType.MOUNTAIN: 0.25,
        TerrainType.WASTELAND: 0.20,
    },
    MapDifficulty.HARD: {
        TerrainType.PLAIN: 0.20,
        TerrainType.FOREST: 0.25,
        TerrainType.MOUNTAIN: 0.30,
        TerrainType.WASTELAND: 0.25,
    },
}

QUALITY_THRESHOLDS: dict[MapDifficulty, dict[str, float]] = {
    MapDifficulty.NORMAL: {
        "buildable_ratio_min": 0.55,
        "plain_ratio_min": 0.15,
        "wasteland_ratio_max": 0.25,
        "largest_wasteland_component_ratio_max": 0.18,
    },
    MapDifficulty.HARD: {
        "buildable_ratio_min": 0.45,
        "plain_ratio_min": 0.10,
        "wasteland_ratio_max": 0.33,
        "largest_wasteland_component_ratio_max": 0.25,
    },
}

MAX_ORDINARY_TERRAIN_RATIO = 0.45
MAX_RIVER_RATIO = 0.40
MAX_MAP_RETRIES = 20
MAX_RIVER_RETRIES = 20


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
            (coord, self.board[coord].base_terrain.value) for coord in sorted(self.board, key=coord_sort_key)
        )

    def buildable_ratio(self) -> float:
        counts = self.terrain_counts()
        buildable = counts[TerrainType.PLAIN] + counts[TerrainType.FOREST] + counts[TerrainType.MOUNTAIN]
        return buildable / self.cell_count

    def largest_component_size(self, terrain_type: TerrainType) -> int:
        matching = {coord for coord, tile in self.board.items() if tile.base_terrain is terrain_type}
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
                for neighbor in neighbors(current):
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
        coords = enumerate_hex_coords(config.map_size)
        region_count = self._compute_region_count(len(coords))
        region_seeds = self._pick_region_seeds(coords, region_count, rng)
        region_assignments = self._assign_regions(coords, region_seeds)
        region_cells = self._group_region_cells(region_assignments)
        region_adjacency = self._build_region_adjacency(region_assignments)
        region_primary_terrains = self._assign_primary_terrains(
            region_cells, region_adjacency, config.map_difficulty, rng
        )

        terrain_map = {
            coord: region_primary_terrains[region_assignments[coord]]
            for coord in sort_coords(region_assignments)
        }
        self._inject_secondary_patches(
            terrain_map, region_cells, region_primary_terrains, config.map_difficulty, rng
        )
        self._smooth_terrain(terrain_map, region_cells, region_primary_terrains)

        river_paths = self._generate_rivers(config, coords, terrain_map, rng)
        for river_path in river_paths:
            for coord in river_path:
                terrain_map[coord] = TerrainType.RIVER

        self._repair_river_adjacent_wasteland(
            terrain_map,
            region_assignments,
            region_primary_terrains,
            config.map_difficulty,
        )
        self._ensure_plain_exists(terrain_map)

        board = {coord: Tile(base_terrain=terrain_map[coord]) for coord in sort_coords(terrain_map)}
        return GeneratedMap(
            board=board,
            region_assignments=region_assignments,
            region_seeds=tuple(region_seeds),
            region_primary_terrains=region_primary_terrains,
            river_paths=tuple(tuple(path) for path in river_paths),
        )

    def _compute_region_count(self, cell_count: int) -> int:
        return max(3, min(8, round(cell_count / 18)))

    def _pick_region_seeds(self, coords: Sequence[Coord], region_count: int, rng: Random) -> list[Coord]:
        sorted_coords_list = sort_coords(coords)
        seeds = [rng.choice(sorted_coords_list)]

        while len(seeds) < region_count:
            best_distance = -1
            candidates: list[Coord] = []
            for coord in sorted_coords_list:
                if coord in seeds:
                    continue
                distance = min(hex_distance(coord, seed) for seed in seeds)
                if distance > best_distance:
                    best_distance = distance
                    candidates = [coord]
                elif distance == best_distance:
                    candidates.append(coord)
            seeds.append(rng.choice(candidates))

        return seeds

    def _assign_regions(self, coords: Sequence[Coord], region_seeds: Sequence[Coord]) -> dict[Coord, int]:
        assignments: dict[Coord, int] = {seed: region_id for region_id, seed in enumerate(region_seeds)}
        queue = deque((seed, region_id) for region_id, seed in enumerate(region_seeds))

        while queue:
            current, region_id = queue.popleft()
            for neighbor in neighbors(current):
                if neighbor in assignments or neighbor not in coords:
                    continue
                assignments[neighbor] = region_id
                queue.append((neighbor, region_id))

        return assignments

    def _group_region_cells(self, region_assignments: dict[Coord, int]) -> dict[int, list[Coord]]:
        region_cells: dict[int, list[Coord]] = defaultdict(list)
        for coord, region_id in region_assignments.items():
            region_cells[region_id].append(coord)
        return {region_id: sort_coords(cells) for region_id, cells in region_cells.items()}

    def _build_region_adjacency(self, region_assignments: dict[Coord, int]) -> dict[int, set[int]]:
        adjacency: dict[int, set[int]] = defaultdict(set)
        for coord, region_id in region_assignments.items():
            for neighbor in neighbors(coord):
                other_region = region_assignments.get(neighbor)
                if other_region is None or other_region == region_id:
                    continue
                adjacency[region_id].add(other_region)
                adjacency[other_region].add(region_id)
        return adjacency

    def _assign_primary_terrains(
        self,
        region_cells: dict[int, list[Coord]],
        region_adjacency: dict[int, set[int]],
        difficulty: MapDifficulty,
        rng: Random,
    ) -> dict[int, TerrainType]:
        total_cells = sum(len(cells) for cells in region_cells.values())
        target_counts = self._terrain_target_counts(total_cells, difficulty)
        ordered_regions = sorted(
            region_cells,
            key=lambda region_id: (-len(region_cells[region_id]), coord_sort_key(region_cells[region_id][0])),
        )

        forced_plain_region = ordered_regions[0]
        assigned: dict[int, TerrainType] = {}
        assigned_sizes: Counter[TerrainType] = Counter()

        for region_id in ordered_regions:
            if region_id == forced_plain_region:
                chosen = TerrainType.PLAIN
            else:
                deficits = {
                    terrain: target_counts[terrain] - assigned_sizes[terrain] for terrain in ORDINARY_TERRAINS
                }
                eligible = [terrain for terrain in ORDINARY_TERRAINS if deficits[terrain] > 0]
                if not eligible:
                    eligible = list(ORDINARY_TERRAINS)

                adjacent_assigned = {
                    assigned[neighbor]
                    for neighbor in region_adjacency.get(region_id, set())
                    if neighbor in assigned
                }
                non_repeating = [terrain for terrain in eligible if terrain not in adjacent_assigned]
                candidate_pool = non_repeating or eligible
                best_deficit = max(deficits[terrain] for terrain in candidate_pool)
                best_candidates = [
                    terrain for terrain in candidate_pool if deficits[terrain] == best_deficit
                ]
                chosen = rng.choice(best_candidates)

            assigned[region_id] = chosen
            assigned_sizes[chosen] += len(region_cells[region_id])

        return assigned

    def _inject_secondary_patches(
        self,
        terrain_map: dict[Coord, TerrainType],
        region_cells: dict[int, list[Coord]],
        region_primary_terrains: dict[int, TerrainType],
        difficulty: MapDifficulty,
        rng: Random,
    ) -> None:
        total_cells = len(terrain_map)
        target_counts = self._terrain_target_counts(total_cells, difficulty)
        global_counts: Counter[TerrainType] = Counter(terrain_map.values())

        ordered_regions = sorted(
            region_cells,
            key=lambda region_id: (-len(region_cells[region_id]), coord_sort_key(region_cells[region_id][0])),
        )
        for region_id in ordered_regions:
            cells = region_cells[region_id]
            primary = region_primary_terrains[region_id]
            min_primary_cells = ceil(len(cells) * 0.70)
            remaining_secondary_budget = len(cells) - min_primary_cells
            if remaining_secondary_budget < 2:
                continue

            max_patch_count = min(3, remaining_secondary_budget // 2)
            patch_count = rng.randint(1, max_patch_count)
            remaining_budget = remaining_secondary_budget
            secondary_types = self._choose_secondary_types(primary, global_counts, target_counts, rng)

            region_set = set(cells)
            for patch_index in range(patch_count):
                remaining_patches = patch_count - patch_index
                max_size = min(5, remaining_budget - 2 * (remaining_patches - 1))
                if max_size < 2:
                    break

                patch_size = rng.randint(2, max_size)
                patch_terrain = self._choose_patch_terrain(secondary_types, global_counts, target_counts, rng)
                patch_cells = self._grow_patch(region_set, terrain_map, primary, patch_size, rng)
                if len(patch_cells) < 2:
                    continue

                for coord in patch_cells:
                    global_counts[terrain_map[coord]] -= 1
                    terrain_map[coord] = patch_terrain
                    global_counts[patch_terrain] += 1
                remaining_budget -= len(patch_cells)

    def _choose_secondary_types(
        self,
        primary: TerrainType,
        global_counts: Counter[TerrainType],
        target_counts: dict[TerrainType, int],
        rng: Random,
    ) -> tuple[TerrainType, ...]:
        candidates = [terrain for terrain in ORDINARY_TERRAINS if terrain is not primary]
        ranked = sorted(
            candidates,
            key=lambda terrain: (
                -(target_counts[terrain] - global_counts[terrain]),
                terrain.value,
            ),
        )
        if len(ranked) == 1:
            return (ranked[0],)

        top_deficit = target_counts[ranked[0]] - global_counts[ranked[0]]
        tied = [terrain for terrain in ranked if target_counts[terrain] - global_counts[terrain] == top_deficit]
        first = rng.choice(tied)
        second_candidates = [terrain for terrain in ranked if terrain is not first]
        return (first, second_candidates[0])

    def _choose_patch_terrain(
        self,
        terrain_options: Sequence[TerrainType],
        global_counts: Counter[TerrainType],
        target_counts: dict[TerrainType, int],
        rng: Random,
    ) -> TerrainType:
        deficits = {terrain: target_counts[terrain] - global_counts[terrain] for terrain in terrain_options}
        best_deficit = max(deficits.values())
        best_candidates = [terrain for terrain in terrain_options if deficits[terrain] == best_deficit]
        return rng.choice(best_candidates)

    def _grow_patch(
        self,
        region_set: set[Coord],
        terrain_map: dict[Coord, TerrainType],
        primary: TerrainType,
        patch_size: int,
        rng: Random,
    ) -> list[Coord]:
        primary_cells = [coord for coord in sort_coords(region_set) if terrain_map[coord] is primary]
        if len(primary_cells) < 2:
            return []

        seed = rng.choice(primary_cells)
        selected = [seed]
        selected_set = {seed}
        queue = deque([seed])

        while queue and len(selected) < patch_size:
            current = queue.popleft()
            for neighbor in sort_coords(neighbors(current)):
                if neighbor not in region_set or neighbor in selected_set:
                    continue
                if terrain_map[neighbor] is not primary:
                    continue
                selected_set.add(neighbor)
                selected.append(neighbor)
                queue.append(neighbor)
                if len(selected) >= patch_size:
                    break

        return selected

    def _smooth_terrain(
        self,
        terrain_map: dict[Coord, TerrainType],
        region_cells: dict[int, list[Coord]],
        region_primary_terrains: dict[int, TerrainType],
    ) -> None:
        ordered_regions = sorted(region_cells, key=lambda region_id: coord_sort_key(region_cells[region_id][0]))

        for _ in range(2):
            region_counts = {
                region_id: Counter(terrain_map[coord] for coord in cells)
                for region_id, cells in region_cells.items()
            }
            changes: dict[Coord, TerrainType] = {}

            for region_id in ordered_regions:
                primary = region_primary_terrains[region_id]
                min_primary_cells = ceil(len(region_cells[region_id]) * 0.70)
                region_set = set(region_cells[region_id])
                for coord in region_cells[region_id]:
                    current = terrain_map[coord]
                    neighbor_terrains = [
                        terrain_map[neighbor] for neighbor in neighbors(coord) if neighbor in region_set
                    ]
                    if not neighbor_terrains:
                        continue

                    same_count = sum(1 for terrain in neighbor_terrains if terrain is current)
                    if same_count > 1:
                        continue

                    counts = Counter(neighbor_terrains)
                    top_count = max(counts.values())
                    majority = [terrain for terrain, count in counts.items() if count == top_count]
                    if len(majority) != 1:
                        continue

                    proposed = majority[0]
                    if proposed is current:
                        continue
                    if current is primary and region_counts[region_id][primary] - 1 < min_primary_cells:
                        continue

                    changes[coord] = proposed
                    region_counts[region_id][current] -= 1
                    region_counts[region_id][proposed] += 1

            if not changes:
                break
            terrain_map.update(changes)

    def _generate_rivers(
        self,
        config: GameConfig,
        coords: Sequence[Coord],
        terrain_map: dict[Coord, TerrainType],
        rng: Random,
    ) -> list[list[Coord]]:
        river_count = 1 if config.map_difficulty is MapDifficulty.NORMAL or config.map_size <= 6 else 2
        min_length = self._min_river_length(config)
        max_length = floor(len(coords) * MAX_RIVER_RATIO)

        occupied: set[Coord] = set()
        rivers: list[list[Coord]] = []
        for _ in range(river_count):
            river = self._generate_single_river(
                coords=coords,
                occupied=occupied,
                map_size=config.map_size,
                min_length=min_length,
                max_length=max_length,
                rng=rng,
            )
            if river is None:
                raise RuntimeError("River generation failed.")
            rivers.append(river)
            occupied.update(river)
        return rivers

    def _generate_single_river(
        self,
        *,
        coords: Sequence[Coord],
        occupied: set[Coord],
        map_size: int,
        min_length: int,
        max_length: int,
        rng: Random,
    ) -> list[Coord] | None:
        available = set(coords) - occupied
        boundary = [coord for coord in sort_coords(available) if self._is_boundary(coord, map_size)]
        if len(boundary) < 2:
            return None

        for _ in range(MAX_RIVER_RETRIES):
            start = rng.choice(boundary)
            endpoint_candidates = [coord for coord in boundary if coord != start]
            farthest_distance = max(hex_distance(start, coord) for coord in endpoint_candidates)
            farthest_endpoints = [
                coord for coord in endpoint_candidates if hex_distance(start, coord) == farthest_distance
            ]
            end = rng.choice(farthest_endpoints)
            path = self._search_river_path(start, end, available, map_size, max_length, rng)
            if path is not None and len(path) >= min_length:
                return path

        return None

    def _search_river_path(
        self,
        start: Coord,
        end: Coord,
        available: set[Coord],
        map_size: int,
        max_length: int,
        rng: Random,
    ) -> list[Coord] | None:
        start_state = (start, -1)
        frontier: list[tuple[float, float, float, Coord, int]] = []
        heappush(frontier, (hex_distance(start, end), 0.0, rng.random(), start, -1))

        came_from: dict[tuple[Coord, int], tuple[Coord, int] | None] = {start_state: None}
        best_cost: dict[tuple[Coord, int], float] = {start_state: 0.0}

        while frontier:
            _, cost_so_far, _, current, previous_direction_index = heappop(frontier)
            current_state = (current, previous_direction_index)
            if cost_so_far != best_cost[current_state]:
                continue

            if current == end:
                path = self._reconstruct_path(came_from, current_state)
                if len(path) <= max_length:
                    return path
                continue

            if len(self._reconstruct_path(came_from, current_state)) + hex_distance(current, end) > max_length:
                continue

            for direction_index, direction in enumerate(HEX_DIRECTIONS):
                neighbor = add_coords(current, direction)
                if neighbor not in available or not is_valid_hex(neighbor, map_size):
                    continue

                turn_penalty = (
                    0.0
                    if previous_direction_index in (-1, direction_index)
                    else 0.25
                )
                next_cost = cost_so_far + 1.0 + turn_penalty
                next_state = (neighbor, direction_index)
                if next_cost >= best_cost.get(next_state, float("inf")):
                    continue

                best_cost[next_state] = next_cost
                came_from[next_state] = current_state
                priority = next_cost + hex_distance(neighbor, end)
                heappush(frontier, (priority, next_cost, rng.random(), neighbor, direction_index))

        return None

    def _reconstruct_path(
        self,
        came_from: dict[tuple[Coord, int], tuple[Coord, int] | None],
        end_state: tuple[Coord, int],
    ) -> list[Coord]:
        path: list[Coord] = []
        current: tuple[Coord, int] | None = end_state
        while current is not None:
            path.append(current[0])
            current = came_from[current]
        path.reverse()
        return path

    def _repair_river_adjacent_wasteland(
        self,
        terrain_map: dict[Coord, TerrainType],
        region_assignments: dict[Coord, int],
        region_primary_terrains: dict[int, TerrainType],
        difficulty: MapDifficulty,
    ) -> None:
        target_plain_ratio = TARGET_TERRAIN_RATIOS[difficulty][TerrainType.PLAIN]
        total_cells = len(terrain_map)
        river_cells = [coord for coord, terrain in terrain_map.items() if terrain is TerrainType.RIVER]
        for river_coord in river_cells:
            for neighbor in neighbors(river_coord):
                if terrain_map.get(neighbor) is not TerrainType.WASTELAND:
                    continue
                region_id = region_assignments[neighbor]
                primary = region_primary_terrains[region_id]
                if primary is not TerrainType.WASTELAND:
                    terrain_map[neighbor] = primary
                    continue

                plain_ratio = self._terrain_ratio(terrain_map, TerrainType.PLAIN)
                if plain_ratio + (1 / total_cells) <= target_plain_ratio + 0.05:
                    terrain_map[neighbor] = TerrainType.PLAIN
                else:
                    terrain_map[neighbor] = TerrainType.FOREST

    def _ensure_plain_exists(self, terrain_map: dict[Coord, TerrainType]) -> None:
        if any(terrain is TerrainType.PLAIN for terrain in terrain_map.values()):
            return

        for coord in sort_coords(terrain_map):
            if terrain_map[coord] is not TerrainType.RIVER:
                terrain_map[coord] = TerrainType.PLAIN
                return

    def _repair_quality(self, generated: GeneratedMap, config: GameConfig) -> GeneratedMap:
        terrain_map = {coord: tile.base_terrain for coord, tile in generated.board.items()}
        total_cells = len(terrain_map)
        thresholds = QUALITY_THRESHOLDS[config.map_difficulty]
        target_counts = self._terrain_target_counts(total_cells, config.map_difficulty)

        required_plain = ceil(total_cells * thresholds["plain_ratio_min"])
        while self._terrain_count(terrain_map, TerrainType.PLAIN) < required_plain:
            coord = self._pick_conversion_candidate(
                terrain_map,
                from_terrains=(TerrainType.WASTELAND, TerrainType.FOREST, TerrainType.MOUNTAIN),
            )
            if coord is None:
                break
            terrain_map[coord] = TerrainType.PLAIN

        max_wasteland = floor(total_cells * thresholds["wasteland_ratio_max"])
        while self._terrain_count(terrain_map, TerrainType.WASTELAND) > max_wasteland:
            coord = self._pick_wasteland_candidate(terrain_map)
            if coord is None:
                break
            terrain_map[coord] = TerrainType.FOREST

        required_buildable = ceil(total_cells * thresholds["buildable_ratio_min"])
        while self._buildable_count(terrain_map) < required_buildable:
            coord = self._pick_conversion_candidate(terrain_map, from_terrains=(TerrainType.WASTELAND,))
            if coord is None:
                break
            terrain_map[coord] = TerrainType.PLAIN

        max_component = floor(total_cells * thresholds["largest_wasteland_component_ratio_max"])
        largest_component = self._largest_component(terrain_map, TerrainType.WASTELAND)
        while len(largest_component) > max_component:
            coord = sorted(largest_component, key=coord_sort_key)[len(largest_component) // 2]
            terrain_map[coord] = TerrainType.FOREST
            largest_component = self._largest_component(terrain_map, TerrainType.WASTELAND)

        max_ordinary = floor(total_cells * MAX_ORDINARY_TERRAIN_RATIO)
        for terrain in ORDINARY_TERRAINS:
            while self._terrain_count(terrain_map, terrain) > max_ordinary:
                coord = self._pick_conversion_candidate(terrain_map, from_terrains=(terrain,))
                replacement = self._most_deficient_ordinary_terrain(terrain_map, target_counts, exclude=terrain)
                if coord is None or replacement is None:
                    break
                terrain_map[coord] = replacement

        self._repair_river_adjacent_wasteland(
            terrain_map,
            generated.region_assignments,
            generated.region_primary_terrains,
            config.map_difficulty,
        )
        self._ensure_plain_exists(terrain_map)

        board = {coord: Tile(base_terrain=terrain_map[coord]) for coord in sort_coords(terrain_map)}
        return GeneratedMap(
            board=board,
            region_assignments=generated.region_assignments,
            region_seeds=generated.region_seeds,
            region_primary_terrains=generated.region_primary_terrains,
            river_paths=generated.river_paths,
        )

    def _quality_errors(self, generated: GeneratedMap, config: GameConfig) -> list[str]:
        errors: list[str] = []
        thresholds = QUALITY_THRESHOLDS[config.map_difficulty]
        counts = generated.terrain_counts()
        total = generated.cell_count

        if generated.buildable_ratio() < thresholds["buildable_ratio_min"]:
            errors.append("buildable_ratio")
        if counts[TerrainType.PLAIN] / total < thresholds["plain_ratio_min"]:
            errors.append("plain_ratio")
        if counts[TerrainType.WASTELAND] / total > thresholds["wasteland_ratio_max"]:
            errors.append("wasteland_ratio")
        if generated.largest_component_size(TerrainType.WASTELAND) / total > thresholds[
            "largest_wasteland_component_ratio_max"
        ]:
            errors.append("largest_wasteland_component")
        if any(len(path) / total > MAX_RIVER_RATIO for path in generated.river_paths):
            errors.append("river_length")
        if any(counts[terrain] / total > MAX_ORDINARY_TERRAIN_RATIO for terrain in ORDINARY_TERRAINS):
            errors.append("ordinary_terrain_ratio")

        river_set = {coord for path in generated.river_paths for coord in path}
        for coord in river_set:
            for neighbor in neighbors(coord):
                tile = generated.board.get(neighbor)
                if tile is not None and tile.base_terrain is TerrainType.WASTELAND:
                    errors.append("wasteland_adjacent_to_river")
                    break
            if "wasteland_adjacent_to_river" in errors:
                break

        if counts[TerrainType.PLAIN] < 1:
            errors.append("plain_guarantee")
        return errors

    def _terrain_target_counts(
        self, cell_count: int, difficulty: MapDifficulty
    ) -> dict[TerrainType, int]:
        ratios = TARGET_TERRAIN_RATIOS[difficulty]
        raw_counts = {terrain: ratios[terrain] * cell_count for terrain in ORDINARY_TERRAINS}
        counts = {terrain: floor(raw_counts[terrain]) for terrain in ORDINARY_TERRAINS}
        remainder = cell_count - sum(counts.values())
        ranked = sorted(
            ORDINARY_TERRAINS,
            key=lambda terrain: (-(raw_counts[terrain] - counts[terrain]), terrain.value),
        )
        for terrain in ranked[:remainder]:
            counts[terrain] += 1
        return counts

    def _min_river_length(self, config: GameConfig) -> int:
        scale = 0.60 if config.map_difficulty is MapDifficulty.NORMAL else 0.75
        return ceil(2 * (config.map_size - 1) * scale)

    def _is_boundary(self, coord: Coord, map_size: int) -> bool:
        q, r = coord
        s = -q - r
        radius = map_size - 1
        return max(abs(q), abs(r), abs(s)) == radius

    def _terrain_count(self, terrain_map: dict[Coord, TerrainType], terrain: TerrainType) -> int:
        return sum(1 for current in terrain_map.values() if current is terrain)

    def _terrain_ratio(self, terrain_map: dict[Coord, TerrainType], terrain: TerrainType) -> float:
        return self._terrain_count(terrain_map, terrain) / len(terrain_map)

    def _buildable_count(self, terrain_map: dict[Coord, TerrainType]) -> int:
        return sum(
            1
            for terrain in terrain_map.values()
            if terrain in {TerrainType.PLAIN, TerrainType.FOREST, TerrainType.MOUNTAIN}
        )

    def _largest_component(
        self, terrain_map: dict[Coord, TerrainType], terrain_type: TerrainType
    ) -> list[Coord]:
        matching = {coord for coord, terrain in terrain_map.items() if terrain is terrain_type}
        seen: set[Coord] = set()
        largest: list[Coord] = []

        for start in sort_coords(matching):
            if start in seen:
                continue
            component: list[Coord] = []
            queue = deque([start])
            seen.add(start)
            while queue:
                current = queue.popleft()
                component.append(current)
                for neighbor in neighbors(current):
                    if neighbor in matching and neighbor not in seen:
                        seen.add(neighbor)
                        queue.append(neighbor)
            if len(component) > len(largest):
                largest = component
        return largest

    def _pick_conversion_candidate(
        self,
        terrain_map: dict[Coord, TerrainType],
        *,
        from_terrains: Iterable[TerrainType],
    ) -> Coord | None:
        terrain_set = set(from_terrains)
        candidates = [
            coord
            for coord in sort_coords(terrain_map)
            if terrain_map[coord] in terrain_set and terrain_map[coord] is not TerrainType.RIVER
        ]
        return candidates[0] if candidates else None

    def _pick_wasteland_candidate(self, terrain_map: dict[Coord, TerrainType]) -> Coord | None:
        largest_component = self._largest_component(terrain_map, TerrainType.WASTELAND)
        if largest_component:
            return sort_coords(largest_component)[0]
        return None

    def _most_deficient_ordinary_terrain(
        self,
        terrain_map: dict[Coord, TerrainType],
        target_counts: dict[TerrainType, int],
        *,
        exclude: TerrainType,
    ) -> TerrainType | None:
        current_counts = Counter(terrain_map.values())
        candidates = [terrain for terrain in ORDINARY_TERRAINS if terrain is not exclude]
        ranked = sorted(
            candidates,
            key=lambda terrain: (-(target_counts[terrain] - current_counts[terrain]), terrain.value),
        )
        return ranked[0] if ranked else None
