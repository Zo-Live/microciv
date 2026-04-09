"""Map layout helpers for the minimal Textual UI."""

from __future__ import annotations

from microciv.game.models import GameState
from microciv.utils.hexgrid import coord_sort_key


def grouped_map_rows(state: GameState) -> list[tuple[int, list[tuple[int, int]], int]]:
    """Return rows grouped by axial r coordinate with a simple text indent."""
    row_map: dict[int, list[tuple[int, int]]] = {}
    for coord in sorted(state.board, key=coord_sort_key):
        row_map.setdefault(coord[1], []).append(coord)

    rows: list[tuple[int, list[tuple[int, int]], int]] = []
    radius = state.config.map_size - 1
    for r in range(-radius, radius + 1):
        coords = row_map.get(r, [])
        if not coords:
            continue
        indent = abs(r) * 4
        rows.append((r, coords, indent))
    return rows
