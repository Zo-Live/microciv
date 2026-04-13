"""City-network management helpers."""

from __future__ import annotations

from collections import deque

from microciv.game.enums import OccupantType, TerrainType
from microciv.game.models import GameState, Network
from microciv.utils.grid import Coord, cardinal_neighbors, coord_sort_key, sort_coords


def is_network_passable(state: GameState, coord: Coord) -> bool:
    """Return whether a coordinate can participate in a city-network path."""
    tile = state.board.get(coord)
    if tile is None:
        return False
    return (
        tile.occupant in {OccupantType.CITY, OccupantType.ROAD}
        or tile.base_terrain is TerrainType.RIVER
    )


def recompute_networks(state: GameState) -> dict[int, Network]:
    """Rebuild the city-network partition and merge old network state when connected."""
    if not state.cities:
        state.networks = {}
        state.next_network_id = max(1, state.next_network_id)
        return {}

    coord_to_city_id = {city.coord: city_id for city_id, city in state.cities.items()}
    city_components = _discover_city_components(state, coord_to_city_id)

    old_networks = state.networks
    consumed_old_network_ids: set[int] = set()
    rebuilt: dict[int, Network] = {}
    next_network_id = state.next_network_id

    for component_city_ids in city_components:
        old_ids = sorted(
            {
                state.cities[city_id].network_id
                for city_id in component_city_ids
                if state.cities[city_id].network_id in old_networks
                and state.cities[city_id].network_id not in consumed_old_network_ids
            }
        )

        retained_id = old_ids[0] if old_ids else next_network_id
        if not old_ids:
            next_network_id += 1

        merged_network = Network(network_id=retained_id)
        merged_network.city_ids = set(component_city_ids)
        for old_id in old_ids:
            merged_network.merge_from(old_networks[old_id])
            consumed_old_network_ids.add(old_id)

        rebuilt[retained_id] = merged_network
        for city_id in component_city_ids:
            state.cities[city_id].network_id = retained_id

    state.networks = rebuilt
    if rebuilt:
        next_network_id = max(next_network_id, max(rebuilt) + 1)
    state.next_network_id = max(1, next_network_id)
    return rebuilt


def map_passable_coords_to_networks(state: GameState) -> dict[Coord, int]:
    """Return the network id associated with each passable coordinate connected to a city."""
    coord_to_city_id = {city.coord: city_id for city_id, city in state.cities.items()}
    if not coord_to_city_id:
        return {}

    mapping: dict[Coord, int] = {}
    seen: set[Coord] = set()
    for city_coord in sort_coords(coord_to_city_id):
        if city_coord in seen:
            continue
        network_id = state.cities[coord_to_city_id[city_coord]].network_id
        queue = deque([city_coord])
        seen.add(city_coord)
        while queue:
            current = queue.popleft()
            mapping[current] = network_id
            for neighbor in cardinal_neighbors(current):
                if neighbor in seen or not is_network_passable(state, neighbor):
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
    return mapping


def _discover_city_components(
    state: GameState, coord_to_city_id: dict[Coord, int]
) -> list[list[int]]:
    components: list[list[int]] = []
    seen: set[Coord] = set()

    for start in sort_coords(coord_to_city_id):
        if start in seen:
            continue
        component_city_ids: list[int] = []
        queue = deque([start])
        seen.add(start)
        while queue:
            current = queue.popleft()
            city_id = coord_to_city_id.get(current)
            if city_id is not None:
                component_city_ids.append(city_id)
            for neighbor in cardinal_neighbors(current):
                if neighbor in seen or not is_network_passable(state, neighbor):
                    continue
                seen.add(neighbor)
                queue.append(neighbor)

        components.append(
            sorted(
                component_city_ids, key=lambda city_id: coord_sort_key(state.cities[city_id].coord)
            )
        )

    return components
