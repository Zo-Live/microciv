"""Hex-grid coordinate helpers."""

from __future__ import annotations

from collections.abc import Iterable

Coord = tuple[int, int]

HEX_DIRECTIONS: tuple[Coord, ...] = (
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
)


def add_coords(a: Coord, b: Coord) -> Coord:
    """Add two axial coordinates."""
    return (a[0] + b[0], a[1] + b[1])


def coord_sort_key(coord: Coord) -> tuple[int, int]:
    """Return the canonical lexicographic sort key for a coordinate."""
    return coord


def neighbors(coord: Coord) -> list[Coord]:
    """Return the six adjacent axial coordinates."""
    return [add_coords(coord, direction) for direction in HEX_DIRECTIONS]


def hex_distance(a: Coord, b: Coord) -> int:
    """Return the axial hex distance between two coordinates."""
    aq, ar = a
    bq, br = b
    return max(abs(aq - bq), abs(ar - br), abs((-aq - ar) - (-bq - br)))


def is_valid_hex(coord: Coord, map_size: int) -> bool:
    """Check whether a coordinate lies inside the symmetric hex map."""
    if map_size < 1:
        raise ValueError("map_size must be positive.")
    q, r = coord
    s = -q - r
    radius = map_size - 1
    return max(abs(q), abs(r), abs(s)) <= radius


def enumerate_hex_coords(map_size: int) -> list[Coord]:
    """Return all legal coordinates inside a symmetric hex map."""
    if map_size < 1:
        raise ValueError("map_size must be positive.")

    coords: list[Coord] = []
    radius = map_size - 1
    for q in range(-radius, radius + 1):
        r_min = max(-radius, -q - radius)
        r_max = min(radius, -q + radius)
        for r in range(r_min, r_max + 1):
            coords.append((q, r))
    return coords


def valid_neighbors(coord: Coord, map_size: int) -> list[Coord]:
    """Return adjacent coordinates that stay inside the map."""
    return [neighbor for neighbor in neighbors(coord) if is_valid_hex(neighbor, map_size)]


def sort_coords(coords: Iterable[Coord]) -> list[Coord]:
    """Return coordinates sorted by the canonical lexicographic rule."""
    return sorted(coords, key=coord_sort_key)
