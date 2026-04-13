"""Square-grid coordinate helpers."""

from __future__ import annotations

from collections.abc import Iterable

Coord = tuple[int, int]

CARDINAL_DIRECTIONS: tuple[Coord, ...] = (
    (1, 0),
    (0, 1),
    (-1, 0),
    (0, -1),
)

DIAGONAL_DIRECTIONS: tuple[Coord, ...] = (
    (1, 1),
    (-1, 1),
    (-1, -1),
    (1, -1),
)

ALL_DIRECTIONS: tuple[Coord, ...] = CARDINAL_DIRECTIONS + DIAGONAL_DIRECTIONS


def add_coords(a: Coord, b: Coord) -> Coord:
    """Add two grid coordinates."""
    return (a[0] + b[0], a[1] + b[1])


def coord_sort_key(coord: Coord) -> tuple[int, int]:
    """Return the canonical lexicographic sort key for a coordinate."""
    return coord


def cardinal_neighbors(coord: Coord) -> list[Coord]:
    """Return the four edge-adjacent coordinates."""
    return [add_coords(coord, direction) for direction in CARDINAL_DIRECTIONS]


def moore_neighbors(coord: Coord) -> list[Coord]:
    """Return the eight surrounding coordinates."""
    return [add_coords(coord, direction) for direction in ALL_DIRECTIONS]


def manhattan_distance(a: Coord, b: Coord) -> int:
    """Return the edge-walk distance on the square grid."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def chebyshev_distance(a: Coord, b: Coord) -> int:
    """Return the king-move distance on the square grid."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def is_valid_coord(coord: Coord, map_size: int) -> bool:
    """Check whether a coordinate lies inside the square map."""
    if map_size < 1:
        raise ValueError("map_size must be positive.")
    x, y = coord
    return 0 <= x < map_size and 0 <= y < map_size


def enumerate_coords(map_size: int) -> list[Coord]:
    """Return all legal coordinates inside the square map."""
    if map_size < 1:
        raise ValueError("map_size must be positive.")
    return [(x, y) for y in range(map_size) for x in range(map_size)]


def valid_cardinal_neighbors(coord: Coord, map_size: int) -> list[Coord]:
    """Return edge-adjacent coordinates that stay inside the map."""
    return [
        neighbor for neighbor in cardinal_neighbors(coord) if is_valid_coord(neighbor, map_size)
    ]


def valid_moore_neighbors(coord: Coord, map_size: int) -> list[Coord]:
    """Return surrounding coordinates that stay inside the map."""
    return [neighbor for neighbor in moore_neighbors(coord) if is_valid_coord(neighbor, map_size)]


def sort_coords(coords: Iterable[Coord]) -> list[Coord]:
    """Return coordinates sorted by the canonical lexicographic rule."""
    return sorted(coords, key=coord_sort_key)
