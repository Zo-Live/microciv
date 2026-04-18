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
class RiverMetrics:
    turn_ratio: float = 0.0
    secondary_span_ratio: float = 0.0
    secondary_coverage_ratio: float = 0.0
    secondary_reversal_ratio: float = 0.0
    meander_ratio: float = 0.0
    curvature_score: float = 0.0


@dataclass(slots=True, frozen=True)
class RiverSpec:
    shape: str
    start_edge: str
    end_edge: str
    lane: float
    amplitude: float
    allow_overlap: bool = False


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

    def river_metrics(self) -> RiverMetrics:
        if not self.river_paths:
            return RiverMetrics()
        map_size = int(self.cell_count**0.5)
        metrics = [_river_path_metrics(list(path), map_size) for path in self.river_paths]
        count = len(metrics)
        return RiverMetrics(
            turn_ratio=sum(metric.turn_ratio for metric in metrics) / count,
            secondary_span_ratio=sum(metric.secondary_span_ratio for metric in metrics) / count,
            secondary_coverage_ratio=(
                sum(metric.secondary_coverage_ratio for metric in metrics) / count
            ),
            secondary_reversal_ratio=(
                sum(metric.secondary_reversal_ratio for metric in metrics) / count
            ),
            meander_ratio=sum(metric.meander_ratio for metric in metrics) / count,
            curvature_score=sum(metric.curvature_score for metric in metrics) / count,
        )


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
        region_count = self._compute_region_count(config.map_size, config.map_difficulty)
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
        self._smooth_terrain(terrain_map, config.map_size, config.map_difficulty)

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

    def _compute_region_count(self, map_size: int, difficulty: MapDifficulty) -> int:
        base = max(4, min(9, round((map_size * map_size) / 72)))
        if difficulty is MapDifficulty.NORMAL:
            return max(4, base - 1)
        return min(11, base + 1)

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
        rounds = 1 if difficulty is MapDifficulty.NORMAL else 2

        for _ in range(rounds):
            for _region_id, cells in sorted(region_cells.items()):
                if len(cells) < 8:
                    continue
                if difficulty is MapDifficulty.NORMAL:
                    budget = max(2, len(cells) // 9)
                    patch_size = min(budget, max(2, len(cells) // 7))
                else:
                    budget = max(2, len(cells) // 7)
                    patch_size = min(budget, max(2, len(cells) // 5))
                seed = rng.choice(cells)
                patch = self._grow_patch(seed, patch_size, set(cells), rng)
                replacement = self._choose_patch_terrain(
                    difficulty=difficulty,
                    target_counts=target_counts,
                    global_counts=global_counts,
                    rng=rng,
                )
                for coord in patch:
                    global_counts[terrain_map[coord]] -= 1
                    terrain_map[coord] = replacement
                    global_counts[replacement] += 1

    def _grow_patch(
        self, seed: Coord, target_size: int, allowed: set[Coord], rng: Random
    ) -> list[Coord]:
        queue = deque([seed])
        seen = {seed}
        patch: list[Coord] = []

        while queue and len(patch) < target_size:
            current = queue.popleft()
            patch.append(current)
            neighbors = list(cardinal_neighbors(current))
            rng.shuffle(neighbors)
            for neighbor in neighbors:
                if neighbor in allowed and neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        return patch

    def _choose_patch_terrain(
        self,
        *,
        difficulty: MapDifficulty,
        target_counts: dict[TerrainType, int],
        global_counts: Counter[TerrainType],
        rng: Random,
    ) -> TerrainType:
        if difficulty is MapDifficulty.NORMAL:
            bias = {
                TerrainType.PLAIN: 6,
                TerrainType.FOREST: 3,
                TerrainType.MOUNTAIN: 1,
                TerrainType.WASTELAND: -2,
            }
        else:
            bias = {
                TerrainType.PLAIN: -1,
                TerrainType.FOREST: 0,
                TerrainType.MOUNTAIN: 4,
                TerrainType.WASTELAND: 5,
            }

        ranked = sorted(
            ORDINARY_TERRAINS,
            key=lambda terrain: (
                (target_counts[terrain] - global_counts[terrain]) + bias[terrain],
                rng.random(),
            ),
            reverse=True,
        )
        return ranked[0]

    def _smooth_terrain(
        self,
        terrain_map: dict[Coord, TerrainType],
        map_size: int,
        difficulty: MapDifficulty,
    ) -> None:
        passes = 2 if difficulty is MapDifficulty.NORMAL else 1
        threshold = 3 if difficulty is MapDifficulty.NORMAL else 4

        for _ in range(passes):
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
                if count >= threshold and (
                    difficulty is MapDifficulty.NORMAL
                    or most_common in {TerrainType.MOUNTAIN, TerrainType.WASTELAND}
                ):
                    terrain_map[coord] = most_common
                else:
                    terrain_map[coord] = current

    def _generate_rivers(
        self,
        config: GameConfig,
        terrain_map: dict[Coord, TerrainType],
        rng: Random,
    ) -> list[list[Coord]]:
        river_specs = self._plan_river_specs(config.map_difficulty, rng)
        available = set(terrain_map)
        river_coords: set[Coord] = set()
        paths: list[list[Coord]] = []

        for spec in river_specs:
            path: list[Coord] = []
            for _ in range(16):
                waypoints = self._build_river_waypoints(
                    map_size=config.map_size,
                    spec=spec,
                    rng=rng,
                )
                path = self._trace_river_path(
                    map_size=config.map_size,
                    available=available,
                    occupied_rivers=river_coords,
                    waypoints=waypoints,
                    allow_overlap=spec.allow_overlap,
                    rng=rng,
                )
                if path and self._river_path_is_acceptable(
                    path=path,
                    map_size=config.map_size,
                    difficulty=config.map_difficulty,
                ):
                    break
            if not path:
                waypoints = self._build_river_waypoints(
                    map_size=config.map_size,
                    spec=spec,
                    rng=rng,
                )
                start, end = waypoints[0], waypoints[-1]
                path = self._find_fallback_river_path(
                    map_size=config.map_size,
                    start=start,
                    end=end,
                    available=available,
                    occupied_rivers=river_coords,
                    allow_overlap=spec.allow_overlap,
                    rng=rng,
                )
            for coord in path:
                river_coords.add(coord)
                if coord in available:
                    available.remove(coord)
            paths.append(path)

        return paths

    def _plan_river_specs(
        self,
        difficulty: MapDifficulty,
        rng: Random,
    ) -> list[RiverSpec]:
        river_count = 1
        if difficulty is MapDifficulty.NORMAL:
            river_count = 2 if rng.random() < 0.35 else 1
        else:
            river_count = 2 if rng.random() < 0.75 else 1

        primary_horizontal = rng.random() < 0.5
        if river_count == 1:
            return [self._single_river_spec(primary_horizontal, rng)]

        if rng.random() < 0.5:
            return self._crossing_river_specs(primary_horizontal, rng)
        return self._non_crossing_river_specs(primary_horizontal, rng)

    def _single_river_spec(self, horizontal: bool, rng: Random) -> RiverSpec:
        lane = rng.uniform(0.28, 0.72)
        amplitude = rng.uniform(0.20, 0.34)
        if horizontal:
            edges = ("left", "right")
        else:
            edges = ("top", "bottom")
        shape = "s_curve" if rng.random() < 0.55 else "u_bend"
        return RiverSpec(
            shape=shape,
            start_edge=edges[0],
            end_edge=edges[1],
            lane=lane,
            amplitude=amplitude,
        )

    def _crossing_river_specs(self, primary_horizontal: bool, rng: Random) -> list[RiverSpec]:
        primary = self._single_river_spec(primary_horizontal, rng)
        secondary_horizontal = not primary_horizontal
        if secondary_horizontal:
            edges = ("left", "top" if primary.lane > 0.5 else "bottom")
        else:
            edges = ("top", "left" if primary.lane > 0.5 else "right")
        secondary = RiverSpec(
            shape="s_curve" if rng.random() < 0.5 else "u_bend",
            start_edge=edges[0],
            end_edge=edges[1],
            lane=rng.uniform(0.30, 0.70),
            amplitude=rng.uniform(0.16, 0.28),
            allow_overlap=True,
        )
        return [primary, secondary]

    def _non_crossing_river_specs(
        self,
        primary_horizontal: bool,
        rng: Random,
    ) -> list[RiverSpec]:
        low_lane = rng.uniform(0.18, 0.34)
        high_lane = rng.uniform(0.66, 0.82)
        primary_lane, secondary_lane = (
            (low_lane, high_lane) if rng.random() < 0.5 else (high_lane, low_lane)
        )
        if primary_horizontal:
            primary_edges = ("left", "right")
            secondary_edges = ("left", "top" if secondary_lane < 0.5 else "bottom")
        else:
            primary_edges = ("top", "bottom")
            secondary_edges = ("top", "left" if secondary_lane < 0.5 else "right")
        return [
            RiverSpec(
                shape="s_curve" if rng.random() < 0.5 else "u_bend",
                start_edge=primary_edges[0],
                end_edge=primary_edges[1],
                lane=primary_lane,
                amplitude=rng.uniform(0.18, 0.30),
            ),
            RiverSpec(
                shape="u_bend" if rng.random() < 0.55 else "s_curve",
                start_edge=secondary_edges[0],
                end_edge=secondary_edges[1],
                lane=secondary_lane,
                amplitude=rng.uniform(0.16, 0.26),
            ),
        ]

    def _build_river_waypoints(
        self,
        *,
        map_size: int,
        spec: RiverSpec,
        rng: Random,
    ) -> list[Coord]:
        start = self._edge_coord(
            map_size=map_size,
            edge=spec.start_edge,
            position=self._jitter_lane(spec.lane, 0.08, rng),
        )
        end = self._edge_coord(
            map_size=map_size,
            edge=spec.end_edge,
            position=self._jitter_lane(spec.lane, 0.08, rng),
        )
        return (
            self._build_s_curve_waypoints(map_size, start, end, spec, rng)
            if spec.shape == "s_curve"
            else self._build_u_bend_waypoints(map_size, start, end, spec, rng)
        )

    def _build_s_curve_waypoints(
        self,
        map_size: int,
        start: Coord,
        end: Coord,
        spec: RiverSpec,
        rng: Random,
    ) -> list[Coord]:
        horizontal = abs(end[0] - start[0]) >= abs(end[1] - start[1])
        anchors = [0.22, 0.48, 0.78]
        direction = 1 if spec.lane < 0.5 else -1
        if rng.random() < 0.5:
            direction *= -1
        points = [start]
        for index, anchor in enumerate(anchors):
            primary = anchor
            secondary = spec.lane + (direction * spec.amplitude * (1 if index != 1 else -1))
            points.append(
                self._normalized_coord(
                    map_size=map_size,
                    horizontal=horizontal,
                    primary=primary,
                    secondary=secondary,
                )
            )
            direction *= -1
        points.append(end)
        return self._dedupe_waypoints(points)

    def _build_u_bend_waypoints(
        self,
        map_size: int,
        start: Coord,
        end: Coord,
        spec: RiverSpec,
        rng: Random,
    ) -> list[Coord]:
        horizontal = abs(end[0] - start[0]) >= abs(end[1] - start[1])
        if spec.lane < 0.5:
            bend_target = min(0.92, spec.lane + spec.amplitude + 0.18)
        else:
            bend_target = max(0.08, spec.lane - spec.amplitude - 0.18)
        bend_target = self._jitter_lane(bend_target, 0.04, rng)
        points = [
            start,
            self._normalized_coord(
                map_size=map_size,
                horizontal=horizontal,
                primary=0.25,
                secondary=spec.lane + ((bend_target - spec.lane) * 0.35),
            ),
            self._normalized_coord(
                map_size=map_size,
                horizontal=horizontal,
                primary=0.52,
                secondary=bend_target,
            ),
            self._normalized_coord(
                map_size=map_size,
                horizontal=horizontal,
                primary=0.78,
                secondary=spec.lane + ((bend_target - spec.lane) * 0.30),
            ),
            end,
        ]
        return self._dedupe_waypoints(points)

    def _normalized_coord(
        self,
        *,
        map_size: int,
        horizontal: bool,
        primary: float,
        secondary: float,
    ) -> Coord:
        primary_index = round(max(0.0, min(1.0, primary)) * (map_size - 1))
        secondary_index = round(max(0.0, min(1.0, secondary)) * (map_size - 1))
        return (
            (primary_index, secondary_index)
            if horizontal
            else (secondary_index, primary_index)
        )

    def _edge_coord(self, *, map_size: int, edge: str, position: float) -> Coord:
        index = round(max(0.0, min(1.0, position)) * (map_size - 1))
        if edge == "left":
            return (0, index)
        if edge == "right":
            return (map_size - 1, index)
        if edge == "top":
            return (index, 0)
        return (index, map_size - 1)

    def _jitter_lane(self, lane: float, amount: float, rng: Random) -> float:
        return max(0.05, min(0.95, lane + rng.uniform(-amount, amount)))

    def _dedupe_waypoints(self, points: list[Coord]) -> list[Coord]:
        deduped: list[Coord] = []
        for point in points:
            if not deduped or deduped[-1] != point:
                deduped.append(point)
        return deduped

    def _trace_river_path(
        self,
        *,
        map_size: int,
        available: set[Coord],
        occupied_rivers: set[Coord],
        waypoints: list[Coord],
        allow_overlap: bool,
        rng: Random,
    ) -> list[Coord]:
        if len(waypoints) < 2:
            return []

        path: list[Coord] = []
        own_coords: set[Coord] = set()
        for start, end in zip(waypoints, waypoints[1:], strict=False):
            horizontal = abs(end[0] - start[0]) >= abs(end[1] - start[1])
            segment_available = available | own_coords | {start, end}
            segment_occupied = occupied_rivers if allow_overlap else (occupied_rivers | own_coords)
            target_curve = self._build_river_target_curve(
                map_size=map_size,
                control_points=[start, end],
                horizontal=horizontal,
            )
            segment = self._find_shaped_river_path(
                map_size=map_size,
                start=start,
                end=end,
                available=segment_available,
                occupied_rivers=segment_occupied,
                horizontal=horizontal,
                target_curve=target_curve,
                rng=rng,
            )
            if not segment:
                return []
            if path:
                segment = segment[1:]
            if not allow_overlap and any(coord in own_coords for coord in segment):
                return []
            path.extend(segment)
            own_coords.update(segment)

        if not allow_overlap and any(coord in occupied_rivers for coord in path[1:-1]):
            return []
        return path

    def _find_fallback_river_path(
        self,
        *,
        map_size: int,
        start: Coord,
        end: Coord,
        available: set[Coord],
        occupied_rivers: set[Coord],
        allow_overlap: bool,
        rng: Random,
    ) -> list[Coord]:
        path = self._find_river_path(
            map_size,
            start,
            end,
            available,
            occupied_rivers if allow_overlap else set(),
            rng,
        )
        if not allow_overlap and any(coord in occupied_rivers for coord in path[1:-1]):
            return []
        return path

    def _choose_river_endpoints(
        self, map_size: int, *, horizontal: bool, rng: Random
    ) -> tuple[Coord, Coord]:
        if horizontal:
            y_start = rng.randint(0, map_size - 1)
            y_end = rng.randint(0, map_size - 1)
            return (0, y_start), (map_size - 1, y_end)
        x_start = rng.randint(0, map_size - 1)
        x_end = rng.randint(0, map_size - 1)
        return (x_start, 0), (x_end, map_size - 1)

    def _choose_available_river_endpoints(
        self,
        *,
        map_size: int,
        horizontal: bool,
        available: set[Coord],
        rng: Random,
    ) -> tuple[Coord, Coord]:
        if horizontal:
            start_candidates = [(0, y) for y in range(map_size) if (0, y) in available]
            end_candidates = [
                (map_size - 1, y) for y in range(map_size) if (map_size - 1, y) in available
            ]
        else:
            start_candidates = [(x, 0) for x in range(map_size) if (x, 0) in available]
            end_candidates = [
                (x, map_size - 1) for x in range(map_size) if (x, map_size - 1) in available
            ]

        if not start_candidates or not end_candidates:
            return self._choose_river_endpoints(map_size, horizontal=horizontal, rng=rng)
        return (rng.choice(start_candidates), rng.choice(end_candidates))

    def _build_river_control_points(
        self,
        *,
        map_size: int,
        start: Coord,
        end: Coord,
        horizontal: bool,
        difficulty: MapDifficulty,
        rng: Random,
    ) -> list[Coord]:
        control_count = 3 if difficulty is MapDifficulty.NORMAL else 4
        control_points = [start]
        primary_limit = map_size - 1
        low_band_end = max(2, map_size // 4)
        high_band_start = min(map_size - 3, map_size - map_size // 4 - 1)
        start_secondary = start[1] if horizontal else start[0]
        prefer_high = start_secondary < map_size // 2

        for index in range(1, control_count + 1):
            primary = round((primary_limit * index) / (control_count + 1))
            use_high_band = prefer_high if index % 2 == 1 else not prefer_high
            if use_high_band:
                secondary = rng.randint(high_band_start, map_size - 1)
            else:
                secondary = rng.randint(0, low_band_end)
            control_points.append((primary, secondary) if horizontal else (secondary, primary))

        control_points.append(end)
        return control_points

    def _build_river_target_curve(
        self,
        *,
        map_size: int,
        control_points: list[Coord],
        horizontal: bool,
    ) -> dict[int, float]:
        axis_points = sorted(
            (point[0], point[1]) if horizontal else (point[1], point[0])
            for point in control_points
        )
        target_curve: dict[int, float] = {}

        for index in range(len(axis_points) - 1):
            primary_start, secondary_start = axis_points[index]
            primary_end, secondary_end = axis_points[index + 1]
            span = max(abs(primary_end - primary_start), 1)
            step = 1 if primary_end >= primary_start else -1
            for offset, primary in enumerate(range(primary_start, primary_end + step, step)):
                ratio = offset / span
                target_curve[primary] = secondary_start + (
                    (secondary_end - secondary_start) * ratio
                )

        low_primary = axis_points[0][0]
        high_primary = axis_points[-1][0]
        for primary in range(0, low_primary):
            target_curve[primary] = axis_points[0][1]
        for primary in range(high_primary + 1, map_size):
            target_curve[primary] = axis_points[-1][1]
        return target_curve

    def _find_river_path(
        self,
        map_size: int,
        start: Coord,
        end: Coord,
        available: set[Coord],
        occupied_rivers: set[Coord],
        rng: Random,
    ) -> list[Coord]:
        if start not in available and start not in occupied_rivers:
            return []
        if end not in available and end not in occupied_rivers:
            return []
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
                if (
                    neighbor not in available
                    and neighbor not in occupied_rivers
                    and neighbor != end
                ):
                    continue
                overlap_penalty = (
                    5
                    if neighbor in occupied_rivers and neighbor not in {start, end}
                    else 0
                )
                next_cost = cost_so_far[current] + 1 + overlap_penalty
                if neighbor not in cost_so_far or next_cost < cost_so_far[neighbor]:
                    cost_so_far[neighbor] = next_cost
                    priority = next_cost + manhattan_distance(neighbor, end)
                    came_from[neighbor] = current
                    heappush(frontier, (priority, rng.random(), neighbor))

        if end not in came_from:
            return []

        path: list[Coord] = []
        cursor: Coord | None = end
        while cursor is not None:
            path.append(cursor)
            cursor = came_from[cursor]
        path.reverse()
        return path

    def _find_shaped_river_path(
        self,
        *,
        map_size: int,
        start: Coord,
        end: Coord,
        available: set[Coord],
        occupied_rivers: set[Coord],
        horizontal: bool,
        target_curve: dict[int, float],
        rng: Random,
    ) -> list[Coord]:
        if start not in available and start not in occupied_rivers:
            return []
        if end not in available and end not in occupied_rivers:
            return []
        frontier: list[tuple[float, float, Coord]] = []
        heappush(frontier, (float(manhattan_distance(start, end)), rng.random(), start))
        came_from: dict[Coord, Coord | None] = {start: None}
        cost_so_far: dict[Coord, float] = {start: 0.0}

        while frontier:
            _, _, current = heappop(frontier)
            if current == end:
                break

            for neighbor in cardinal_neighbors(current):
                if not is_valid_coord(neighbor, map_size):
                    continue
                if (
                    neighbor not in available
                    and neighbor not in occupied_rivers
                    and neighbor != end
                ):
                    continue
                next_cost = cost_so_far[current] + self._river_step_cost(
                    current=current,
                    neighbor=neighbor,
                    occupied_rivers=occupied_rivers,
                    start=start,
                    end=end,
                    horizontal=horizontal,
                    target_curve=target_curve,
                )
                if neighbor not in cost_so_far or next_cost < cost_so_far[neighbor]:
                    cost_so_far[neighbor] = next_cost
                    priority = next_cost + self._river_heuristic(
                        neighbor=neighbor,
                        end=end,
                        horizontal=horizontal,
                        target_curve=target_curve,
                    )
                    came_from[neighbor] = current
                    heappush(frontier, (priority, rng.random(), neighbor))

        if end not in came_from:
            return []

        path: list[Coord] = []
        cursor: Coord | None = end
        while cursor is not None:
            path.append(cursor)
            cursor = came_from[cursor]
        path.reverse()
        return path

    def _river_step_cost(
        self,
        *,
        current: Coord,
        neighbor: Coord,
        occupied_rivers: set[Coord],
        start: Coord,
        end: Coord,
        horizontal: bool,
        target_curve: dict[int, float],
    ) -> float:
        primary = neighbor[0] if horizontal else neighbor[1]
        secondary = neighbor[1] if horizontal else neighbor[0]
        current_primary = current[0] if horizontal else current[1]
        current_secondary = current[1] if horizontal else current[0]
        desired_secondary = target_curve[primary]
        current_deviation = abs(current_secondary - target_curve[current_primary])
        next_deviation = abs(secondary - desired_secondary)
        lateral_move = (neighbor[1] - current[1]) if horizontal else (neighbor[0] - current[0])

        cost = 1.0 + (next_deviation * 0.9)
        if lateral_move != 0:
            cost += 0.35
        if next_deviation > current_deviation:
            cost += 0.45
        if neighbor in occupied_rivers and neighbor not in {start, end}:
            cost += 5.0
        return cost

    def _river_heuristic(
        self,
        *,
        neighbor: Coord,
        end: Coord,
        horizontal: bool,
        target_curve: dict[int, float],
    ) -> float:
        primary = neighbor[0] if horizontal else neighbor[1]
        secondary = neighbor[1] if horizontal else neighbor[0]
        desired_secondary = target_curve[primary]
        return manhattan_distance(neighbor, end) + abs(secondary - desired_secondary) * 0.7

    def _river_path_is_acceptable(
        self,
        *,
        path: list[Coord],
        map_size: int,
        difficulty: MapDifficulty,
    ) -> bool:
        metrics = _river_path_metrics(path, map_size)
        if difficulty is MapDifficulty.NORMAL:
            return (
                metrics.secondary_span_ratio >= 0.26
                and metrics.secondary_coverage_ratio >= 0.24
                and metrics.secondary_reversal_ratio >= 0.35
                and metrics.curvature_score >= 0.50
            )
        return (
            metrics.secondary_span_ratio >= 0.20
            and metrics.secondary_coverage_ratio >= 0.20
            and metrics.secondary_reversal_ratio >= 0.20
            and metrics.curvature_score >= 0.40
        )

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

        for path in generated.river_paths:
            metrics = _river_path_metrics(list(path), config.map_size)
            if config.map_difficulty is MapDifficulty.NORMAL:
                if metrics.secondary_span_ratio < 0.26:
                    errors.append("River secondary span below threshold.")
                if metrics.secondary_coverage_ratio < 0.24:
                    errors.append("River secondary coverage below threshold.")
                if metrics.secondary_reversal_ratio < 0.35:
                    errors.append("River reversal below threshold.")
                if metrics.curvature_score < 0.50:
                    errors.append("River curvature below threshold.")
            else:
                if metrics.secondary_span_ratio < 0.20:
                    errors.append("River secondary span below threshold.")
                if metrics.secondary_coverage_ratio < 0.20:
                    errors.append("River secondary coverage below threshold.")
                if metrics.secondary_reversal_ratio < 0.20:
                    errors.append("River reversal below threshold.")
                if metrics.curvature_score < 0.40:
                    errors.append("River curvature below threshold.")
            if errors:
                return errors

        return errors


def _river_path_metrics(path: list[Coord], map_size: int) -> RiverMetrics:
    if len(path) < 2:
        return RiverMetrics()

    x_values = [coord[0] for coord in path]
    y_values = [coord[1] for coord in path]
    x_span = max(x_values) - min(x_values)
    y_span = max(y_values) - min(y_values)
    horizontal = x_span >= y_span
    secondary_span = y_span if horizontal else x_span
    secondary_span_ratio = secondary_span / max(map_size - 1, 1)
    secondary_values = y_values if horizontal else x_values
    secondary_coverage_ratio = len(set(secondary_values)) / max(map_size, 1)

    directions: list[Coord] = []
    for current, nxt in zip(path, path[1:], strict=False):
        directions.append((nxt[0] - current[0], nxt[1] - current[1]))
    simplified = [directions[0]]
    for direction in directions[1:]:
        if direction != simplified[-1]:
            simplified.append(direction)

    turn_count = max(0, len(simplified) - 1)
    turn_ratio = turn_count / max(len(simplified), 1)
    secondary_reversal_ratio = min(_secondary_reversal_count(secondary_values) / 2, 1.0)
    meander_ratio = len(path) / max(manhattan_distance(path[0], path[-1]), 1)
    meander_component = min(max(meander_ratio - 1.0, 0.0) / 0.8, 1.0)
    curvature_score = (
        (secondary_span_ratio * 0.24)
        + (secondary_coverage_ratio * 0.18)
        + (secondary_reversal_ratio * 0.18)
        + (turn_ratio * 0.20)
        + (meander_component * 0.20)
    )
    return RiverMetrics(
        turn_ratio=turn_ratio,
        secondary_span_ratio=secondary_span_ratio,
        secondary_coverage_ratio=secondary_coverage_ratio,
        secondary_reversal_ratio=secondary_reversal_ratio,
        meander_ratio=meander_ratio,
        curvature_score=curvature_score,
    )


def _secondary_reversal_count(values: list[int]) -> int:
    deltas = [right - left for left, right in zip(values, values[1:], strict=False)]
    trend: list[int] = []
    for delta in deltas:
        if delta == 0:
            continue
        sign = 1 if delta > 0 else -1
        if not trend or trend[-1] != sign:
            trend.append(sign)
    return max(0, len(trend) - 1)
