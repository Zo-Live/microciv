"""High-throughput tabular artifacts for large experiment analysis."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from microciv.game.enums import (
    MapDifficulty,
    Mode,
    OccupantType,
    PlaybackMode,
    PolicyType,
    TechType,
    TerrainType,
)
from microciv.game.models import (
    BuildingCounts,
    City,
    GameConfig,
    GameState,
    Network,
    ResourcePool,
    Road,
    Tile,
)
from microciv.game.scoring import score_breakdown
from microciv.records.models import RecordEntry

ARTIFACT_SCHEMA_VERSION: Final[int] = 1
ARTIFACT_MANIFEST_FILENAME: Final[str] = "artifact_manifest.json"
ARTIFACT_TABLES: Final[tuple[str, ...]] = (
    "macro",
    "turn_scores",
    "decisions",
    "actions",
    "behavior",
    "maps",
    "score_breakdowns",
)
TAIL_WINDOW: Final[int] = 20
GREEDY_LABEL: Final[str] = "Greedy"
RANDOM_LABEL: Final[str] = "Random"
SEARCH_LABEL: Final[str] = "Search"


@dataclass(slots=True, frozen=True)
class ArtifactWriteResult:
    """Metadata for a written artifact part."""

    output_dir: Path
    file_format: str
    table_paths: dict[str, list[str]]
    row_counts: dict[str, int]


def is_artifact_dir(path: Path) -> bool:
    """Return whether a path looks like a MicroCiv artifact directory."""
    return path.is_dir() and (
        (path / ARTIFACT_MANIFEST_FILENAME).exists()
        or any(path.glob("*.parquet"))
        or any(path.glob("*.jsonl"))
    )


def policy_variant_label(record: RecordEntry) -> str:
    """Return the analysis grouping label for a record."""
    if record.ai_type != SEARCH_LABEL:
        return record.ai_type
    for context in record.decision_contexts:
        if (
            context.search_depth is None
            and context.search_beam_width is None
            and context.search_candidate_limit is None
        ):
            continue
        depth = context.search_depth if context.search_depth is not None else "?"
        beam_width = context.search_beam_width if context.search_beam_width is not None else "?"
        candidate_limit = (
            context.search_candidate_limit if context.search_candidate_limit is not None else "?"
        )
        return f"Search d{depth} b{beam_width} c{candidate_limit}"
    return "Search d? b? c?"


def write_record_artifacts(
    records: list[RecordEntry],
    output_dir: Path,
    *,
    preferred_format: str = "parquet",
    part_name: str | None = None,
    write_manifest: bool = True,
) -> ArtifactWriteResult:
    """Write Records as analysis artifacts and return file metadata."""
    rows_by_table = rows_for_records(records)
    result = write_artifact_rows(
        rows_by_table,
        output_dir,
        preferred_format=preferred_format,
        part_name=part_name,
    )
    if write_manifest:
        write_artifact_manifest(
            output_dir,
            result=result,
            record_count=len(records),
            mode="single",
        )
    return result


def rows_for_records(records: list[RecordEntry]) -> dict[str, list[dict[str, object]]]:
    """Build all artifact table rows for a sequence of records."""
    rows: dict[str, list[dict[str, object]]] = {table: [] for table in ARTIFACT_TABLES}
    for record in records:
        rows["macro"].append(record_macro_row(record))
        rows["behavior"].append(record_behavior_row(record))
        rows["maps"].append(record_map_row(record))
        rows["score_breakdowns"].append(record_score_breakdown_row(record))
        rows["turn_scores"].extend(record_turn_score_rows(record))
        rows["decisions"].extend(record_decision_rows(record))
        rows["actions"].extend(record_action_rows(record))
    return rows


def write_artifact_rows(
    rows_by_table: dict[str, list[dict[str, object]]],
    output_dir: Path,
    *,
    preferred_format: str = "parquet",
    part_name: str | None = None,
) -> ArtifactWriteResult:
    """Write prebuilt artifact rows as Parquet or JSONL."""
    output_dir.mkdir(parents=True, exist_ok=True)
    file_format = "parquet" if preferred_format == "parquet" and _has_pyarrow() else "jsonl"
    table_paths: dict[str, list[str]] = {}
    row_counts: dict[str, int] = {}

    for table in ARTIFACT_TABLES:
        rows = rows_by_table.get(table, [])
        row_counts[table] = len(rows)
        if not rows:
            table_paths[table] = []
            continue
        suffix = f"_{part_name}" if part_name else ""
        path = output_dir / f"{table}{suffix}.{file_format}"
        if file_format == "parquet":
            _write_parquet(path, rows)
        else:
            _write_jsonl(path, rows)
        table_paths[table] = [str(path)]

    return ArtifactWriteResult(
        output_dir=output_dir,
        file_format=file_format,
        table_paths=table_paths,
        row_counts=row_counts,
    )


def write_artifact_manifest(
    output_dir: Path,
    *,
    result: ArtifactWriteResult,
    record_count: int,
    mode: str,
    extra: dict[str, object] | None = None,
) -> Path:
    """Write an artifact manifest for one or more table files."""
    manifest = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "mode": mode,
        "record_count": record_count,
        "file_format": result.file_format,
        "tables": {
            table: {
                "row_count": result.row_counts.get(table, 0),
                "paths": result.table_paths.get(table, []),
            }
            for table in ARTIFACT_TABLES
        },
    }
    if extra:
        manifest.update(extra)
    path = output_dir / ARTIFACT_MANIFEST_FILENAME
    path.write_bytes(dumps_json_bytes(manifest, indent=True) + b"\n")
    return path


def read_artifact_table(artifact_dir: Path, table: str, pd: Any) -> Any:
    """Read an artifact table into a pandas DataFrame."""
    parquet_paths = sorted(artifact_dir.glob(f"{table}*.parquet"))
    jsonl_paths = sorted(artifact_dir.glob(f"{table}*.jsonl"))
    frames = []
    for path in parquet_paths:
        frames.append(pd.read_parquet(path))
    for path in jsonl_paths:
        frames.append(pd.read_json(path, lines=True))
    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True)


def read_artifact_frames(artifact_dir: Path, pd: Any) -> dict[str, Any]:
    """Read every known artifact table into DataFrames."""
    return {table: read_artifact_table(artifact_dir, table, pd) for table in ARTIFACT_TABLES}


def record_macro_row(record: RecordEntry) -> dict[str, object]:
    """Return the per-game macro analysis row."""
    connected_cities, largest_network_size = _connected_city_metrics(record)
    isolated_cities = sum(
        len(network.city_ids) for network in record.networks if len(network.city_ids) == 1
    )
    score_drop_turns, worst_score_drop = _score_drop_metrics(record)
    first_negative_food_turn = _first_turn_matching(
        record.turn_snapshots,
        lambda snapshot: snapshot.food < 0,
    )
    negative_food_turns = _count_turns_matching(
        record.turn_snapshots,
        lambda snapshot: snapshot.food < 0,
    )
    first_starvation_turn = _first_turn_matching(
        record.turn_snapshots,
        lambda snapshot: snapshot.starving_network_count > 0,
    )
    starvation_turns = _count_turns_matching(
        record.turn_snapshots,
        lambda snapshot: snapshot.starving_network_count > 0,
    )
    greedy_contexts = [context for context in record.decision_contexts if context.greedy_stage]
    food_pressures = [
        context.greedy_food_pressure
        for context in greedy_contexts
        if context.greedy_food_pressure is not None
    ]
    tail_actions = record.action_log[-TAIL_WINDOW:]
    tail_skip_ratio = sum(1 for action in tail_actions if action.action_type == "skip") / max(
        len(tail_actions), 1
    )
    base = _record_base_row(record)
    base.update(
        {
            "final_score": record.final_score,
            "city_count": record.city_count,
            "road_count": len(record.roads),
            "building_count": record.building_count,
            "tech_count": record.tech_count,
            "network_count": len(record.networks),
            "connected_cities": connected_cities,
            "isolated_cities": isolated_cities,
            "largest_network_size": largest_network_size,
            "starving_network_count": sum(1 for network in record.networks if network.food <= 0),
            "food": record.food,
            "wood": record.wood,
            "ore": record.ore,
            "science": record.science,
            "skip_count": record.skip_count,
            "actual_turns": record.actual_turns,
            "decision_count": record.decision_count,
            "decision_time_ms_total": record.decision_time_ms_total,
            "decision_time_ms_avg": record.decision_time_ms_avg,
            "decision_time_ms_max": record.decision_time_ms_max,
            "turn_elapsed_ms_total": record.turn_elapsed_ms_total,
            "turn_elapsed_ms_avg": record.turn_elapsed_ms_avg,
            "turn_elapsed_ms_max": record.turn_elapsed_ms_max,
            "session_elapsed_ms": record.session_elapsed_ms,
            "has_starvation": int(_has_starvation(record)),
            "first_negative_food_turn": first_negative_food_turn,
            "negative_food_turns": negative_food_turns,
            "first_starvation_turn": first_starvation_turn,
            "starvation_turns": starvation_turns,
            "longest_starvation_streak": _longest_streak(
                record.turn_snapshots,
                lambda snapshot: snapshot.starving_network_count > 0,
            ),
            "max_starving_networks_seen": max(
                (snapshot.starving_network_count for snapshot in record.turn_snapshots),
                default=0,
            ),
            "final_starving_network_count": sum(
                1 for network in record.networks if network.food <= 0
            ),
            "final_largest_network_size": largest_network_size,
            "final_connected_city_ratio": connected_cities / max(record.city_count, 1),
            "late_game_no_growth_streak": _late_game_no_growth_streak(record),
            "score_drop_turns": score_drop_turns,
            "worst_score_drop": worst_score_drop,
            "first_skip_turn": _first_turn_matching(
                record.action_log,
                lambda action: action.action_type == "skip",
            ),
            "tail_skip_ratio": tail_skip_ratio,
            "first_stage_fill_turn": _first_turn_matching(
                greedy_contexts,
                lambda context: context.greedy_stage == "fill",
            ),
            "fill_stage_turns": _count_turns_matching(
                greedy_contexts,
                lambda context: context.greedy_stage == "fill",
            ),
            "first_stage_expand_reopen_turn": _first_turn_matching(
                greedy_contexts,
                lambda context: context.greedy_stage == "expand_reopen",
            ),
            "expand_reopen_stage_turns": _count_turns_matching(
                greedy_contexts,
                lambda context: context.greedy_stage == "expand_reopen",
            ),
            "rescue_stage_turns": _count_turns_matching(
                greedy_contexts,
                lambda context: context.greedy_stage == "rescue",
            ),
            "avg_food_pressure": (
                sum(food_pressures) / len(food_pressures) if food_pressures else 0.0
            ),
            "score_per_city": record.final_score / max(record.city_count, 1),
            "score_per_building": record.final_score / max(record.building_count, 1),
            "buildings_per_city": record.building_count / max(record.city_count, 1),
            "roads_per_city": len(record.roads) / max(record.city_count, 1),
            "connected_city_ratio": connected_cities / max(record.city_count, 1),
        }
    )
    return base


def record_turn_score_rows(record: RecordEntry) -> list[dict[str, object]]:
    """Return per-turn score rows for a record."""
    rows: list[dict[str, object]] = []
    base = _record_base_row(record)
    for snapshot in record.turn_snapshots:
        if not snapshot.score_breakdown:
            continue
        row = {
            **base,
            "turn": snapshot.turn,
            "score": snapshot.score,
        }
        for key, value in snapshot.score_breakdown.items():
            row[f"score_{key}"] = value
        rows.append(row)
    return rows


def record_decision_rows(record: RecordEntry) -> list[dict[str, object]]:
    """Return per-turn decision rows for a record."""
    rows: list[dict[str, object]] = []
    base = _record_base_row(record)
    for context in record.decision_contexts:
        row: dict[str, object] = {
            **base,
            "turn": context.turn,
            "chosen_action_type": context.chosen_action_type or "",
            "greedy_stage": context.greedy_stage or "",
            "greedy_priority": context.greedy_priority or "",
            "greedy_best_action_type": context.greedy_best_action_type or "",
            "greedy_best_score": context.greedy_best_score,
            "greedy_best_delta_score": context.greedy_best_delta_score,
            "greedy_food_pressure": context.greedy_food_pressure,
            "greedy_starving_networks": context.greedy_starving_networks,
            "greedy_connected_cities": context.greedy_connected_cities,
            "greedy_total_food": context.greedy_total_food,
            "greedy_network_count": context.greedy_network_count,
            "greedy_best_connection_steps": context.greedy_best_connection_steps,
            "greedy_best_future_network_starving": (
                int(context.greedy_best_future_network_starving)
                if context.greedy_best_future_network_starving is not None
                else None
            ),
            "legal_actions_count": context.legal_actions_count,
            "legal_build_city_count": context.legal_build_city_count,
            "legal_build_road_count": context.legal_build_road_count,
            "legal_build_building_count": context.legal_build_building_count,
            "legal_research_tech_count": context.legal_research_tech_count,
            "legal_skip_count": context.legal_skip_count,
            "search_depth": context.search_depth,
            "search_base_depth": context.search_base_depth,
            "search_max_depth": context.search_max_depth,
            "search_depth_reason": context.search_depth_reason or "",
            "search_beam_width": context.search_beam_width,
            "search_candidate_limit": context.search_candidate_limit,
            "search_nodes_expanded": context.search_nodes_expanded,
            "search_candidates_considered": context.search_candidates_considered,
            "search_leaf_count": context.search_leaf_count,
            "search_best_value": context.search_best_value,
            "search_sequence_length": len(context.search_best_sequence),
            "search_first_action_type": (
                context.search_best_sequence[0].action_type if context.search_best_sequence else ""
            ),
        }
        for key, value in context.greedy_score_breakdown.items():
            row[f"score_{key}"] = value
        for key, value in context.greedy_best_site_budget.items():
            row[f"site_{key}"] = value
        for key, value in context.greedy_best_future_network_budget.items():
            row[f"future_network_{key}"] = value
        rows.append(row)
    return rows


def record_action_rows(record: RecordEntry) -> list[dict[str, object]]:
    """Return per-action rows for a record."""
    rows: list[dict[str, object]] = []
    base = _record_base_row(record)
    for index, action in enumerate(record.action_log):
        rows.append(
            {
                **base,
                "action_index": index,
                "turn": action.turn,
                "action_type": action.action_type,
                "x": action.x,
                "y": action.y,
                "city_id": action.city_id,
                "building_type": action.building_type,
                "tech_type": action.tech_type,
            }
        )
    return rows


def record_behavior_row(record: RecordEntry) -> dict[str, object]:
    """Return per-game behavior percentages."""
    action_counts = Counter(entry.action_type for entry in record.action_log)
    total_actions = sum(action_counts.values()) or 1
    legal_denominator = sum(ctx.legal_actions_count for ctx in record.decision_contexts) or 1
    legal_city = sum(ctx.legal_build_city_count for ctx in record.decision_contexts)
    legal_road = sum(ctx.legal_build_road_count for ctx in record.decision_contexts)
    legal_building = sum(ctx.legal_build_building_count for ctx in record.decision_contexts)
    legal_tech = sum(ctx.legal_research_tech_count for ctx in record.decision_contexts)
    tail_actions = record.action_log[-TAIL_WINDOW:]
    tail_counts = Counter(entry.action_type for entry in tail_actions)
    tail_total = len(tail_actions) or 1
    chosen_city_pct = action_counts["build_city"] / total_actions * 100
    chosen_road_pct = action_counts["build_road"] / total_actions * 100
    chosen_building_pct = action_counts["build_building"] / total_actions * 100
    chosen_tech_pct = action_counts["research_tech"] / total_actions * 100

    row = _record_base_row(record)
    row.update(
        {
            "chosen_city_pct": chosen_city_pct,
            "chosen_road_pct": chosen_road_pct,
            "chosen_building_pct": chosen_building_pct,
            "chosen_tech_pct": chosen_tech_pct,
            "chosen_skip_pct": action_counts["skip"] / total_actions * 100,
            "legal_city_pct": legal_city / legal_denominator * 100,
            "legal_road_pct": legal_road / legal_denominator * 100,
            "legal_building_pct": legal_building / legal_denominator * 100,
            "legal_tech_pct": legal_tech / legal_denominator * 100,
            "chosen_minus_legal_city_pct": chosen_city_pct - (legal_city / legal_denominator * 100),
            "chosen_minus_legal_road_pct": chosen_road_pct - (legal_road / legal_denominator * 100),
            "chosen_minus_legal_building_pct": chosen_building_pct
            - (legal_building / legal_denominator * 100),
            "chosen_minus_legal_tech_pct": chosen_tech_pct - (legal_tech / legal_denominator * 100),
            "tail_build_city_pct": tail_counts["build_city"] / tail_total * 100,
            "tail_build_road_pct": tail_counts["build_road"] / tail_total * 100,
            "tail_build_building_pct": tail_counts["build_building"] / tail_total * 100,
            "tail_build_tech_pct": tail_counts["research_tech"] / tail_total * 100,
            "tail_skip_pct": tail_counts["skip"] / tail_total * 100,
        }
    )
    return row


def record_map_row(record: RecordEntry) -> dict[str, object]:
    """Return per-game map composition metrics."""
    terrain_counts = Counter(tile.base_terrain for tile in record.final_map)
    river = {(tile.x, tile.y) for tile in record.final_map if tile.base_terrain == "river"}
    turns = 0
    straights = 0
    for x, y in river:
        neighbors = [
            (nx, ny)
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            if (nx, ny) in river
        ]
        if len(neighbors) != 2:
            continue
        same_x = neighbors[0][0] == x == neighbors[1][0]
        same_y = neighbors[0][1] == y == neighbors[1][1]
        if same_x or same_y:
            straights += 1
        else:
            turns += 1

    total = len(record.final_map) or 1
    buildable = terrain_counts["plain"] + terrain_counts["forest"] + terrain_counts["mountain"]
    row = _record_base_row(record)
    row.update(
        {
            "buildable_ratio": buildable / total,
            "plain_ratio": terrain_counts["plain"] / total,
            "wasteland_ratio": terrain_counts["wasteland"] / total,
            "river_ratio": terrain_counts["river"] / total,
            "river_cells": len(river),
            "river_turn_ratio": turns / max(turns + straights, 1),
        }
    )
    return row


def record_score_breakdown_row(record: RecordEntry) -> dict[str, object]:
    """Return the final score breakdown row."""
    breakdown = score_breakdown(record_to_state(record))
    row = _record_base_row(record)
    row.update(
        {
            "city_score": breakdown.city_score,
            "connected_city_score": breakdown.connected_city_score,
            "resource_ring_score": breakdown.resource_ring_score,
            "river_access_score": breakdown.river_access_score,
            "city_composition_bonus": breakdown.city_composition_bonus,
            "building_score": breakdown.building_score,
            "tech_score": breakdown.tech_score,
            "building_utilization_score": breakdown.building_utilization_score,
            "resource_score": breakdown.resource_score,
            "food_score": breakdown.food_score,
            "wood_score": breakdown.wood_score,
            "ore_score": breakdown.ore_score,
            "science_score": breakdown.science_score,
            "library_science_bonus": breakdown.library_science_bonus,
            "building_mismatch_penalty": breakdown.building_mismatch_penalty,
            "starving_network_penalty": breakdown.starving_network_penalty,
            "fragmented_network_penalty": breakdown.fragmented_network_penalty,
            "isolated_city_penalty": breakdown.isolated_city_penalty,
            "unproductive_road_penalty": breakdown.unproductive_road_penalty,
            "total_score": breakdown.total,
        }
    )
    return row


def record_to_state(record: RecordEntry) -> GameState:
    """Rebuild a final GameState from a persisted record."""
    config = GameConfig(
        mode=Mode.PLAY if record.mode == "play" else Mode.AUTOPLAY,
        map_size=record.map_size,
        turn_limit=record.turn_limit,
        map_difficulty=MapDifficulty(record.map_difficulty),
        policy_type=_policy_type_from_label(record.ai_type),
        playback_mode=_playback_mode_from_label(record.playback_mode),
        seed=record.seed,
    )
    state = GameState.empty(config)
    state.turn = max(record.actual_turns, 1)
    state.score = record.final_score
    state.board = {
        (tile.x, tile.y): Tile(
            base_terrain=TerrainType(tile.base_terrain),
            occupant=OccupantType(tile.occupant),
        )
        for tile in record.final_map
    }
    state.cities = {
        city.city_id: City(
            city_id=city.city_id,
            coord=(city.x, city.y),
            founded_turn=city.founded_turn,
            network_id=city.network_id,
            buildings=BuildingCounts(
                farm=city.farm,
                lumber_mill=city.lumber_mill,
                mine=city.mine,
                library=city.library,
            ),
        )
        for city in record.cities
    }
    state.roads = {
        road.road_id: Road(
            road_id=road.road_id,
            coord=(road.x, road.y),
            built_turn=road.built_turn,
        )
        for road in record.roads
    }
    state.networks = {
        network.network_id: Network(
            network_id=network.network_id,
            city_ids=set(network.city_ids),
            resources=ResourcePool(
                food=network.food,
                wood=network.wood,
                ore=network.ore,
                science=network.science,
            ),
            unlocked_techs={TechType(name) for name in network.unlocked_techs},
            consecutive_starving_turns=network.consecutive_starving_turns,
        )
        for network in record.networks
    }
    return state


def _record_base_row(record: RecordEntry) -> dict[str, object]:
    return {
        "record_id": record.record_id,
        "seed": record.seed,
        "ai_type": record.ai_type,
        "policy_variant": policy_variant_label(record),
        "map_size": record.map_size,
        "turn_limit": record.turn_limit,
        "map_difficulty": record.map_difficulty,
    }


def _record_match_key(record: RecordEntry) -> tuple[int, int, int, str]:
    return (record.seed, record.map_size, record.turn_limit, record.map_difficulty)


def _has_starvation(record: RecordEntry) -> bool:
    return any(snapshot.starving_network_count > 0 for snapshot in record.turn_snapshots) or any(
        network.food <= 0 for network in record.networks
    )


def _connected_city_metrics(record: RecordEntry) -> tuple[int, int]:
    connected_cities = sum(
        len(network.city_ids) for network in record.networks if len(network.city_ids) >= 2
    )
    largest_network_size = max((len(network.city_ids) for network in record.networks), default=0)
    return connected_cities, largest_network_size


def _score_drop_metrics(record: RecordEntry) -> tuple[int, int]:
    snapshots = record.turn_snapshots
    if len(snapshots) < 2:
        return 0, 0
    drop_count = 0
    worst_drop = 0
    for previous, current in zip(snapshots, snapshots[1:], strict=False):
        delta = current.score - previous.score
        if delta < 0:
            drop_count += 1
            worst_drop = min(worst_drop, delta)
    return drop_count, worst_drop


def _late_game_no_growth_streak(record: RecordEntry) -> int:
    snapshots = record.turn_snapshots[-TAIL_WINDOW:]
    if len(snapshots) < 2:
        return 0
    best = 0
    current = 0
    previous_signature = (
        snapshots[0].city_count,
        snapshots[0].building_count,
        snapshots[0].tech_count,
        snapshots[0].road_count,
    )
    for snapshot in snapshots[1:]:
        current_signature = (
            snapshot.city_count,
            snapshot.building_count,
            snapshot.tech_count,
            snapshot.road_count,
        )
        if current_signature == previous_signature:
            current += 1
            best = max(best, current)
        else:
            current = 0
        previous_signature = current_signature
    return best


def _first_turn_matching(items: list[Any], predicate: Any) -> int | None:
    for item in items:
        if predicate(item):
            return int(item.turn)
    return None


def _count_turns_matching(items: list[Any], predicate: Any) -> int:
    count = 0
    for item in items:
        if predicate(item):
            count += 1
    return count


def _longest_streak(items: list[Any], predicate: Any) -> int:
    best = 0
    current = 0
    for item in items:
        if predicate(item):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _policy_type_from_label(label: str) -> PolicyType:
    if label == GREEDY_LABEL:
        return PolicyType.GREEDY
    if label == RANDOM_LABEL:
        return PolicyType.RANDOM
    if label == SEARCH_LABEL:
        return PolicyType.SEARCH
    return PolicyType.NONE


def _playback_mode_from_label(label: str) -> PlaybackMode:
    if label == "speed":
        return PlaybackMode.SPEED
    if label == "normal":
        return PlaybackMode.NORMAL
    return PlaybackMode.NONE


def _has_pyarrow() -> bool:
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("wb") as f:
        for row in rows:
            f.write(dumps_json_bytes(row))
            f.write(b"\n")


def dumps_json_bytes(payload: object, *, indent: bool = False) -> bytes:
    """Serialize JSON using orjson when available."""
    try:
        import orjson
    except ModuleNotFoundError:
        text = json.dumps(payload, ensure_ascii=True, indent=2 if indent else None)
        return text.encode("utf-8")
    option = orjson.OPT_INDENT_2 if indent else 0
    return orjson.dumps(payload, option=option)


def loads_json_bytes(payload: bytes) -> object:
    """Deserialize JSON using orjson when available."""
    try:
        import orjson
    except ModuleNotFoundError:
        return json.loads(payload.decode("utf-8"))
    return orjson.loads(payload)
