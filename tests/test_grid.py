from __future__ import annotations

from microciv.utils.grid import (
    ALL_DIRECTIONS,
    CARDINAL_DIRECTIONS,
    add_coords,
    cardinal_neighbors,
    chebyshev_distance,
    coord_sort_key,
    enumerate_coords,
    is_valid_coord,
    manhattan_distance,
    moore_neighbors,
    sort_coords,
    valid_cardinal_neighbors,
    valid_moore_neighbors,
)


def test_square_grid_directions_and_neighbors_are_stable() -> None:
    assert CARDINAL_DIRECTIONS == ((1, 0), (0, 1), (-1, 0), (0, -1))
    assert len(ALL_DIRECTIONS) == 8
    assert add_coords((1, 2), (-1, 3)) == (0, 5)
    assert cardinal_neighbors((2, 2)) == [(3, 2), (2, 3), (1, 2), (2, 1)]
    assert moore_neighbors((0, 0)) == [
        (1, 0),
        (0, 1),
        (-1, 0),
        (0, -1),
        (1, 1),
        (-1, 1),
        (-1, -1),
        (1, -1),
    ]


def test_square_grid_distance_bounds_and_sorting_helpers() -> None:
    coords = enumerate_coords(4)

    assert len(coords) == 16
    assert is_valid_coord((0, 0), 4)
    assert is_valid_coord((3, 3), 4)
    assert not is_valid_coord((4, 0), 4)
    assert manhattan_distance((0, 0), (2, 3)) == 5
    assert chebyshev_distance((0, 0), (2, 3)) == 3
    assert valid_cardinal_neighbors((0, 0), 4) == [(1, 0), (0, 1)]
    assert valid_moore_neighbors((0, 0), 4) == [(1, 0), (0, 1), (1, 1)]
    assert coord_sort_key((2, 1)) == (2, 1)
    assert sort_coords([(2, 1), (0, 2), (0, 1)]) == [(0, 1), (0, 2), (2, 1)]
