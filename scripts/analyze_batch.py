"""Analyze a MicroCiv batch dataset and emit a descriptive Markdown report."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

try:
    import pandas as pd
except ModuleNotFoundError as exc:  # pragma: no cover - depends on local optional deps
    pd = None  # type: ignore[assignment]
    PANDAS_IMPORT_ERROR = exc
else:
    PANDAS_IMPORT_ERROR = None

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from microciv.constants import APP_NAME  # noqa: E402
from microciv.game.enums import (  # noqa: E402
    MapDifficulty,
    Mode,
    OccupantType,
    PlaybackMode,
    PolicyType,
    TechType,
    TerrainType,
)
from microciv.game.models import (  # noqa: E402
    BuildingCounts,
    City,
    GameConfig,
    GameState,
    Network,
    ResourcePool,
    Road,
    Tile,
)
from microciv.game.scoring import score_breakdown  # noqa: E402
from microciv.records.models import RecordDatabase, RecordEntry  # noqa: E402

TAIL_WINDOW: Final[int] = 20
GREEDY_LABEL: Final[str] = "Greedy"
RANDOM_LABEL: Final[str] = "Random"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze MicroCiv dataset.")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "exports" / "dataset" / "dataset.json",
        help="Path to dataset JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "report.md",
        help="Path to output Markdown report.",
    )
    return parser.parse_args()


def make_table(df: pd.DataFrame, floatfmt: str = ".1f") -> str:
    if df.empty:
        return "_No data_"
    return df.to_markdown(index=False, floatfmt=floatfmt)


def _p25(series: pd.Series) -> float:
    return float(series.quantile(0.25))


def _p75(series: pd.Series) -> float:
    return float(series.quantile(0.75))


def _summary_table(
    df: pd.DataFrame,
    group_cols: list[str],
    value_cols: list[str],
) -> pd.DataFrame:
    summary = (
        df.groupby(group_cols, dropna=False)[value_cols]
        .agg(["mean", "median", _p25, _p75, "min", "max"])
        .reset_index()
    )
    summary.columns = [
        "_".join(str(part) for part in column if part).rstrip("_")
        if isinstance(column, tuple)
        else str(column)
        for column in summary.columns
    ]
    counts = df.groupby(group_cols, dropna=False).size().reset_index(name="samples")
    return counts.merge(summary, on=group_cols, how="left")


def _metric_mean(df: pd.DataFrame, column: str) -> float:
    if column not in df:
        return 0.0
    return float(df[column].fillna(0).mean())


def _record_match_key(record: RecordEntry) -> tuple[int, int, int, str]:
    return (record.seed, record.map_size, record.turn_limit, record.map_difficulty)


def _build_random_index(
    records: list[RecordEntry],
) -> dict[tuple[int, int, int, str], RecordEntry]:
    return {
        _record_match_key(record): record
        for record in records
        if record.ai_type == RANDOM_LABEL
    }


def _first_turn_matching(items: list[Any], predicate: Callable[[Any], bool]) -> int | None:
    for item in items:
        if predicate(item):
            return int(item.turn)
    return None


def _count_turns_matching(items: list[Any], predicate: Callable[[Any], bool]) -> int:
    count = 0
    for item in items:
        if predicate(item):
            count += 1
    return count


def _longest_streak(items: list[Any], predicate: Callable[[Any], bool]) -> int:
    best = 0
    current = 0
    for item in items:
        if predicate(item):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


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


def _connected_city_metrics(record: RecordEntry) -> tuple[int, int]:
    connected_cities = sum(
        len(network.city_ids) for network in record.networks if len(network.city_ids) >= 2
    )
    largest_network_size = max((len(network.city_ids) for network in record.networks), default=0)
    return connected_cities, largest_network_size


def summarize_record_anomaly(
    record: RecordEntry,
    random_peer: RecordEntry | None,
) -> dict[str, object]:
    score_drop_turns, worst_score_drop = _score_drop_metrics(record)
    connected_cities, largest_network_size = _connected_city_metrics(record)
    tail_actions = record.action_log[-TAIL_WINDOW:]
    tail_skip_ratio = (
        sum(1 for action in tail_actions if action.action_type == "skip")
        / max(len(tail_actions), 1)
    )
    greedy_contexts = [context for context in record.decision_contexts if context.greedy_stage]
    food_pressures = [
        context.greedy_food_pressure
        for context in greedy_contexts
        if context.greedy_food_pressure is not None
    ]
    is_negative_score = record.final_score < 0
    is_under_random = random_peer is not None and record.final_score < random_peer.final_score
    return {
        "record_id": record.record_id,
        "seed": record.seed,
        "map_size": record.map_size,
        "turn_limit": record.turn_limit,
        "map_difficulty": record.map_difficulty,
        "greedy_record_id": record.record_id,
        "random_record_id": random_peer.record_id if random_peer is not None else None,
        "greedy_score": record.final_score,
        "random_score": random_peer.final_score if random_peer is not None else None,
        "score_gap": (
            record.final_score - random_peer.final_score if random_peer is not None else None
        ),
        "has_random_peer": int(random_peer is not None),
        "is_negative_score": int(is_negative_score),
        "is_under_random": int(is_under_random),
        "first_negative_food_turn": _first_turn_matching(
            record.turn_snapshots,
            lambda snapshot: snapshot.food < 0,
        ),
        "negative_food_turns": _count_turns_matching(
            record.turn_snapshots,
            lambda snapshot: snapshot.food < 0,
        ),
        "first_starvation_turn": _first_turn_matching(
            record.turn_snapshots,
            lambda snapshot: snapshot.starving_network_count > 0,
        ),
        "starvation_turns": _count_turns_matching(
            record.turn_snapshots,
            lambda snapshot: snapshot.starving_network_count > 0,
        ),
        "longest_starvation_streak": _longest_streak(
            record.turn_snapshots,
            lambda snapshot: snapshot.starving_network_count > 0,
        ),
        "first_skip_turn": _first_turn_matching(
            record.action_log,
            lambda action: action.action_type == "skip",
        ),
        "skip_turns": sum(1 for action in record.action_log if action.action_type == "skip"),
        "tail_skip_ratio": tail_skip_ratio,
        "first_stage_fill_turn": _first_turn_matching(
            greedy_contexts,
            lambda context: context.greedy_stage == "fill",
        ),
        "fill_stage_turns": _count_turns_matching(
            greedy_contexts,
            lambda context: context.greedy_stage == "fill",
        ),
        "rescue_stage_turns": _count_turns_matching(
            greedy_contexts,
            lambda context: context.greedy_stage == "rescue",
        ),
        "avg_food_pressure": (
            sum(food_pressures) / len(food_pressures) if food_pressures else 0.0
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
        "record": record,
        "random_peer": random_peer,
    }


def collect_greedy_anomaly_cases(records: list[RecordEntry]) -> list[dict[str, object]]:
    random_index = _build_random_index(records)
    cases: list[dict[str, object]] = []
    for record in records:
        if record.ai_type != GREEDY_LABEL:
            continue
        random_peer = random_index.get(_record_match_key(record))
        if record.final_score >= 0 and (
            random_peer is None or record.final_score >= random_peer.final_score
        ):
            continue
        cases.append(summarize_record_anomaly(record, random_peer))
    return sorted(
        cases,
        key=lambda case: (
            case["score_gap"] is None,
            case["score_gap"] if case["score_gap"] is not None else 0,
            int(case["greedy_score"]),
            int(case["record_id"]),
        ),
    )


def build_anomaly_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows = []
    for case in collect_greedy_anomaly_cases(records):
        row = {key: value for key, value in case.items() if key not in {"record", "random_peer"}}
        rows.append(row)
    return pd.DataFrame(rows)


def build_macro_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for record in records:
        connected_cities = sum(
            len(network.city_ids) for network in record.networks if len(network.city_ids) >= 2
        )
        isolated_cities = sum(
            len(network.city_ids) for network in record.networks if len(network.city_ids) == 1
        )
        largest_network_size = max(
            (len(network.city_ids) for network in record.networks),
            default=0,
        )
        first_negative_food_turn = next(
            (snap.turn for snap in record.turn_snapshots if snap.food < 0),
            None,
        )
        rows.append(
            {
                "ai_type": record.ai_type,
                "map_size": record.map_size,
                "turn_limit": record.turn_limit,
                "map_difficulty": record.map_difficulty,
                "final_score": record.final_score,
                "city_count": record.city_count,
                "road_count": len(record.roads),
                "building_count": record.building_count,
                "tech_count": record.tech_count,
                "network_count": len(record.networks),
                "connected_cities": connected_cities,
                "isolated_cities": isolated_cities,
                "largest_network_size": largest_network_size,
                "starving_network_count": sum(
                    1 for network in record.networks if network.food <= 0
                ),
                "food": record.food,
                "wood": record.wood,
                "ore": record.ore,
                "science": record.science,
                "skip_count": record.skip_count,
                "actual_turns": record.actual_turns,
                "first_negative_food_turn": first_negative_food_turn,
                "score_per_city": record.final_score / max(record.city_count, 1),
                "score_per_building": record.final_score / max(record.building_count, 1),
                "buildings_per_city": record.building_count / max(record.city_count, 1),
                "roads_per_city": len(record.roads) / max(record.city_count, 1),
                "connected_city_ratio": connected_cities / max(record.city_count, 1),
            }
        )
    return pd.DataFrame(rows)


def build_score_breakdown_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for record in records:
        breakdown = score_breakdown(record_to_state(record))
        rows.append(
            {
                "ai_type": record.ai_type,
                "map_size": record.map_size,
                "turn_limit": record.turn_limit,
                "map_difficulty": record.map_difficulty,
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
    return pd.DataFrame(rows)


def build_turn_score_breakdown_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for record in records:
        for snapshot in record.turn_snapshots:
            if not snapshot.score_breakdown:
                continue
            row: dict[str, object] = {
                "ai_type": record.ai_type,
                "map_size": record.map_size,
                "turn_limit": record.turn_limit,
                "map_difficulty": record.map_difficulty,
                "turn": snapshot.turn,
                "score": snapshot.score,
            }
            for key, value in snapshot.score_breakdown.items():
                row[f"score_{key}"] = value
            rows.append(row)
    return pd.DataFrame(rows)


def build_decision_context_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for record in records:
        for context in record.decision_contexts:
            row: dict[str, object] = {
                "ai_type": record.ai_type,
                "map_size": record.map_size,
                "turn_limit": record.turn_limit,
                "map_difficulty": record.map_difficulty,
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
            }
            for key, value in context.greedy_score_breakdown.items():
                row[f"score_{key}"] = value
            for key, value in context.greedy_best_site_budget.items():
                row[f"site_{key}"] = value
            for key, value in context.greedy_best_future_network_budget.items():
                row[f"future_network_{key}"] = value
            rows.append(row)
    return pd.DataFrame(rows)


def build_behavior_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for record in records:
        action_counts = Counter(entry.action_type for entry in record.action_log)
        total_actions = sum(action_counts.values()) or 1
        legal_denominator = sum(ctx.legal_actions_count for ctx in record.decision_contexts) or 1
        tail_actions = record.action_log[-TAIL_WINDOW:]
        tail_counts = Counter(entry.action_type for entry in tail_actions)
        tail_total = len(tail_actions) or 1
        rows.append(
            {
                "ai_type": record.ai_type,
                "map_size": record.map_size,
                "turn_limit": record.turn_limit,
                "map_difficulty": record.map_difficulty,
                "chosen_city_pct": action_counts["build_city"] / total_actions * 100,
                "chosen_road_pct": action_counts["build_road"] / total_actions * 100,
                "chosen_building_pct": action_counts["build_building"] / total_actions * 100,
                "chosen_tech_pct": action_counts["research_tech"] / total_actions * 100,
                "chosen_skip_pct": action_counts["skip"] / total_actions * 100,
                "legal_city_pct": (
                    sum(ctx.legal_build_city_count for ctx in record.decision_contexts)
                    / legal_denominator
                    * 100
                ),
                "legal_road_pct": (
                    sum(ctx.legal_build_road_count for ctx in record.decision_contexts)
                    / legal_denominator
                    * 100
                ),
                "legal_building_pct": (
                    sum(ctx.legal_build_building_count for ctx in record.decision_contexts)
                    / legal_denominator
                    * 100
                ),
                "legal_tech_pct": (
                    sum(ctx.legal_research_tech_count for ctx in record.decision_contexts)
                    / legal_denominator
                    * 100
                ),
                "chosen_minus_legal_city_pct": (
                    action_counts["build_city"] / total_actions * 100
                    - (
                        sum(ctx.legal_build_city_count for ctx in record.decision_contexts)
                        / legal_denominator
                        * 100
                    )
                ),
                "chosen_minus_legal_road_pct": (
                    action_counts["build_road"] / total_actions * 100
                    - (
                        sum(ctx.legal_build_road_count for ctx in record.decision_contexts)
                        / legal_denominator
                        * 100
                    )
                ),
                "chosen_minus_legal_building_pct": (
                    action_counts["build_building"] / total_actions * 100
                    - (
                        sum(ctx.legal_build_building_count for ctx in record.decision_contexts)
                        / legal_denominator
                        * 100
                    )
                ),
                "chosen_minus_legal_tech_pct": (
                    action_counts["research_tech"] / total_actions * 100
                    - (
                        sum(ctx.legal_research_tech_count for ctx in record.decision_contexts)
                        / legal_denominator
                        * 100
                    )
                ),
                "tail_build_city_pct": tail_counts["build_city"] / tail_total * 100,
                "tail_build_road_pct": tail_counts["build_road"] / tail_total * 100,
                "tail_build_building_pct": tail_counts["build_building"] / tail_total * 100,
                "tail_build_tech_pct": tail_counts["research_tech"] / tail_total * 100,
                "tail_skip_pct": tail_counts["skip"] / tail_total * 100,
            }
        )
    return pd.DataFrame(rows)


def build_stage_summary_df(records: list[RecordEntry]) -> pd.DataFrame:
    decision_df = build_decision_context_df(records)
    if decision_df.empty:
        return decision_df

    greedy_df = decision_df[decision_df["greedy_stage"] != ""].copy()
    if greedy_df.empty:
        return greedy_df

    rows: list[dict[str, object]] = []
    for (ai_type, stage), group in greedy_df.groupby(["ai_type", "greedy_stage"], dropna=False):
        total = len(group)
        chosen_counts = Counter(group["chosen_action_type"])
        row: dict[str, object] = {
            "ai_type": ai_type,
            "greedy_stage": stage,
            "samples": total,
            "chosen_city_pct": chosen_counts["build_city"] / total * 100,
            "chosen_road_pct": chosen_counts["build_road"] / total * 100,
            "chosen_building_pct": chosen_counts["build_building"] / total * 100,
            "chosen_tech_pct": chosen_counts["research_tech"] / total * 100,
            "avg_best_delta_score": _metric_mean(group, "greedy_best_delta_score"),
            "avg_food_pressure": _metric_mean(group, "greedy_food_pressure"),
            "avg_network_count": _metric_mean(group, "greedy_network_count"),
            "avg_site_food_balance": _metric_mean(group, "site_food_balance"),
            "avg_site_total_yield": _metric_mean(group, "site_total_yield"),
            "avg_future_network_pressure": _metric_mean(group, "future_network_pressure"),
            "future_network_starving_rate": (
                _metric_mean(group, "greedy_best_future_network_starving") * 100
            ),
        }
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["ai_type", "greedy_stage"])


def build_map_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for record in records:
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
        buildable = (
            terrain_counts["plain"] + terrain_counts["forest"] + terrain_counts["mountain"]
        )
        rows.append(
            {
                "ai_type": record.ai_type,
                "map_size": record.map_size,
                "turn_limit": record.turn_limit,
                "map_difficulty": record.map_difficulty,
                "buildable_ratio": buildable / total,
                "plain_ratio": terrain_counts["plain"] / total,
                "wasteland_ratio": terrain_counts["wasteland"] / total,
                "river_ratio": terrain_counts["river"] / total,
                "river_cells": len(river),
                "river_turn_ratio": turns / max(turns + straights, 1),
            }
        )
    return pd.DataFrame(rows)


def _sample_rows(records: list[RecordEntry]) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for ai_type in sorted({record.ai_type for record in records}):
        subset = [record for record in records if record.ai_type == ai_type]
        if not subset:
            continue
        samples.extend(
            [
                {
                    "label": f"{ai_type} highest score",
                    "record": max(subset, key=lambda r: r.final_score),
                },
                {
                    "label": f"{ai_type} lowest score",
                    "record": min(subset, key=lambda r: r.final_score),
                },
                {
                    "label": f"{ai_type} highest skip_count",
                    "record": max(subset, key=lambda r: r.skip_count),
                },
                {
                    "label": f"{ai_type} largest network_count",
                    "record": max(subset, key=lambda r: len(r.networks)),
                },
            ]
        )
    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()
    for sample in samples:
        record = sample["record"]
        assert isinstance(record, RecordEntry)
        key = (str(sample["label"]), record.record_id)
        if key in seen:
            continue
        deduped.append(sample)
        seen.add(key)
    return deduped


def render_turn_log(record: RecordEntry, max_turns: int = 20, *, from_end: bool = False) -> str:
    if from_end:
        actions = record.action_log[-max_turns:]
        contexts = record.decision_contexts[-len(actions) :]
    else:
        actions = record.action_log[:max_turns]
        contexts = record.decision_contexts[:max_turns]
    if not actions:
        return "_No actions_"
    lines = []
    for index, action in enumerate(actions):
        context = contexts[index] if index < len(contexts) else None
        priority = context.greedy_priority if context is not None else "-"
        stage = context.greedy_stage if context is not None else "-"
        legal = context.legal_actions_count if context is not None else "-"
        delta = context.greedy_best_delta_score if context is not None else "-"
        coord = f"({action.x},{action.y})" if action.x is not None else "-"
        lines.append(
            f"  T{action.turn:>3} | {action.action_type:18} | coord={coord:8} | "
            f"legal={legal:4} | stage={stage or '-':11} | "
            f"priority={priority or '-':15} | delta={delta}"
        )
    return "\n".join(lines)


def record_to_state(record: RecordEntry) -> GameState:
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


def _policy_type_from_label(label: str) -> PolicyType:
    if label == "Greedy":
        return PolicyType.GREEDY
    if label == "Random":
        return PolicyType.RANDOM
    return PolicyType.NONE


def _playback_mode_from_label(label: str) -> PlaybackMode:
    if label == "speed":
        return PlaybackMode.SPEED
    if label == "normal":
        return PlaybackMode.NORMAL
    return PlaybackMode.NONE


def render_anomaly_case(case: dict[str, object]) -> list[str]:
    record = case["record"]
    assert isinstance(record, RecordEntry)
    random_score = case["random_score"]
    score_gap = case["score_gap"]
    lines = [
        (
            f"### Anomaly record_id={record.record_id} seed={record.seed} "
            f"config={record.map_size}/{record.turn_limit}/{record.map_difficulty}"
        ),
        (
            f"- greedy_score={record.final_score}, random_score="
            f"{random_score if random_score is not None else 'N/A'}, score_gap="
            f"{score_gap if score_gap is not None else 'N/A'}, "
            f"negative_score={bool(case['is_negative_score'])}, "
            f"under_random={bool(case['is_under_random'])}"
        ),
        (
            f"- starvation: first={case['first_starvation_turn']}, "
            f"turns={case['starvation_turns']}, "
            f"longest_streak={case['longest_starvation_streak']}, "
            f"negative_food_first={case['first_negative_food_turn']}, "
            f"negative_food_turns={case['negative_food_turns']}"
        ),
        (
            f"- skip_and_stage: first_skip={case['first_skip_turn']}, "
            f"skip_turns={case['skip_turns']}, tail_skip_ratio={case['tail_skip_ratio']:.2f}, "
            f"first_fill={case['first_stage_fill_turn']}, fill_turns={case['fill_stage_turns']}, "
            f"rescue_turns={case['rescue_stage_turns']}"
        ),
        (
            f"- network_and_score: final_starving={case['final_starving_network_count']}, "
            f"largest_network={case['final_largest_network_size']}, "
            f"connected_city_ratio={case['final_connected_city_ratio']:.2f}, "
            f"late_no_growth={case['late_game_no_growth_streak']}, "
            f"score_drop_turns={case['score_drop_turns']}, "
            f"worst_score_drop={case['worst_score_drop']}, "
            f"avg_food_pressure={case['avg_food_pressure']:.1f}"
        ),
        "- first 20 actions:",
        "```",
        render_turn_log(record),
        "```",
        "- last 20 actions:",
        "```",
        render_turn_log(record, from_end=True),
        "```",
        "",
    ]
    return lines


def generate_report(records: list[RecordEntry]) -> str:
    if pd is None:  # pragma: no cover - depends on local optional deps
        raise RuntimeError(
            "scripts/analyze_batch.py requires pandas and tabulate. "
            "Install dev dependencies first."
        ) from PANDAS_IMPORT_ERROR
    macro_df = build_macro_df(records)
    score_df = build_score_breakdown_df(records)
    turn_score_df = build_turn_score_breakdown_df(records)
    behavior_df = build_behavior_df(records)
    stage_df = build_stage_summary_df(records)
    map_df = build_map_df(records)
    anomaly_cases = collect_greedy_anomaly_cases(records)
    anomaly_df = build_anomaly_df(records)
    samples = _sample_rows(records)

    dataset_overview = pd.DataFrame(
        [
            {
                "total_games": len(records),
                "policy_count": macro_df["ai_type"].nunique(),
                "map_size_count": macro_df["map_size"].nunique(),
                "turn_limit_count": macro_df["turn_limit"].nunique(),
                "difficulty_count": macro_df["map_difficulty"].nunique(),
                "config_count": macro_df[
                    ["ai_type", "map_size", "turn_limit", "map_difficulty"]
                ]
                .drop_duplicates()
                .shape[0],
            }
        ]
    )
    config_coverage = (
        macro_df.groupby(["ai_type", "map_size", "turn_limit", "map_difficulty"], dropna=False)
        .size()
        .reset_index(name="samples")
        .sort_values(["ai_type", "map_size", "turn_limit", "map_difficulty"])
    )
    policy_summary = _summary_table(
        macro_df,
        ["ai_type"],
        [
            "final_score",
            "city_count",
            "road_count",
            "building_count",
            "buildings_per_city",
            "roads_per_city",
            "score_per_city",
            "score_per_building",
            "connected_city_ratio",
            "skip_count",
            "food",
            "science",
        ],
    )
    config_summary = _summary_table(
        macro_df,
        ["ai_type", "map_size", "turn_limit", "map_difficulty"],
        [
            "final_score",
            "city_count",
            "road_count",
            "building_count",
            "buildings_per_city",
            "roads_per_city",
            "connected_city_ratio",
            "skip_count",
            "first_negative_food_turn",
        ],
    )
    score_summary = _summary_table(
        score_df,
        ["ai_type"],
        [
            "city_score",
            "connected_city_score",
            "resource_ring_score",
            "river_access_score",
            "city_composition_bonus",
            "building_score",
            "tech_score",
            "building_utilization_score",
            "resource_score",
            "library_science_bonus",
            "building_mismatch_penalty",
            "fragmented_network_penalty",
            "isolated_city_penalty",
            "unproductive_road_penalty",
            "total_score",
        ],
    )
    turn_score_value_cols = [
        "score_total",
        "score_city_score",
        "score_connected_city_score",
        "score_resource_ring_score",
        "score_building_score",
        "score_tech_score",
        "score_resource_score",
        "score_starving_network_penalty",
        "score_fragmented_network_penalty",
        "score_isolated_city_penalty",
    ]
    turn_score_summary = (
        _summary_table(
            turn_score_df,
            ["ai_type"],
            [column for column in turn_score_value_cols if column in turn_score_df],
        )
        if (
            not turn_score_df.empty
            and any(column in turn_score_df for column in turn_score_value_cols)
        )
        else pd.DataFrame()
    )
    behavior_summary = _summary_table(
        behavior_df,
        ["ai_type"],
        [
            "chosen_city_pct",
            "chosen_road_pct",
            "chosen_building_pct",
            "chosen_tech_pct",
            "chosen_skip_pct",
            "legal_city_pct",
            "legal_road_pct",
            "legal_building_pct",
            "legal_tech_pct",
            "chosen_minus_legal_city_pct",
            "chosen_minus_legal_road_pct",
            "chosen_minus_legal_building_pct",
            "chosen_minus_legal_tech_pct",
            "tail_build_city_pct",
            "tail_build_road_pct",
            "tail_build_building_pct",
            "tail_build_tech_pct",
            "tail_skip_pct",
        ],
    )
    stage_summary = stage_df if not stage_df.empty else pd.DataFrame()
    network_summary = _summary_table(
        macro_df,
        ["ai_type"],
        [
            "network_count",
            "connected_cities",
            "isolated_cities",
            "largest_network_size",
            "starving_network_count",
            "first_negative_food_turn",
        ],
    )
    map_summary = _summary_table(
        map_df,
        ["map_difficulty"],
        [
            "buildable_ratio",
            "plain_ratio",
            "wasteland_ratio",
            "river_ratio",
            "river_cells",
            "river_turn_ratio",
        ],
    )
    greedy_total = sum(1 for record in records if record.ai_type == GREEDY_LABEL)
    anomaly_overview = pd.DataFrame(
        [
            {
                "greedy_games": greedy_total,
                "anomaly_count": len(anomaly_cases),
                "anomaly_rate": len(anomaly_cases) / max(greedy_total, 1),
                "negative_score_count": (
                    int(anomaly_df["is_negative_score"].sum()) if not anomaly_df.empty else 0
                ),
                "under_random_count": (
                    int(anomaly_df["is_under_random"].sum()) if not anomaly_df.empty else 0
                ),
                "avg_score_gap": (
                    float(anomaly_df["score_gap"].dropna().mean())
                    if not anomaly_df.empty and anomaly_df["score_gap"].notna().any()
                    else 0.0
                ),
                "worst_score_gap": (
                    float(anomaly_df["score_gap"].dropna().min())
                    if not anomaly_df.empty and anomaly_df["score_gap"].notna().any()
                    else 0.0
                ),
            }
        ]
    )
    anomaly_config_summary = pd.DataFrame()
    if greedy_total > 0:
        greedy_config_counts = (
            macro_df[macro_df["ai_type"] == GREEDY_LABEL]
            .groupby(["map_size", "turn_limit", "map_difficulty"], dropna=False)
            .size()
            .reset_index(name="greedy_samples")
        )
        anomaly_config_summary = greedy_config_counts.copy()
        anomaly_config_summary["anomaly_count"] = 0
        anomaly_config_summary["negative_score_count"] = 0
        anomaly_config_summary["under_random_count"] = 0
        anomaly_config_summary["avg_score_gap"] = 0.0
        anomaly_config_summary["avg_first_skip_turn"] = 0.0
        anomaly_config_summary["avg_starvation_turns"] = 0.0
        anomaly_config_summary["avg_longest_starvation_streak"] = 0.0
        anomaly_config_summary["anomaly_rate"] = 0.0
        if not anomaly_df.empty:
            anomaly_config_counts = (
                anomaly_df.groupby(["map_size", "turn_limit", "map_difficulty"], dropna=False)
                .agg(
                    anomaly_count=("record_id", "size"),
                    negative_score_count=("is_negative_score", "sum"),
                    under_random_count=("is_under_random", "sum"),
                    avg_score_gap=("score_gap", "mean"),
                    avg_first_skip_turn=("first_skip_turn", "mean"),
                    avg_starvation_turns=("starvation_turns", "mean"),
                    avg_longest_starvation_streak=("longest_starvation_streak", "mean"),
                )
                .reset_index()
            )
            anomaly_config_summary = greedy_config_counts.merge(
                anomaly_config_counts,
                on=["map_size", "turn_limit", "map_difficulty"],
                how="left",
            )
            fill_zero_cols = [
                "anomaly_count",
                "negative_score_count",
                "under_random_count",
                "avg_score_gap",
                "avg_first_skip_turn",
                "avg_starvation_turns",
                "avg_longest_starvation_streak",
            ]
            anomaly_config_summary[fill_zero_cols] = anomaly_config_summary[
                fill_zero_cols
            ].fillna(0)
            anomaly_config_summary["anomaly_rate"] = (
                anomaly_config_summary["anomaly_count"]
                / anomaly_config_summary["greedy_samples"].clip(lower=1)
            )
            anomaly_config_summary = anomaly_config_summary.sort_values(
                ["anomaly_rate", "avg_score_gap", "map_size", "turn_limit", "map_difficulty"],
                ascending=[False, True, True, True, True],
            )

    lines = [
        f"# {APP_NAME} Dataset Report",
        "",
        "## 1. Dataset Overview",
        "",
        make_table(dataset_overview, floatfmt=".0f"),
        "",
        "### 1.1 Config Coverage",
        "",
        make_table(config_coverage, floatfmt=".0f"),
        "",
        "## 2. Policy Summary",
        "",
        make_table(policy_summary),
        "",
        "## 3. Config Summary",
        "",
        make_table(config_summary),
        "",
        "## 4. Score Component Summary",
        "",
        make_table(score_summary),
        "",
        "## 5. Turn Score Composition Summary",
        "",
        make_table(turn_score_summary),
        "",
        "## 6. Behavior Summary",
        "",
        make_table(behavior_summary),
        "",
        "## 7. Greedy Stage Summary",
        "",
        make_table(stage_summary),
        "",
        "## 8. Network And Risk Summary",
        "",
        make_table(network_summary),
        "",
        "## 9. Map Summary",
        "",
        make_table(map_summary, floatfmt=".3f"),
        "",
        "## 10. Anomaly Summary",
        "",
        make_table(anomaly_overview, floatfmt=".3f"),
        "",
        "### 10.1 Anomaly Config Summary",
        "",
        make_table(anomaly_config_summary),
        "",
        "## 11. Anomaly Cases",
        "",
    ]

    if not anomaly_cases:
        lines.extend(["_No data_", ""])
    else:
        for case in anomaly_cases:
            lines.extend(render_anomaly_case(case))

    lines.extend(
        [
            "## 12. Representative Samples",
            "",
        ]
    )

    for sample in samples:
        record = sample["record"]
        assert isinstance(record, RecordEntry)
        lines.extend(
            [
                f"### {sample['label']}",
                (
                    f"- record_id={record.record_id}, score={record.final_score}, "
                    f"cities={record.city_count}, roads={len(record.roads)}, "
                    f"buildings={record.building_count}, techs={record.tech_count}, "
                    f"skip={record.skip_count}, config={record.map_size}/{record.turn_limit}/"
                    f"{record.map_difficulty}"
                ),
                "- first 20 actions:",
                "```",
                render_turn_log(record),
                "```",
                "",
            ]
        )

    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    if pd is None:  # pragma: no cover - depends on local optional deps
        print(
            "Missing optional dependency: pandas. "
            "Install dev dependencies or `pip install pandas tabulate`.",
            file=sys.stderr,
        )
        return 1
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    database = RecordDatabase.from_dict(raw)
    report = generate_report(database.records)
    args.output.write_text(report, encoding="utf-8")
    print(f"Report written to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
