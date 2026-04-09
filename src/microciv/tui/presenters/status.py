"""Text presenters for the minimal Textual UI."""

from __future__ import annotations

from microciv.game.enums import OccupantType, TerrainType
from microciv.game.models import GameState
from microciv.game.scoring import total_resources
from microciv.records.models import RecordEntry
from microciv.tui.presenters.game_session import GameSession, selected_city_id_for_coord


def present_setup_summary(
    *,
    mode_label: str,
    playback_label: str,
    map_size: int,
    turn_limit: int,
    difficulty_label: str,
    seed: int,
) -> str:
    """Render the current setup configuration."""
    lines = [
        f"Mode: {mode_label}",
        f"Playback: {playback_label}",
        f"Map Size: {map_size}",
        f"Turn Limit: {turn_limit}",
        f"Difficulty: {difficulty_label}",
        f"Seed: {seed}",
        "",
        "Phase 1 freeze:",
        "- Play uses manual actions only",
        "- Autoplay runs Baseline only",
        "- Final games are saved to Records",
    ]
    return "\n".join(lines)


def present_game_sidebar(session: GameSession) -> str:
    """Render the current game state for the right-side panel."""
    state = session.state
    resources = total_resources(state)
    selected_coord = state.selection.selected_coord
    selected_city_id = state.selection.selected_city_id or selected_city_id_for_coord(state, selected_coord)

    lines = [
        f"Mode: {state.config.mode.value}",
        f"Turn: {state.turn}/{state.config.turn_limit}",
        f"Score: {state.score}",
        "",
        f"Food: {resources.food}",
        f"Wood: {resources.wood}",
        f"Ore: {resources.ore}",
        f"Science: {resources.science}",
        "",
        f"Cities: {len(state.cities)}",
        f"Roads: {len(state.roads)}",
        f"Networks: {len(state.networks)}",
        "",
        "Legend: C city  = road  . plain",
        "        F forest  M mountain",
        "        ~ river   X wasteland",
        "",
    ]

    if selected_coord is None:
        lines.append("Selected Tile: none")
    else:
        tile = state.board[selected_coord]
        lines.extend(
            [
                f"Selected Tile: {selected_coord}",
                f"Terrain: {tile.base_terrain.value}",
                f"Occupant: {tile.occupant.value}",
            ]
        )

    if selected_city_id is not None:
        city = state.cities[selected_city_id]
        network = state.networks[city.network_id]
        lines.extend(
            [
                "",
                f"Selected City: #{city.city_id}",
                f"Founded: turn {city.founded_turn}",
                f"Network: #{city.network_id}",
                f"Buildings: {city.total_buildings}",
                (
                    "Counts: "
                    f"farm={city.buildings.farm}, "
                    f"lumber={city.buildings.lumber_mill}, "
                    f"mine={city.buildings.mine}, "
                    f"library={city.buildings.library}"
                ),
                f"Network Techs: {', '.join(sorted(tech.value for tech in network.unlocked_techs)) or 'none'}",
            ]
        )

    if state.message:
        lines.extend(["", f"Message: {state.message}"])

    if session.policy is None:
        lines.extend(
            [
                "",
                "Manual Tips:",
                "- Click a tile to inspect or act",
                "- City/building research uses selected city",
                "- Invalid actions show a message here",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Autoplay:",
                f"- Policy: {session.state.config.policy_type.value}",
                f"- Playback: {session.state.config.playback_mode.value}",
                "- Speed batches decisions between refreshes",
            ]
        )

    return "\n".join(lines)


def present_final_summary(session: GameSession) -> str:
    """Render the end-of-game summary."""
    state = session.state
    resources = total_resources(state)
    lines = [
        f"Final Score: {state.score}",
        f"Turns Played: {state.config.turn_limit}",
        f"Cities: {len(state.cities)}",
        f"Roads: {len(state.roads)}",
        f"Networks: {len(state.networks)}",
        "",
        f"Food: {resources.food}",
        f"Wood: {resources.wood}",
        f"Ore: {resources.ore}",
        f"Science: {resources.science}",
        "",
        "Natural finishes are saved automatically.",
    ]
    if session.saved_record is not None:
        lines.extend(["", f"Saved Record: #{session.saved_record.record_id}"])
    return "\n".join(lines)


def present_records_listing(records: list[RecordEntry], selected_index: int) -> str:
    """Render a compact records list."""
    if not records:
        return "No saved records."

    lines: list[str] = []
    for index, record in enumerate(records):
        marker = ">" if index == selected_index else " "
        lines.append(
            f"{marker} #{record.record_id} {record.timestamp} "
            f"{record.mode} score={record.final_score}"
        )
    lines.append("")
    lines.append("Use Previous / Next to browse, Export CSV to dump the table.")
    return "\n".join(lines)


def present_record_detail(record: RecordEntry | None) -> str:
    """Render a selected record detail panel."""
    if record is None:
        return "No record selected."

    lines = [
        f"Record #{record.record_id}",
        f"Timestamp: {record.timestamp}",
        f"Mode: {record.mode}",
        f"AI: {record.ai_type}",
        f"Playback: {record.playback_mode or '-'}",
        f"Map: size={record.map_size} difficulty={record.map_difficulty} seed={record.seed}",
        f"Turns: {record.actual_turns}/{record.turn_limit}",
        f"Final Score: {record.final_score}",
        "",
        f"Cities: {record.city_count}",
        f"Buildings: {record.building_count}",
        f"Techs: {record.tech_count}",
        f"Food/Wood/Ore/Science: {record.food}/{record.wood}/{record.ore}/{record.science}",
        "",
        "Stats:",
        (
            f"city={record.build_city_count}, road={record.build_road_count}, "
            f"farm={record.build_farm_count}, lumber={record.build_lumber_mill_count}, "
            f"mine={record.build_mine_count}, library={record.build_library_count}"
        ),
        (
            f"agri={record.research_agriculture_count}, "
            f"log={record.research_logging_count}, "
            f"mining={record.research_mining_count}, "
            f"edu={record.research_education_count}, skip={record.skip_count}"
        ),
        "",
        f"Final Map Tiles: {len(record.final_map)}",
        f"Saved Cities/Roads/Networks: {len(record.cities)}/{len(record.roads)}/{len(record.networks)}",
    ]
    return "\n".join(lines)


def terrain_short_name(terrain: TerrainType, occupant: OccupantType) -> str:
    """Return the tile glyph used in the map widget."""
    if occupant is OccupantType.CITY:
        return "C"
    if occupant is OccupantType.ROAD:
        return "="
    if terrain is TerrainType.PLAIN:
        return "."
    if terrain is TerrainType.FOREST:
        return "F"
    if terrain is TerrainType.MOUNTAIN:
        return "M"
    if terrain is TerrainType.RIVER:
        return "~"
    return "X"
