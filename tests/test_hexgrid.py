from __future__ import annotations

from microciv.utils.hexgrid import (
    HEX_DIRECTIONS,
    add_coords,
    coord_sort_key,
    enumerate_hex_coords,
    hex_distance,
    is_valid_hex,
    neighbors,
    sort_coords,
    valid_neighbors,
)


def test_hex_directions_follow_project_order() -> None:
    assert HEX_DIRECTIONS == ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))


def test_add_coords_and_neighbors() -> None:
    assert add_coords((1, -2), (0, 1)) == (1, -1)
    assert neighbors((0, 0)) == [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


def test_hex_distance_is_symmetric_and_matches_known_cases() -> None:
    assert hex_distance((0, 0), (0, 0)) == 0
    assert hex_distance((0, 0), (2, -1)) == 2
    assert hex_distance((2, -1), (0, 0)) == 2
    assert hex_distance((-2, 1), (1, -1)) == 3


def test_is_valid_hex_and_enumerate_hex_coords_match_formula() -> None:
    coords = enumerate_hex_coords(4)

    assert len(coords) == 37
    assert is_valid_hex((0, 0), 4)
    assert is_valid_hex((3, 0), 4)
    assert not is_valid_hex((4, 0), 4)
    assert not is_valid_hex((3, 1), 4)


def test_valid_neighbors_clip_to_map_bounds() -> None:
    assert valid_neighbors((0, 0), 4) == neighbors((0, 0))
    assert valid_neighbors((3, 0), 4) == [(3, -1), (2, 0), (2, 1)]


def test_coordinate_sorting_uses_q_then_r() -> None:
    coords = [(1, -2), (0, 1), (0, -1), (-1, 0)]

    assert coord_sort_key((2, -1)) == (2, -1)
    assert sort_coords(coords) == [(-1, 0), (0, -1), (0, 1), (1, -2)]
