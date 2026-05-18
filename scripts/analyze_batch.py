"""Analyze a MicroCiv batch dataset and emit a descriptive Markdown report."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable
from math import ceil
from numbers import Real
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
from microciv.game.enums import PlaybackMode, PolicyType  # noqa: E402
from microciv.game.models import GameState  # noqa: E402
from microciv.records.artifacts import (  # noqa: E402
    is_artifact_dir,
    loads_json_bytes,
    read_artifact_frames,
    record_action_rows,
    record_behavior_row,
    record_decision_rows,
    record_macro_row,
    record_map_row,
    record_score_breakdown_row,
    record_turn_score_rows,
)
from microciv.records.artifacts import (  # noqa: E402
    policy_variant_label as artifact_policy_variant_label,
)
from microciv.records.artifacts import (  # noqa: E402
    record_to_state as artifact_record_to_state,
)
from microciv.records.models import RecordDatabase, RecordEntry  # noqa: E402

TAIL_WINDOW: Final[int] = 20
GREEDY_LABEL: Final[str] = "Greedy"
RANDOM_LABEL: Final[str] = "Random"
SEARCH_LABEL: Final[str] = "Search"
MATCH_KEY_COLS: Final[tuple[str, ...]] = ("seed", "map_size", "turn_limit", "map_difficulty")
LAG_GAP_THRESHOLDS: Final[tuple[int, ...]] = (100, 250, 500)
LAG_PCT_POINTS: Final[tuple[float, ...]] = (0.10, 0.25, 0.50, 0.75)
EVENT_TURN_COLUMNS: Final[tuple[str, ...]] = (
    "first_turn_under_greedy",
    "first_turn_gap_le_250",
    "first_persistent_under_greedy_turn",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze MicroCiv dataset.")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "exports" / "dataset" / "dataset.json",
        help="Path to dataset JSON or artifact directory.",
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
        _record_match_key(record): record for record in records if record.ai_type == RANDOM_LABEL
    }


def _build_greedy_index(
    records: list[RecordEntry],
) -> dict[tuple[int, int, int, str], RecordEntry]:
    return {
        _record_match_key(record): record for record in records if record.ai_type == GREEDY_LABEL
    }


def policy_variant_label(record: RecordEntry) -> str:
    return artifact_policy_variant_label(record)


def _has_starvation(record: RecordEntry) -> bool:
    return any(snapshot.starving_network_count > 0 for snapshot in record.turn_snapshots) or any(
        network.food <= 0 for network in record.networks
    )


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
    tail_skip_ratio = sum(1 for action in tail_actions if action.action_type == "skip") / max(
        len(tail_actions), 1
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
        "avg_food_pressure": (sum(food_pressures) / len(food_pressures) if food_pressures else 0.0),
        "max_starving_networks_seen": max(
            (snapshot.starving_network_count for snapshot in record.turn_snapshots),
            default=0,
        ),
        "final_starving_network_count": sum(1 for network in record.networks if network.food <= 0),
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
    return pd.DataFrame(record_macro_row(record) for record in records)


def build_score_breakdown_df(records: list[RecordEntry]) -> pd.DataFrame:
    return pd.DataFrame(record_score_breakdown_row(record) for record in records)


def build_turn_score_breakdown_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for record in records:
        rows.extend(record_turn_score_rows(record))
    return pd.DataFrame(rows)


def build_decision_context_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for record in records:
        rows.extend(record_decision_rows(record))
    return pd.DataFrame(rows)


def build_action_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for record in records:
        rows.extend(record_action_rows(record))
    return pd.DataFrame(rows)


def build_behavior_df(records: list[RecordEntry]) -> pd.DataFrame:
    return pd.DataFrame(record_behavior_row(record) for record in records)


def build_stage_summary_df(records: list[RecordEntry]) -> pd.DataFrame:
    decision_df = build_decision_context_df(records)
    return build_stage_summary_from_decision_df(decision_df)


def build_stage_summary_from_decision_df(decision_df: pd.DataFrame) -> pd.DataFrame:
    if decision_df.empty:
        return decision_df

    greedy_df = decision_df[decision_df["greedy_stage"] != ""].copy()
    if greedy_df.empty:
        return greedy_df

    rows: list[dict[str, object]] = []
    for (policy_variant, stage), group in greedy_df.groupby(
        ["policy_variant", "greedy_stage"],
        dropna=False,
    ):
        total = len(group)
        chosen_counts = Counter(group["chosen_action_type"])
        row: dict[str, object] = {
            "policy_variant": policy_variant,
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
    return pd.DataFrame(rows).sort_values(["policy_variant", "greedy_stage"])


def build_search_summary_df(records: list[RecordEntry]) -> pd.DataFrame:
    decision_df = build_decision_context_df(records)
    return build_search_summary_from_decision_df(decision_df)


def build_search_summary_from_decision_df(decision_df: pd.DataFrame) -> pd.DataFrame:
    if decision_df.empty or "search_depth" not in decision_df:
        return pd.DataFrame()

    search_df = decision_df[decision_df["search_depth"].notna()].copy()
    if search_df.empty:
        return pd.DataFrame()

    value_cols = [
        "search_depth",
        "search_actual_depth",
        "search_max_depth",
        "search_beam_width",
        "search_candidate_limit",
        "search_root_candidate_build_city_count",
        "search_root_candidate_build_road_count",
        "search_root_candidate_build_building_count",
        "search_root_candidate_research_tech_count",
        "search_root_candidate_skip_count",
        "search_root_effective_city_candidate_count",
        "search_root_redundant_road_candidate_count",
        "search_root_high_roi_building_candidate_count",
        "search_root_gated_candidate_count",
        "search_nodes_expanded",
        "search_candidates_considered",
        "search_leaf_count",
        "search_best_value",
        "search_sequence_adjustment",
        "search_dominant_pressure_value",
        "search_risk_pressure_total",
        "search_is_risk_dominated",
        "search_is_sequence_adjusted",
        "search_best_score_total",
        "search_best_starving_network_count",
        "search_best_food_pressure",
        "search_best_starving_turns",
        "search_best_network_count",
        "search_best_isolated_city_count",
        "search_sequence_length",
    ]
    value_cols.extend(
        column for column in search_df.columns if str(column).startswith("search_value_")
    )
    value_cols = [column for column in value_cols if column in search_df]
    return _summary_table(search_df, ["policy_variant"], value_cols)


def build_search_mode_summary_from_decision_df(decision_df: pd.DataFrame) -> pd.DataFrame:
    if decision_df.empty or "search_mode" not in decision_df:
        return pd.DataFrame()
    search_df = decision_df[
        decision_df.get("search_mode", pd.Series(dtype=object)).fillna("") != ""
    ].copy()
    if search_df.empty:
        return pd.DataFrame()

    numeric_cols = [
        "search_depth",
        "search_root_candidate_build_city_count",
        "search_root_candidate_build_road_count",
        "search_root_candidate_build_building_count",
        "search_root_candidate_research_tech_count",
        "search_root_candidate_skip_count",
        "search_sequence_adjustment",
        "search_best_value",
        "search_risk_pressure_total",
        "search_is_risk_dominated",
        "search_is_sequence_adjusted",
    ]
    for column in numeric_cols:
        if column not in search_df:
            search_df[column] = 0

    rows: list[dict[str, object]] = []
    for (policy_variant, search_mode), group in search_df.groupby(
        ["policy_variant", "search_mode"],
        dropna=False,
    ):
        total = len(group)
        chosen_counts = Counter(group["chosen_action_type"])
        rows.append(
            {
                "policy_variant": policy_variant,
                "search_mode": search_mode,
                "samples": total,
                "chosen_city_pct": chosen_counts["build_city"] / total * 100,
                "chosen_road_pct": chosen_counts["build_road"] / total * 100,
                "chosen_building_pct": chosen_counts["build_building"] / total * 100,
                "chosen_tech_pct": chosen_counts["research_tech"] / total * 100,
                "chosen_skip_pct": chosen_counts["skip"] / total * 100,
                "search_depth_mean": _metric_mean(group, "search_depth"),
                "candidate_city_mean": _metric_mean(
                    group, "search_root_candidate_build_city_count"
                ),
                "candidate_road_mean": _metric_mean(
                    group, "search_root_candidate_build_road_count"
                ),
                "candidate_building_mean": _metric_mean(
                    group, "search_root_candidate_build_building_count"
                ),
                "candidate_tech_mean": _metric_mean(
                    group, "search_root_candidate_research_tech_count"
                ),
                "candidate_skip_mean": _metric_mean(group, "search_root_candidate_skip_count"),
                "sequence_adjustment_mean": _metric_mean(group, "search_sequence_adjustment"),
                "risk_pressure_mean": _metric_mean(group, "search_risk_pressure_total"),
                "risk_dominated_pct": _metric_mean(group, "search_is_risk_dominated") * 100,
                "sequence_adjusted_pct": (_metric_mean(group, "search_is_sequence_adjusted") * 100),
                "best_value_mean": _metric_mean(group, "search_best_value"),
            }
        )
    return pd.DataFrame(rows).sort_values(["policy_variant", "search_mode"])


def build_search_pressure_summary_from_decision_df(decision_df: pd.DataFrame) -> pd.DataFrame:
    if decision_df.empty or "search_dominant_pressure" not in decision_df:
        return pd.DataFrame()
    search_df = decision_df[
        decision_df.get("search_dominant_pressure", pd.Series(dtype=object)).fillna("") != ""
    ].copy()
    if search_df.empty:
        return pd.DataFrame()

    numeric_cols = [
        "search_dominant_pressure_value",
        "search_risk_pressure_total",
        "search_is_risk_dominated",
        "search_is_sequence_adjusted",
        "search_sequence_adjustment",
        "search_best_value",
    ]
    for column in numeric_cols:
        if column not in search_df:
            search_df[column] = 0

    rows: list[dict[str, object]] = []
    for (policy_variant, dominant_pressure), group in search_df.groupby(
        ["policy_variant", "search_dominant_pressure"],
        dropna=False,
    ):
        total = len(group)
        chosen_counts = Counter(group["chosen_action_type"])
        rows.append(
            {
                "policy_variant": policy_variant,
                "search_dominant_pressure": dominant_pressure,
                "samples": total,
                "chosen_city_pct": chosen_counts["build_city"] / total * 100,
                "chosen_road_pct": chosen_counts["build_road"] / total * 100,
                "chosen_building_pct": chosen_counts["build_building"] / total * 100,
                "chosen_tech_pct": chosen_counts["research_tech"] / total * 100,
                "chosen_skip_pct": chosen_counts["skip"] / total * 100,
                "dominant_pressure_value_mean": _metric_mean(
                    group, "search_dominant_pressure_value"
                ),
                "risk_pressure_total_mean": _metric_mean(group, "search_risk_pressure_total"),
                "risk_dominated_pct": _metric_mean(group, "search_is_risk_dominated") * 100,
                "sequence_adjusted_pct": (_metric_mean(group, "search_is_sequence_adjusted") * 100),
                "sequence_adjustment_mean": _metric_mean(group, "search_sequence_adjustment"),
                "best_value_mean": _metric_mean(group, "search_best_value"),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["policy_variant", "samples", "search_dominant_pressure"],
        ascending=[True, False, True],
    )


def build_search_candidate_health_summary_from_decision_df(
    decision_df: pd.DataFrame,
) -> pd.DataFrame:
    if decision_df.empty or "search_depth" not in decision_df:
        return pd.DataFrame()
    search_df = decision_df[decision_df["search_depth"].notna()].copy()
    if search_df.empty:
        return pd.DataFrame()
    value_cols = [
        "search_root_candidate_cut_ratio",
        "search_root_chosen_rank",
        "search_root_chosen_value",
        "search_root_best_value",
        "search_root_value_margin",
        "search_root_safe_city_candidate_count",
        "search_root_effective_connection_road_candidate_count",
        "search_root_rescue_candidate_count",
        "search_root_effective_city_candidate_count",
        "search_root_redundant_road_candidate_count",
        "search_root_high_roi_building_candidate_count",
        "search_root_gated_candidate_count",
        "search_delta_starving_network_count",
        "search_delta_food_pressure",
        "search_delta_isolated_city_count",
        "search_delta_network_count",
        "search_delta_connected_city_count",
        "search_delta_road_overbuild",
        "search_delta_worst_network_food_pressure",
        "search_delta_min_network_food",
    ]
    return _summary_table(
        search_df,
        ["policy_variant"],
        [column for column in value_cols if column in search_df],
    )


def build_search_road_quality_summary_from_decision_df(decision_df: pd.DataFrame) -> pd.DataFrame:
    if decision_df.empty or "search_road_connected_city_delta" not in decision_df:
        return pd.DataFrame()
    road_df = decision_df[
        decision_df.get("chosen_action_type", pd.Series(dtype=object)).fillna("") == "build_road"
    ].copy()
    if road_df.empty:
        return pd.DataFrame()
    for column in [
        "search_road_merges_networks",
        "search_road_is_redundant",
        "search_road_after_full_connectivity",
        "search_road_connected_city_delta",
        "search_delta_network_count",
    ]:
        if column not in road_df:
            road_df[column] = 0
    grouped = (
        road_df.groupby(["policy_variant"], dropna=False)
        .agg(
            road_actions=("chosen_action_type", "size"),
            merge_rate=("search_road_merges_networks", "mean"),
            redundant_rate=("search_road_is_redundant", "mean"),
            after_full_connectivity_rate=("search_road_after_full_connectivity", "mean"),
            connected_city_delta_mean=("search_road_connected_city_delta", "mean"),
            network_delta_mean=("search_delta_network_count", "mean"),
        )
        .reset_index()
    )
    for column in ["merge_rate", "redundant_rate", "after_full_connectivity_rate"]:
        grouped[column] = grouped[column] * 100
    return grouped.sort_values(["policy_variant"])


def build_search_record_profile_summary_from_decision_df(decision_df: pd.DataFrame) -> pd.DataFrame:
    if decision_df.empty or "search_depth" not in decision_df:
        return pd.DataFrame()
    search_df = decision_df[decision_df["search_depth"].notna()].copy()
    if search_df.empty or "record_id" not in search_df:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for (policy_variant, record_id), group in search_df.groupby(
        ["policy_variant", "record_id"],
        dropna=False,
    ):
        total = len(group) or 1
        mode_counts = Counter(group.get("search_mode", pd.Series(dtype=object)).fillna(""))
        reason_counts = Counter(
            group.get("search_depth_reason", pd.Series(dtype=object)).fillna("")
        )
        pressure_counts = Counter(
            group.get("search_dominant_pressure", pd.Series(dtype=object)).fillna("")
        )
        rows.append(
            {
                "policy_variant": policy_variant,
                "record_id": record_id,
                "turns": total,
                "rescue_pct": mode_counts["rescue"] / total * 100,
                "connect_pct": mode_counts["connect"] / total * 100,
                "expand_pct": mode_counts["expand"] / total * 100,
                "fill_pct": mode_counts["fill"] / total * 100,
                "food_rescue_depth_pct": reason_counts["food_rescue"] / total * 100,
                "network_connect_depth_pct": reason_counts["network_connect"] / total * 100,
                "risk_dominated_pct": _metric_mean(group, "search_is_risk_dominated") * 100,
                "sequence_adjusted_pct": (_metric_mean(group, "search_is_sequence_adjusted") * 100),
                "road_overbuild_pressure_pct": (
                    pressure_counts["road_overbuild_penalty"] / total * 100
                ),
                "starving_pressure_pct": (
                    pressure_counts["starving_turn_penalty"] + pressure_counts["starving_penalty"]
                )
                / total
                * 100,
            }
        )
    record_df = pd.DataFrame(rows)
    if record_df.empty:
        return record_df
    value_cols = [
        "rescue_pct",
        "connect_pct",
        "expand_pct",
        "fill_pct",
        "food_rescue_depth_pct",
        "network_connect_depth_pct",
        "risk_dominated_pct",
        "sequence_adjusted_pct",
        "road_overbuild_pressure_pct",
        "starving_pressure_pct",
    ]
    return _summary_table(record_df, ["policy_variant"], value_cols)


def build_search_depth_reason_summary_from_decision_df(decision_df: pd.DataFrame) -> pd.DataFrame:
    if decision_df.empty or "search_depth_reason" not in decision_df:
        return pd.DataFrame()
    search_df = decision_df[
        decision_df.get("search_depth_reason", pd.Series(dtype=object)).fillna("") != ""
    ].copy()
    if search_df.empty:
        return pd.DataFrame()
    for column in ["search_depth", "search_leaf_count", "search_best_food_pressure"]:
        if column not in search_df:
            search_df[column] = 0
    grouped = (
        search_df.groupby(["policy_variant", "search_depth_reason"], dropna=False)
        .agg(
            samples=("search_depth_reason", "size"),
            search_depth_mean=("search_depth", "mean"),
            search_depth_max=("search_depth", "max"),
            search_leaf_count_mean=("search_leaf_count", "mean"),
            search_best_food_pressure_mean=("search_best_food_pressure", "mean"),
        )
        .reset_index()
    )
    return grouped.sort_values(["policy_variant", "search_depth_reason"])


def build_search_planning_summary_from_decision_df(decision_df: pd.DataFrame) -> pd.DataFrame:
    if decision_df.empty or "search_planning_mode" not in decision_df:
        return pd.DataFrame()
    search_df = decision_df[
        decision_df.get("search_planning_mode", pd.Series(dtype=object)).fillna("") != ""
    ].copy()
    if search_df.empty:
        return pd.DataFrame()
    for column in [
        "search_depth",
        "search_actual_depth",
        "search_deep_search_enabled",
        "search_nodes_expanded",
        "search_leaf_count",
        "search_best_value",
    ]:
        if column not in search_df:
            search_df[column] = 0
    grouped = (
        search_df.groupby(
            ["policy_variant", "search_planning_mode", "search_planning_reason"],
            dropna=False,
        )
        .agg(
            samples=("search_planning_mode", "size"),
            configured_depth_mean=("search_depth", "mean"),
            actual_depth_mean=("search_actual_depth", "mean"),
            deep_search_rate=("search_deep_search_enabled", "mean"),
            nodes_expanded_mean=("search_nodes_expanded", "mean"),
            leaf_count_mean=("search_leaf_count", "mean"),
            best_value_mean=("search_best_value", "mean"),
        )
        .reset_index()
    )
    grouped["deep_search_rate"] = grouped["deep_search_rate"] * 100
    return grouped.sort_values(
        ["policy_variant", "samples", "search_planning_mode", "search_planning_reason"],
        ascending=[True, False, True, True],
    )


def build_search_matchup_summary_from_macro_df(macro_df: pd.DataFrame) -> pd.DataFrame:
    if macro_df.empty or "ai_type" not in macro_df or "final_score" not in macro_df:
        return pd.DataFrame()
    key_cols = ["seed", "map_size", "turn_limit", "map_difficulty"]
    if any(column not in macro_df for column in key_cols):
        return pd.DataFrame()

    baseline_cols = [*key_cols, "final_score"]
    greedy_df = (
        macro_df[macro_df["ai_type"] == GREEDY_LABEL][baseline_cols]
        .rename(columns={"final_score": "greedy_score"})
        .copy()
    )
    random_df = (
        macro_df[macro_df["ai_type"] == RANDOM_LABEL][baseline_cols]
        .rename(columns={"final_score": "random_score"})
        .copy()
    )
    search_df = macro_df[macro_df["ai_type"] == SEARCH_LABEL].copy()
    if search_df.empty:
        return pd.DataFrame()

    merged = search_df.merge(greedy_df, on=key_cols, how="left").merge(
        random_df,
        on=key_cols,
        how="left",
    )
    merged["score_gap_vs_greedy"] = merged["final_score"] - merged["greedy_score"]
    merged["score_gap_vs_random"] = merged["final_score"] - merged["random_score"]
    merged["meets_same_map_bar"] = (
        (merged["score_gap_vs_greedy"] >= 0) & (merged["score_gap_vs_random"] >= 0)
    ).astype(int)
    summary = (
        merged.groupby(["policy_variant"], dropna=False)
        .agg(
            samples=("final_score", "size"),
            same_map_win_rate=("meets_same_map_bar", "mean"),
            same_map_wins=("meets_same_map_bar", "sum"),
            avg_score_gap_vs_greedy=("score_gap_vs_greedy", "mean"),
            median_score_gap_vs_greedy=("score_gap_vs_greedy", "median"),
            avg_score_gap_vs_random=("score_gap_vs_random", "mean"),
            median_score_gap_vs_random=("score_gap_vs_random", "median"),
            decision_time_ms_total=("decision_time_ms_total", "sum"),
        )
        .reset_index()
    )
    summary["same_map_win_rate"] = summary["same_map_win_rate"] * 100
    summary["wins_per_cpu_hour"] = summary["same_map_wins"] / (
        summary["decision_time_ms_total"].clip(lower=0.000001) / 3_600_000
    )
    summary["task7_acceptance_candidate"] = (
        (summary["same_map_win_rate"] >= 95)
        & (summary["avg_score_gap_vs_greedy"] >= 0)
        & (summary["median_score_gap_vs_greedy"] >= 0)
        & (summary["avg_score_gap_vs_random"] >= 0)
        & (summary["median_score_gap_vs_random"] >= 0)
    ).astype(int)
    return summary.sort_values(["task7_acceptance_candidate", "same_map_win_rate"], ascending=False)


def build_search_score_component_gap_summary_from_score_df(
    score_df: pd.DataFrame,
) -> pd.DataFrame:
    if score_df.empty or "ai_type" not in score_df:
        return pd.DataFrame()
    key_cols = ["seed", "map_size", "turn_limit", "map_difficulty"]
    if any(column not in score_df for column in key_cols):
        return pd.DataFrame()
    component_cols = [
        "total_score",
        "city_score",
        "connected_city_score",
        "resource_ring_score",
        "building_score",
        "tech_score",
        "building_utilization_score",
        "resource_score",
        "food_score",
        "wood_score",
        "ore_score",
        "science_score",
        "starving_network_penalty",
        "fragmented_network_penalty",
        "isolated_city_penalty",
        "unproductive_road_penalty",
    ]
    component_cols = [column for column in component_cols if column in score_df]
    if not component_cols:
        return pd.DataFrame()

    greedy_df = score_df[score_df["ai_type"] == GREEDY_LABEL][[*key_cols, *component_cols]].copy()
    search_df = score_df[score_df["ai_type"] == SEARCH_LABEL].copy()
    if greedy_df.empty or search_df.empty:
        return pd.DataFrame()
    greedy_df = greedy_df.rename(columns={column: f"greedy_{column}" for column in component_cols})
    merged = search_df.merge(greedy_df, on=key_cols, how="left")
    rows: list[dict[str, object]] = []
    for policy_variant, group in merged.groupby(["policy_variant"], dropna=False):
        row: dict[str, object] = {
            "policy_variant": policy_variant,
            "samples": len(group),
        }
        for column in component_cols:
            greedy_column = f"greedy_{column}"
            if greedy_column not in group:
                continue
            row[f"{column}_gap_mean"] = (
                group[column].fillna(0) - group[greedy_column].fillna(0)
            ).mean()
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["policy_variant"])


def build_search_turn_gap_df(
    macro_df: pd.DataFrame,
    turn_score_df: pd.DataFrame,
) -> pd.DataFrame:
    if turn_score_df.empty or "ai_type" not in turn_score_df or "score" not in turn_score_df:
        return pd.DataFrame()
    if any(column not in turn_score_df for column in (*MATCH_KEY_COLS, "turn")):
        return pd.DataFrame()

    component_cols = [
        column for column in turn_score_df.columns if str(column).startswith("score_")
    ]
    snapshot_cols = [
        "food",
        "wood",
        "ore",
        "science",
        "city_count",
        "building_count",
        "tech_count",
        "road_count",
        "network_count",
        "connected_city_count",
        "isolated_city_count",
        "largest_network_size",
        "starving_network_count",
        "legal_actions_count",
    ]
    snapshot_cols = [column for column in snapshot_cols if column in turn_score_df]
    compare_cols = ["score", *component_cols, *snapshot_cols]

    greedy_cols = [*MATCH_KEY_COLS, "turn", *compare_cols]
    greedy_df = turn_score_df[turn_score_df["ai_type"] == GREEDY_LABEL][greedy_cols].copy()
    search_df = turn_score_df[turn_score_df["ai_type"] == SEARCH_LABEL].copy()
    if greedy_df.empty or search_df.empty:
        return pd.DataFrame()

    greedy_df = greedy_df.rename(columns={column: f"greedy_{column}" for column in compare_cols})
    merged = search_df.merge(greedy_df, on=[*MATCH_KEY_COLS, "turn"], how="left")
    if "greedy_score" not in merged:
        return pd.DataFrame()
    merged["score_gap_vs_greedy"] = merged["score"] - merged["greedy_score"]
    for column in component_cols + snapshot_cols:
        greedy_column = f"greedy_{column}"
        if greedy_column in merged:
            merged[f"{column}_gap_vs_greedy"] = merged[column] - merged[greedy_column]

    if not macro_df.empty and "final_score" in macro_df and "record_id" in macro_df:
        final_cols = ["record_id", "final_score", "decision_time_ms_total"]
        final_cols = [column for column in final_cols if column in macro_df]
        search_final = macro_df[macro_df["ai_type"] == SEARCH_LABEL][final_cols].rename(
            columns={"final_score": "search_final_score"}
        )
        greedy_final = macro_df[macro_df["ai_type"] == GREEDY_LABEL][
            [*MATCH_KEY_COLS, "final_score"]
        ].rename(columns={"final_score": "greedy_final_score"})
        merged = merged.merge(search_final, on="record_id", how="left").merge(
            greedy_final,
            on=list(MATCH_KEY_COLS),
            how="left",
        )
        if "search_final_score" in merged and "greedy_final_score" in merged:
            merged["final_gap_vs_greedy"] = (
                merged["search_final_score"] - merged["greedy_final_score"]
            )
    return merged


def build_search_lag_event_df(
    turn_gap_df: pd.DataFrame,
) -> pd.DataFrame:
    if turn_gap_df.empty or "score_gap_vs_greedy" not in turn_gap_df:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for (policy_variant, record_id), group in turn_gap_df.groupby(
        ["policy_variant", "record_id"],
        dropna=False,
    ):
        ordered = group.sort_values("turn")
        turns = [int(_number(value, 0)) for value in ordered["turn"].tolist()]
        gaps = [float(_number(value, 0)) for value in ordered["score_gap_vs_greedy"].tolist()]
        if not turns:
            continue
        turn_limit = int(_number(ordered["turn_limit"].iloc[0], turns[-1]))
        final_gap = (
            float(_number(ordered["final_gap_vs_greedy"].iloc[0], gaps[-1]))
            if "final_gap_vs_greedy" in ordered
            else gaps[-1]
        )
        recovery_count, max_recovery_gap = _recovery_metrics(gaps)
        row: dict[str, object] = {
            "policy_variant": policy_variant,
            "record_id": record_id,
            "seed": int(_number(ordered["seed"].iloc[0], 0)),
            "map_size": int(_number(ordered["map_size"].iloc[0], 0)),
            "turn_limit": turn_limit,
            "map_difficulty": ordered["map_difficulty"].iloc[0],
            "final_gap_vs_greedy": final_gap,
            "is_final_under_greedy": int(final_gap < 0),
            "first_turn_under_greedy": _first_gap_turn(turns, gaps, lambda gap: gap < 0),
            "first_persistent_under_greedy_turn": _first_persistent_gap_turn(
                turns,
                gaps,
                lambda gap: gap < 0,
            ),
            "recovery_count": recovery_count,
            "max_recovery_gap": max_recovery_gap,
        }
        for threshold in LAG_GAP_THRESHOLDS:
            row[f"first_turn_gap_le_{threshold}"] = _first_gap_turn(
                turns,
                gaps,
                lambda gap, threshold=threshold: gap <= -threshold,
            )
        for threshold in (250, 500):
            row[f"first_persistent_gap_le_{threshold}_turn"] = _first_persistent_gap_turn(
                turns,
                gaps,
                lambda gap, threshold=threshold: gap <= -threshold,
            )
        for pct in LAG_PCT_POINTS:
            label = f"{int(pct * 100)}_pct"
            row[f"gap_at_{label}"] = _gap_at_target_turn(
                turns,
                gaps,
                max(1, ceil(turn_limit * pct)),
            )
        row["final_gap"] = final_gap
        rows.append(row)
    return pd.DataFrame(rows)


def build_search_lag_summary_from_lag_df(lag_df: pd.DataFrame) -> pd.DataFrame:
    if lag_df.empty:
        return lag_df
    value_cols = [
        "is_final_under_greedy",
        "first_turn_under_greedy",
        "first_turn_gap_le_100",
        "first_turn_gap_le_250",
        "first_turn_gap_le_500",
        "first_persistent_under_greedy_turn",
        "first_persistent_gap_le_250_turn",
        "first_persistent_gap_le_500_turn",
        "gap_at_10_pct",
        "gap_at_25_pct",
        "gap_at_50_pct",
        "gap_at_75_pct",
        "final_gap",
        "recovery_count",
        "max_recovery_gap",
    ]
    return _summary_table(
        lag_df,
        ["policy_variant"],
        [column for column in value_cols if column in lag_df],
    )


def build_search_lag_config_summary_from_lag_df(lag_df: pd.DataFrame) -> pd.DataFrame:
    if lag_df.empty:
        return lag_df
    summary = (
        lag_df.groupby(["policy_variant", "map_size", "turn_limit", "map_difficulty"], dropna=False)
        .agg(
            samples=("record_id", "size"),
            under_greedy_count=("is_final_under_greedy", "sum"),
            avg_final_gap=("final_gap", "mean"),
            median_final_gap=("final_gap", "median"),
            median_first_under_turn=("first_turn_under_greedy", "median"),
            median_gap_at_25_pct=("gap_at_25_pct", "median"),
        )
        .reset_index()
    )
    summary["under_greedy_rate"] = summary["under_greedy_count"] / summary["samples"].clip(lower=1)
    return summary.sort_values(
        ["under_greedy_rate", "avg_final_gap"],
        ascending=[False, True],
    )


def build_search_lag_event_component_summary(
    lag_df: pd.DataFrame,
    turn_gap_df: pd.DataFrame,
) -> pd.DataFrame:
    if lag_df.empty or turn_gap_df.empty:
        return pd.DataFrame()
    gap_cols = [
        "score_city_score_gap_vs_greedy",
        "score_connected_city_score_gap_vs_greedy",
        "score_resource_ring_score_gap_vs_greedy",
        "score_building_score_gap_vs_greedy",
        "score_resource_score_gap_vs_greedy",
        "score_starving_network_penalty_gap_vs_greedy",
        "score_fragmented_network_penalty_gap_vs_greedy",
        "score_isolated_city_penalty_gap_vs_greedy",
    ]
    gap_cols = [column for column in gap_cols if column in turn_gap_df]
    if not gap_cols:
        return pd.DataFrame()

    indexed = {
        (int(_number(row["record_id"], 0)), int(_number(row["turn"], 0))): row
        for row in turn_gap_df.to_dict("records")
    }
    rows: list[dict[str, object]] = []
    for lag_row in lag_df.to_dict("records"):
        record_id = int(_number(lag_row.get("record_id"), 0))
        for event_col in EVENT_TURN_COLUMNS:
            turn = lag_row.get(event_col)
            if _is_missing(turn):
                continue
            gap_row = indexed.get((record_id, int(_number(turn, 0))))
            if gap_row is None:
                continue
            row: dict[str, object] = {
                "policy_variant": lag_row.get("policy_variant"),
                "event": event_col,
            }
            for column in gap_cols:
                row[column] = gap_row.get(column)
            rows.append(row)
    event_df = pd.DataFrame(rows)
    if event_df.empty:
        return event_df
    return _summary_table(event_df, ["policy_variant", "event"], gap_cols)


def build_search_early_state_summary_from_turn_gap_df(turn_gap_df: pd.DataFrame) -> pd.DataFrame:
    if turn_gap_df.empty:
        return pd.DataFrame()
    value_cols = [
        "city_count_gap_vs_greedy",
        "connected_city_count_gap_vs_greedy",
        "network_count_gap_vs_greedy",
        "largest_network_size_gap_vs_greedy",
        "food_gap_vs_greedy",
        "score_resource_ring_score_gap_vs_greedy",
        "score_city_score_gap_vs_greedy",
        "score_connected_city_score_gap_vs_greedy",
    ]
    value_cols = [column for column in value_cols if column in turn_gap_df]
    if not value_cols:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for (policy_variant, record_id), group in turn_gap_df.groupby(
        ["policy_variant", "record_id"],
        dropna=False,
    ):
        ordered = group.sort_values("turn")
        turn_limit = int(_number(ordered["turn_limit"].iloc[0], 0))
        windows: list[tuple[str, int]] = [
            ("turn_3", 3),
            ("turn_6", 6),
            ("turn_12", 12),
            ("pct_10", max(1, ceil(turn_limit * 0.10))),
            ("pct_25", max(1, ceil(turn_limit * 0.25))),
        ]
        for label, target_turn in windows:
            row_at_window = _row_at_or_after_turn(ordered, target_turn)
            if row_at_window is None:
                continue
            row: dict[str, object] = {
                "policy_variant": policy_variant,
                "record_id": record_id,
                "window": label,
            }
            for column in value_cols:
                row[column] = row_at_window.get(column)
            rows.append(row)
    early_df = pd.DataFrame(rows)
    if early_df.empty:
        return early_df
    return _summary_table(early_df, ["policy_variant", "window"], value_cols)


def build_search_city_site_summary_from_decision_df(decision_df: pd.DataFrame) -> pd.DataFrame:
    if decision_df.empty or "search_chosen_city_site_score" not in decision_df:
        return pd.DataFrame()
    search_df = decision_df[decision_df.get("ai_type", pd.Series(dtype=object)) == SEARCH_LABEL]
    if search_df.empty:
        return pd.DataFrame()
    value_cols = [
        "search_chosen_city_site_score",
        "search_greedy_city_site_score",
        "search_chosen_city_site_score_delta_vs_greedy",
        "search_chosen_city_resource_ring_bonus",
        "search_greedy_city_resource_ring_bonus",
        "search_chosen_city_food_balance",
        "search_chosen_city_total_yield",
        "search_chosen_city_river_access",
        "search_chosen_city_forest_neighbors",
        "search_chosen_city_mountain_neighbors",
        "search_chosen_city_river_neighbors",
        "search_chosen_city_plain_neighbors",
        "search_chosen_city_distance_to_network",
    ]
    value_cols = [column for column in value_cols if column in search_df]
    rows: list[dict[str, object]] = []
    windows = [
        ("turn_3", lambda group: group["turn"] <= 3),
        ("turn_6", lambda group: group["turn"] <= 6),
        ("turn_12", lambda group: group["turn"] <= 12),
        ("pct_10", lambda group: group["turn"] <= (group["turn_limit"] * 0.10).map(ceil)),
        ("pct_25", lambda group: group["turn"] <= (group["turn_limit"] * 0.25).map(ceil)),
    ]
    for label, predicate in windows:
        subset = search_df[predicate(search_df)].copy()
        if subset.empty:
            continue
        subset = subset[subset["search_chosen_city_site_score"].notna()]
        if subset.empty:
            continue
        subset["window"] = label
        rows.extend(subset.to_dict("records"))
    early_df = pd.DataFrame(rows)
    if early_df.empty:
        return early_df
    return _summary_table(early_df, ["policy_variant", "window"], value_cols)


def build_search_mode_transition_summary_from_decision_df(
    decision_df: pd.DataFrame,
) -> pd.DataFrame:
    if decision_df.empty or "search_mode" not in decision_df:
        return pd.DataFrame()
    search_df = decision_df[decision_df.get("ai_type", pd.Series(dtype=object)) == SEARCH_LABEL]
    if search_df.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for (policy_variant, record_id), group in search_df.groupby(
        ["policy_variant", "record_id"],
        dropna=False,
    ):
        ordered = group.sort_values("turn")
        turn_limit = int(_number(ordered["turn_limit"].iloc[0], 0))
        early_threshold = max(1, ceil(turn_limit * 0.25))
        modes = ordered.get("search_mode", pd.Series(dtype=object)).fillna("")
        chosen = ordered.get("chosen_action_type", pd.Series(dtype=object)).fillna("")
        effective_city = ordered.get(
            "search_root_effective_city_candidate_count",
            pd.Series(0, index=ordered.index),
        ).fillna(0)
        candidate_city = ordered.get(
            "search_root_candidate_build_city_count",
            pd.Series(0, index=ordered.index),
        ).fillna(0)
        effective_roads = ordered.get(
            "search_root_effective_connection_road_candidate_count",
            pd.Series(0, index=ordered.index),
        ).fillna(0)
        high_roi = ordered.get(
            "search_root_high_roi_building_candidate_count",
            pd.Series(0, index=ordered.index),
        ).fillna(0)
        safe_deficit = ordered.get(
            "search_profile_safe_expansion_deficit",
            pd.Series(0, index=ordered.index),
        ).fillna(0)
        rows.append(
            {
                "policy_variant": policy_variant,
                "record_id": record_id,
                "first_fill_turn": _first_series_turn(ordered, modes == "fill"),
                "first_connect_turn": _first_series_turn(ordered, modes == "connect"),
                "fill_before_25_pct": int(
                    ((modes == "fill") & (ordered["turn"] <= early_threshold)).any()
                ),
                "connect_without_effective_road_turns": int(
                    ((modes == "connect") & (effective_roads <= 0)).sum()
                ),
                "expand_city_candidate_available_but_building_chosen": int(
                    (
                        (modes == "expand") & (candidate_city > 0) & (chosen == "build_building")
                    ).sum()
                ),
                "effective_city_candidate_available_but_non_city_chosen": int(
                    ((modes == "expand") & (effective_city > 0) & (chosen != "build_city")).sum()
                ),
                "high_roi_building_chosen_before_city_target_met": int(
                    ((high_roi > 0) & (chosen == "build_building") & (safe_deficit > 0)).sum()
                ),
            }
        )
    mode_df = pd.DataFrame(rows)
    if mode_df.empty:
        return mode_df
    return _summary_table(
        mode_df,
        ["policy_variant"],
        [
            "first_fill_turn",
            "first_connect_turn",
            "fill_before_25_pct",
            "connect_without_effective_road_turns",
            "expand_city_candidate_available_but_building_chosen",
            "effective_city_candidate_available_but_non_city_chosen",
            "high_roi_building_chosen_before_city_target_met",
        ],
    )


def build_search_greedy_anchor_summary_from_decision_df(decision_df: pd.DataFrame) -> pd.DataFrame:
    if decision_df.empty or "search_greedy_action_type" not in decision_df:
        return pd.DataFrame()
    search_df = decision_df[
        (decision_df.get("ai_type", pd.Series(dtype=object)) == SEARCH_LABEL)
        & (decision_df["search_greedy_action_type"].fillna("") != "")
    ].copy()
    if search_df.empty:
        return pd.DataFrame()
    value_cols = [
        "search_matches_greedy_action",
        "search_greedy_action_in_root_candidates",
        "search_greedy_action_root_rank",
        "search_greedy_action_root_value_margin",
        "search_chosen_value_delta_vs_greedy_action",
        "search_chosen_city_site_score_delta_vs_greedy",
        "search_chosen_city_resource_ring_bonus",
        "search_greedy_city_resource_ring_bonus",
    ]
    value_cols = [column for column in value_cols if column in search_df]
    return _summary_table(search_df, ["policy_variant"], value_cols)


def build_search_network_food_risk_summary_from_decision_df(
    decision_df: pd.DataFrame,
) -> pd.DataFrame:
    if decision_df.empty or "search_min_network_food_after_action" not in decision_df:
        return pd.DataFrame()
    search_df = decision_df[decision_df.get("ai_type", pd.Series(dtype=object)) == SEARCH_LABEL]
    if search_df.empty:
        return pd.DataFrame()
    value_cols = [
        "search_min_network_food_after_action",
        "search_worst_network_food_pressure_after_action",
        "search_food_surplus_network_count_after_action",
        "search_food_deficit_network_count_after_action",
        "search_delta_worst_network_food_pressure",
        "search_delta_min_network_food",
    ]
    value_cols = [column for column in value_cols if column in search_df]
    return _summary_table(search_df, ["policy_variant"], value_cols)


def build_search_timing_value_summary(
    decision_df: pd.DataFrame,
    turn_gap_df: pd.DataFrame,
) -> pd.DataFrame:
    if decision_df.empty or "decision_time_ms" not in decision_df:
        return pd.DataFrame()
    search_df = decision_df[decision_df.get("ai_type", pd.Series(dtype=object)) == SEARCH_LABEL]
    if search_df.empty:
        return pd.DataFrame()

    gap_cols = pd.DataFrame()
    if not turn_gap_df.empty and "score_gap_vs_greedy" in turn_gap_df:
        gap_cols = turn_gap_df[["record_id", "turn", "score_gap_vs_greedy"]].copy()
        gap_cols = gap_cols.sort_values(["record_id", "turn"])
        gap_cols["next_score_gap_vs_greedy"] = gap_cols.groupby("record_id")[
            "score_gap_vs_greedy"
        ].shift(-1)
        gap_cols["gap_delta_after_search_decision"] = (
            gap_cols["next_score_gap_vs_greedy"] - gap_cols["score_gap_vs_greedy"]
        )
        search_df = search_df.merge(gap_cols, on=["record_id", "turn"], how="left")

    if "search_root_value_margin" in search_df:
        denominator = search_df["decision_time_ms"].fillna(0).clip(lower=0.000001)
        search_df["value_margin_per_ms"] = search_df["search_root_value_margin"].fillna(0) / (
            denominator
        )
    group_cols = ["policy_variant", "search_mode", "search_depth_reason"]
    value_cols = [
        "decision_time_ms",
        "search_leaf_count",
        "search_nodes_expanded",
        "search_root_value_margin",
        "value_margin_per_ms",
        "gap_delta_after_search_decision",
    ]
    value_cols = [column for column in value_cols if column in search_df]
    return _summary_table(search_df, group_cols, value_cols)


def _first_gap_turn(
    turns: list[int],
    gaps: list[float],
    predicate: Callable[[float], bool],
) -> int | None:
    for turn, gap in zip(turns, gaps, strict=False):
        if predicate(gap):
            return turn
    return None


def _first_persistent_gap_turn(
    turns: list[int],
    gaps: list[float],
    predicate: Callable[[float], bool],
) -> int | None:
    for index, turn in enumerate(turns):
        if all(predicate(gap) for gap in gaps[index:]):
            return turn
    return None


def _gap_at_target_turn(turns: list[int], gaps: list[float], target_turn: int) -> float | None:
    if not turns:
        return None
    for turn, gap in zip(turns, gaps, strict=False):
        if turn >= target_turn:
            return gap
    return gaps[-1]


def _recovery_metrics(gaps: list[float]) -> tuple[int, float]:
    recovery_count = 0
    was_under = False
    previous_under = False
    min_under_gap = 0.0
    max_recovery_gap = 0.0
    for gap in gaps:
        is_under = gap < 0
        if is_under:
            was_under = True
            min_under_gap = min(min_under_gap, gap)
        elif was_under and previous_under:
            recovery_count += 1
        if was_under:
            max_recovery_gap = max(max_recovery_gap, gap - min_under_gap)
        previous_under = is_under
    return recovery_count, max_recovery_gap


def _row_at_or_after_turn(group: pd.DataFrame, target_turn: int) -> dict[str, object] | None:
    ordered = group.sort_values("turn")
    subset = ordered[ordered["turn"] >= target_turn]
    if subset.empty:
        subset = ordered.tail(1)
    if subset.empty:
        return None
    return subset.iloc[0].to_dict()


def _first_series_turn(group: pd.DataFrame, mask: pd.Series) -> int | None:
    subset = group[mask]
    if subset.empty:
        return None
    return int(_number(subset.sort_values("turn").iloc[0]["turn"], 0))


def build_map_df(records: list[RecordEntry]) -> pd.DataFrame:
    return pd.DataFrame(record_map_row(record) for record in records)


def _sample_rows(records: list[RecordEntry]) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for policy_variant in sorted({policy_variant_label(record) for record in records}):
        subset = [record for record in records if policy_variant_label(record) == policy_variant]
        if not subset:
            continue
        samples.extend(
            [
                {
                    "label": f"{policy_variant} highest score",
                    "record": max(subset, key=lambda r: r.final_score),
                },
                {
                    "label": f"{policy_variant} lowest score",
                    "record": min(subset, key=lambda r: r.final_score),
                },
                {
                    "label": f"{policy_variant} highest skip_count",
                    "record": max(subset, key=lambda r: r.skip_count),
                },
                {
                    "label": f"{policy_variant} largest network_count",
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
    return artifact_record_to_state(record)


def _policy_type_from_label(label: str) -> PolicyType:
    if label == "Greedy":
        return PolicyType.GREEDY
    if label == "Random":
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
            f"first_reopen={case['first_stage_expand_reopen_turn']}, "
            f"reopen_turns={case['expand_reopen_stage_turns']}, "
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


def summarize_policy_anomaly(
    record: RecordEntry,
    random_peer: RecordEntry | None,
    greedy_peer: RecordEntry | None,
) -> dict[str, object]:
    score_drop_turns, worst_score_drop = _score_drop_metrics(record)
    connected_cities, largest_network_size = _connected_city_metrics(record)
    tail_actions = record.action_log[-TAIL_WINDOW:]
    tail_skip_ratio = sum(1 for action in tail_actions if action.action_type == "skip") / max(
        len(tail_actions), 1
    )
    greedy_contexts = [context for context in record.decision_contexts if context.greedy_stage]
    food_pressures = [
        context.greedy_food_pressure
        for context in greedy_contexts
        if context.greedy_food_pressure is not None
    ]
    is_negative_score = record.final_score < 0
    has_starvation = _has_starvation(record)
    is_common_anomaly = is_negative_score or has_starvation
    is_greedy_under_random = (
        record.ai_type == GREEDY_LABEL
        and random_peer is not None
        and record.final_score < random_peer.final_score
    )
    is_search_under_random = (
        record.ai_type == SEARCH_LABEL
        and random_peer is not None
        and record.final_score < random_peer.final_score
    )
    is_search_under_greedy = (
        record.ai_type == SEARCH_LABEL
        and greedy_peer is not None
        and record.final_score < greedy_peer.final_score
    )
    is_anomaly = (
        is_common_anomaly
        or is_greedy_under_random
        or is_search_under_random
        or is_search_under_greedy
    )
    return {
        "record_id": record.record_id,
        "seed": record.seed,
        "ai_type": record.ai_type,
        "policy_variant": policy_variant_label(record),
        "map_size": record.map_size,
        "turn_limit": record.turn_limit,
        "map_difficulty": record.map_difficulty,
        "final_score": record.final_score,
        "random_record_id": random_peer.record_id if random_peer is not None else None,
        "greedy_record_id": greedy_peer.record_id if greedy_peer is not None else None,
        "random_score": random_peer.final_score if random_peer is not None else None,
        "greedy_baseline_score": greedy_peer.final_score if greedy_peer is not None else None,
        "score_gap": (
            record.final_score - random_peer.final_score if random_peer is not None else None
        ),
        "score_gap_vs_random": (
            record.final_score - random_peer.final_score if random_peer is not None else None
        ),
        "score_gap_vs_greedy": (
            record.final_score - greedy_peer.final_score if greedy_peer is not None else None
        ),
        "has_random_peer": int(random_peer is not None),
        "has_greedy_peer": int(greedy_peer is not None),
        "is_anomaly": int(is_anomaly),
        "is_common_anomaly": int(is_common_anomaly),
        "is_negative_score": int(is_negative_score),
        "has_starvation": int(has_starvation),
        "is_greedy_under_random": int(is_greedy_under_random),
        "is_search_under_random": int(is_search_under_random),
        "is_search_under_greedy": int(is_search_under_greedy),
        "is_under_random": int(is_greedy_under_random or is_search_under_random),
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
        "avg_food_pressure": (sum(food_pressures) / len(food_pressures) if food_pressures else 0.0),
        "max_starving_networks_seen": max(
            (snapshot.starving_network_count for snapshot in record.turn_snapshots),
            default=0,
        ),
        "final_starving_network_count": sum(1 for network in record.networks if network.food <= 0),
        "final_largest_network_size": largest_network_size,
        "final_connected_city_ratio": connected_cities / max(record.city_count, 1),
        "late_game_no_growth_streak": _late_game_no_growth_streak(record),
        "score_drop_turns": score_drop_turns,
        "worst_score_drop": worst_score_drop,
        "record": record,
        "random_peer": random_peer,
        "greedy_peer": greedy_peer,
    }


def build_policy_anomaly_df(records: list[RecordEntry]) -> pd.DataFrame:
    random_index = _build_random_index(records)
    greedy_index = _build_greedy_index(records)
    rows = []
    for record in records:
        match_key = _record_match_key(record)
        case = summarize_policy_anomaly(
            record,
            random_index.get(match_key),
            greedy_index.get(match_key),
        )
        rows.append({key: value for key, value in case.items() if not key.endswith("_peer")})
        rows[-1].pop("record", None)
    return pd.DataFrame(rows)


def build_policy_anomaly_summary_df(records: list[RecordEntry]) -> pd.DataFrame:
    anomaly_df = build_policy_anomaly_df(records)
    if anomaly_df.empty:
        return anomaly_df
    summary = (
        anomaly_df.groupby(["policy_variant"], dropna=False)
        .agg(
            samples=("record_id", "size"),
            anomaly_count=("is_anomaly", "sum"),
            common_anomaly_count=("is_common_anomaly", "sum"),
            negative_score_count=("is_negative_score", "sum"),
            starvation_count=("has_starvation", "sum"),
            under_random_count=("is_under_random", "sum"),
            search_under_greedy_count=("is_search_under_greedy", "sum"),
            avg_score_gap_vs_random=("score_gap_vs_random", "mean"),
            avg_score_gap_vs_greedy=("score_gap_vs_greedy", "mean"),
        )
        .reset_index()
    )
    summary["anomaly_rate"] = summary["anomaly_count"] / summary["samples"].clip(lower=1)
    return summary.sort_values(["anomaly_rate", "policy_variant"], ascending=[False, True])


def build_policy_anomaly_config_summary_df(records: list[RecordEntry]) -> pd.DataFrame:
    anomaly_df = build_policy_anomaly_df(records)
    if anomaly_df.empty:
        return anomaly_df
    group_cols = ["policy_variant", "map_size", "turn_limit", "map_difficulty"]
    summary = (
        anomaly_df.groupby(group_cols, dropna=False)
        .agg(
            samples=("record_id", "size"),
            anomaly_count=("is_anomaly", "sum"),
            common_anomaly_count=("is_common_anomaly", "sum"),
            under_random_count=("is_under_random", "sum"),
            search_under_greedy_count=("is_search_under_greedy", "sum"),
            avg_score_gap_vs_random=("score_gap_vs_random", "mean"),
            avg_score_gap_vs_greedy=("score_gap_vs_greedy", "mean"),
            avg_starvation_turns=("starvation_turns", "mean"),
        )
        .reset_index()
    )
    summary["anomaly_rate"] = summary["anomaly_count"] / summary["samples"].clip(lower=1)
    return summary.sort_values(
        ["anomaly_rate", "policy_variant", "map_size", "turn_limit", "map_difficulty"],
        ascending=[False, True, True, True, True],
    )


def collect_policy_anomaly_cases(records: list[RecordEntry]) -> list[dict[str, object]]:
    random_index = _build_random_index(records)
    greedy_index = _build_greedy_index(records)
    cases = []
    for record in records:
        match_key = _record_match_key(record)
        case = summarize_policy_anomaly(
            record,
            random_index.get(match_key),
            greedy_index.get(match_key),
        )
        if not case["is_anomaly"]:
            continue
        cases.append(case)
    return sorted(
        cases,
        key=lambda case: (
            str(case["policy_variant"]),
            int(case["seed"]),
            int(case["record_id"]),
        ),
    )


def render_policy_anomaly_case(case: dict[str, object]) -> list[str]:
    record = case["record"]
    assert isinstance(record, RecordEntry)
    score_gap = case["score_gap"]
    greedy_score = (
        case["greedy_baseline_score"] if case["greedy_baseline_score"] is not None else "N/A"
    )
    lines = [
        (
            f"### Anomaly record_id={record.record_id} seed={record.seed} "
            f"policy={case['policy_variant']} "
            f"config={record.map_size}/{record.turn_limit}/{record.map_difficulty}"
        ),
        (
            f"- final_score={record.final_score}, random_score="
            f"{case['random_score'] if case['random_score'] is not None else 'N/A'}, "
            f"greedy_score={greedy_score}, "
            f"score_gap={score_gap if score_gap is not None else 'N/A'}, "
            f"score_gap_vs_greedy="
            f"{case['score_gap_vs_greedy'] if case['score_gap_vs_greedy'] is not None else 'N/A'}"
        ),
        (
            f"- anomaly_flags: negative_score={bool(case['is_negative_score'])}, "
            f"starvation={bool(case['has_starvation'])}, "
            f"under_random={bool(case['is_under_random'])}, "
            f"search_under_greedy={bool(case['is_search_under_greedy'])}"
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
            f"first_reopen={case['first_stage_expand_reopen_turn']}, "
            f"reopen_turns={case['expand_reopen_stage_turns']}, "
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


def build_policy_anomaly_df_from_macro(macro_df: pd.DataFrame) -> pd.DataFrame:
    """Build anomaly rows from artifact macro data."""
    if macro_df.empty:
        return pd.DataFrame()
    random_index = {
        _macro_match_key(row): row
        for row in macro_df.to_dict("records")
        if row.get("ai_type") == RANDOM_LABEL
    }
    greedy_index = {
        _macro_match_key(row): row
        for row in macro_df.to_dict("records")
        if row.get("ai_type") == GREEDY_LABEL
    }
    rows: list[dict[str, object]] = []
    for row in macro_df.to_dict("records"):
        match_key = _macro_match_key(row)
        random_peer = random_index.get(match_key)
        greedy_peer = greedy_index.get(match_key)
        final_score = _number(row.get("final_score"), 0)
        random_score = (
            _number(random_peer.get("final_score"), 0) if random_peer is not None else None
        )
        greedy_score = (
            _number(greedy_peer.get("final_score"), 0) if greedy_peer is not None else None
        )
        is_negative_score = final_score < 0
        has_starvation = bool(_number(row.get("has_starvation"), 0))
        ai_type = str(row.get("ai_type", ""))
        is_common_anomaly = is_negative_score or has_starvation
        is_greedy_under_random = (
            ai_type == GREEDY_LABEL and random_score is not None and final_score < random_score
        )
        is_search_under_random = (
            ai_type == SEARCH_LABEL and random_score is not None and final_score < random_score
        )
        is_search_under_greedy = (
            ai_type == SEARCH_LABEL and greedy_score is not None and final_score < greedy_score
        )
        is_anomaly = (
            is_common_anomaly
            or is_greedy_under_random
            or is_search_under_random
            or is_search_under_greedy
        )
        output = dict(row)
        output.update(
            {
                "random_record_id": (
                    _number(random_peer.get("record_id"), 0) if random_peer is not None else None
                ),
                "greedy_record_id": (
                    _number(greedy_peer.get("record_id"), 0) if greedy_peer is not None else None
                ),
                "random_score": random_score,
                "greedy_baseline_score": greedy_score,
                "score_gap": final_score - random_score if random_score is not None else None,
                "score_gap_vs_random": (
                    final_score - random_score if random_score is not None else None
                ),
                "score_gap_vs_greedy": (
                    final_score - greedy_score if greedy_score is not None else None
                ),
                "has_random_peer": int(random_peer is not None),
                "has_greedy_peer": int(greedy_peer is not None),
                "is_anomaly": int(is_anomaly),
                "is_common_anomaly": int(is_common_anomaly),
                "is_negative_score": int(is_negative_score),
                "is_greedy_under_random": int(is_greedy_under_random),
                "is_search_under_random": int(is_search_under_random),
                "is_search_under_greedy": int(is_search_under_greedy),
                "is_under_random": int(is_greedy_under_random or is_search_under_random),
            }
        )
        rows.append(output)
    return pd.DataFrame(rows)


def policy_anomaly_summary_from_df(anomaly_df: pd.DataFrame) -> pd.DataFrame:
    if anomaly_df.empty:
        return anomaly_df
    summary = (
        anomaly_df.groupby(["policy_variant"], dropna=False)
        .agg(
            samples=("record_id", "size"),
            anomaly_count=("is_anomaly", "sum"),
            common_anomaly_count=("is_common_anomaly", "sum"),
            negative_score_count=("is_negative_score", "sum"),
            starvation_count=("has_starvation", "sum"),
            under_random_count=("is_under_random", "sum"),
            search_under_greedy_count=("is_search_under_greedy", "sum"),
            avg_score_gap_vs_random=("score_gap_vs_random", "mean"),
            avg_score_gap_vs_greedy=("score_gap_vs_greedy", "mean"),
        )
        .reset_index()
    )
    summary["anomaly_rate"] = summary["anomaly_count"] / summary["samples"].clip(lower=1)
    return summary.sort_values(["anomaly_rate", "policy_variant"], ascending=[False, True])


def policy_anomaly_config_summary_from_df(anomaly_df: pd.DataFrame) -> pd.DataFrame:
    if anomaly_df.empty:
        return anomaly_df
    group_cols = ["policy_variant", "map_size", "turn_limit", "map_difficulty"]
    summary = (
        anomaly_df.groupby(group_cols, dropna=False)
        .agg(
            samples=("record_id", "size"),
            anomaly_count=("is_anomaly", "sum"),
            common_anomaly_count=("is_common_anomaly", "sum"),
            under_random_count=("is_under_random", "sum"),
            search_under_greedy_count=("is_search_under_greedy", "sum"),
            avg_score_gap_vs_random=("score_gap_vs_random", "mean"),
            avg_score_gap_vs_greedy=("score_gap_vs_greedy", "mean"),
            avg_starvation_turns=("starvation_turns", "mean"),
        )
        .reset_index()
    )
    summary["anomaly_rate"] = summary["anomaly_count"] / summary["samples"].clip(lower=1)
    return summary.sort_values(
        ["anomaly_rate", "policy_variant", "map_size", "turn_limit", "map_difficulty"],
        ascending=[False, True, True, True, True],
    )


def search_anomaly_cases_from_df(
    anomaly_df: pd.DataFrame,
    *,
    limit: int = 30,
) -> list[dict[str, object]]:
    if anomaly_df.empty or "ai_type" not in anomaly_df:
        return []
    search_df = anomaly_df[
        (anomaly_df["ai_type"] == SEARCH_LABEL)
        & (anomaly_df.get("is_anomaly", pd.Series(dtype=float)).fillna(0) == 1)
    ].copy()
    if search_df.empty:
        return []
    for column in [
        "is_negative_score",
        "is_search_under_random",
        "is_search_under_greedy",
        "starvation_turns",
        "score_gap_vs_random",
        "score_gap_vs_greedy",
        "final_score",
    ]:
        if column not in search_df:
            search_df[column] = 0
    search_df["search_case_priority"] = (
        search_df["is_negative_score"].fillna(0) * 10_000
        + search_df["is_search_under_random"].fillna(0) * 5_000
        + search_df["starvation_turns"].fillna(0)
    )
    return (
        search_df.sort_values(
            [
                "search_case_priority",
                "score_gap_vs_greedy",
                "score_gap_vs_random",
                "final_score",
                "record_id",
            ],
            ascending=[False, True, True, True, True],
        )
        .head(limit)
        .to_dict("records")
    )


def render_policy_anomaly_row(row: dict[str, object], action_df: pd.DataFrame) -> list[str]:
    """Render a compact anomaly case from artifact rows."""
    lines = [
        (
            f"### Anomaly record_id={_number(row.get('record_id'), 0)} "
            f"seed={_number(row.get('seed'), 0)} policy={row.get('policy_variant', '')} "
            f"config={_number(row.get('map_size'), 0)}/{_number(row.get('turn_limit'), 0)}/"
            f"{row.get('map_difficulty', '')}"
        ),
        (
            f"- final_score={_number(row.get('final_score'), 0)}, "
            f"random_score={_fmt_optional(row.get('random_score'))}, "
            f"greedy_score={_fmt_optional(row.get('greedy_baseline_score'))}, "
            f"score_gap={_fmt_optional(row.get('score_gap'))}, "
            f"score_gap_vs_greedy={_fmt_optional(row.get('score_gap_vs_greedy'))}"
        ),
        (
            f"- anomaly_flags: negative_score={bool(_number(row.get('is_negative_score'), 0))}, "
            f"starvation={bool(_number(row.get('has_starvation'), 0))}, "
            f"under_random={bool(_number(row.get('is_under_random'), 0))}, "
            f"search_under_greedy={bool(_number(row.get('is_search_under_greedy'), 0))}"
        ),
        (
            f"- starvation: first={_fmt_optional(row.get('first_starvation_turn'))}, "
            f"turns={_number(row.get('starvation_turns'), 0)}, "
            f"longest_streak={_number(row.get('longest_starvation_streak'), 0)}, "
            f"negative_food_first={_fmt_optional(row.get('first_negative_food_turn'))}, "
            f"negative_food_turns={_number(row.get('negative_food_turns'), 0)}"
        ),
        "- first 20 actions:",
        "```",
        render_action_log_from_df(action_df, int(_number(row.get("record_id"), 0))),
        "```",
        "",
    ]
    return lines


def render_search_anomaly_row(
    row: dict[str, object],
    action_df: pd.DataFrame,
    decision_df: pd.DataFrame,
) -> list[str]:
    record_id = int(_number(row.get("record_id"), 0))
    lines = [
        (
            f"### Search Case record_id={record_id} seed={_number(row.get('seed'), 0):.0f} "
            f"policy={row.get('policy_variant', '')} "
            f"config={_number(row.get('map_size'), 0):.0f}/"
            f"{_number(row.get('turn_limit'), 0):.0f}/{row.get('map_difficulty', '')}"
        ),
        (
            f"- scores: search={_number(row.get('final_score'), 0):.0f}, "
            f"greedy={_fmt_optional(row.get('greedy_baseline_score'))}, "
            f"random={_fmt_optional(row.get('random_score'))}, "
            f"gap_vs_greedy={_fmt_optional(row.get('score_gap_vs_greedy'))}, "
            f"gap_vs_random={_fmt_optional(row.get('score_gap_vs_random'))}"
        ),
        (
            f"- flags: negative={bool(_number(row.get('is_negative_score'), 0))}, "
            f"starvation={bool(_number(row.get('has_starvation'), 0))}, "
            f"under_random={bool(_number(row.get('is_search_under_random'), 0))}, "
            f"under_greedy={bool(_number(row.get('is_search_under_greedy'), 0))}, "
            f"first_starvation={_fmt_optional(row.get('first_starvation_turn'))}, "
            f"starvation_turns={_number(row.get('starvation_turns'), 0):.0f}"
        ),
        "- first 20 decisions:",
        "```",
        render_search_decision_window_from_df(action_df, decision_df, record_id),
        "```",
        "- last 20 decisions:",
        "```",
        render_search_decision_window_from_df(
            action_df,
            decision_df,
            record_id,
            from_end=True,
        ),
        "```",
        "",
    ]
    first_starvation = row.get("first_starvation_turn")
    if not _is_missing(first_starvation):
        lines.extend(
            [
                "- first starvation window:",
                "```",
                render_search_decision_window_from_df(
                    action_df,
                    decision_df,
                    record_id,
                    center_turn=int(_number(first_starvation, 0)),
                    max_turns=9,
                ),
                "```",
                "",
            ]
        )
    return lines


def render_action_log_from_df(
    action_df: pd.DataFrame,
    record_id: int,
    max_turns: int = 20,
    *,
    from_end: bool = False,
) -> str:
    if action_df.empty or "record_id" not in action_df:
        return "_No actions_"
    subset = action_df[action_df["record_id"] == record_id].sort_values("action_index")
    if subset.empty:
        return "_No actions_"
    if from_end:
        subset = subset.tail(max_turns)
    else:
        subset = subset.head(max_turns)
    lines = []
    for row in subset.to_dict("records"):
        coord = (
            f"({_fmt_optional(row.get('x'))},{_fmt_optional(row.get('y'))})"
            if not _is_missing(row.get("x"))
            else "-"
        )
        lines.append(
            f"  T{_number(row.get('turn'), 0):>3} | "
            f"{str(row.get('action_type', '')):18} | coord={coord:8}"
        )
    return "\n".join(lines)


def render_search_decision_window_from_df(
    action_df: pd.DataFrame,
    decision_df: pd.DataFrame,
    record_id: int,
    max_turns: int = 20,
    *,
    from_end: bool = False,
    center_turn: int | None = None,
) -> str:
    if action_df.empty or "record_id" not in action_df:
        return "_No actions_"
    actions = action_df[action_df["record_id"] == record_id].sort_values("action_index")
    if actions.empty:
        return "_No actions_"
    if center_turn is not None:
        lower = center_turn - max_turns // 2
        upper = center_turn + max_turns // 2
        actions = actions[(actions["turn"] >= lower) & (actions["turn"] <= upper)]
    elif from_end:
        actions = actions.tail(max_turns)
    else:
        actions = actions.head(max_turns)

    decisions_by_turn: dict[int, dict[str, object]] = {}
    if not decision_df.empty and "record_id" in decision_df:
        decision_subset = decision_df[decision_df["record_id"] == record_id]
        decisions_by_turn = {
            int(_number(item.get("turn"), 0)): item for item in decision_subset.to_dict("records")
        }

    lines = []
    for action in actions.to_dict("records"):
        turn = int(_number(action.get("turn"), 0))
        decision = decisions_by_turn.get(turn, {})
        coord = (
            f"({_fmt_optional(action.get('x'))},{_fmt_optional(action.get('y'))})"
            if not _is_missing(action.get("x"))
            else "-"
        )
        lines.append(
            f"  T{turn:>3} | {str(action.get('action_type', '')):18} | coord={coord:8} | "
            f"mode={decision.get('search_mode', '-') or '-':8} | "
            f"depth={_fmt_optional(decision.get('search_depth')):>3}/"
            f"{_fmt_optional(decision.get('search_actual_depth')):<3} | "
            f"plan={decision.get('search_planning_mode', '-') or '-':13} | "
            f"reason={decision.get('search_planning_reason', '-') or '-':20} | "
            f"pressure={decision.get('search_dominant_pressure', '-') or '-':24} | "
            f"rank={_fmt_optional(decision.get('search_root_chosen_rank')):>3} | "
            f"margin={_fmt_optional(decision.get('search_root_value_margin')):>6} | "
            f"d_food={_fmt_optional(decision.get('search_delta_food_pressure')):>4} | "
            f"d_net_food={_fmt_optional(decision.get('search_delta_min_network_food')):>4} | "
            f"d_net_pressure="
            f"{_fmt_optional(decision.get('search_delta_worst_network_food_pressure')):>4} | "
            f"d_conn={_fmt_optional(decision.get('search_delta_connected_city_count')):>4} | "
            f"road_redundant={_fmt_optional(decision.get('search_road_is_redundant'))}"
        )
    return "\n".join(lines) if lines else "_No actions_"


def generate_report_from_artifacts(frames: dict[str, pd.DataFrame]) -> str:
    """Generate a report directly from artifact tables."""
    macro_df = frames.get("macro", pd.DataFrame())
    score_df = frames.get("score_breakdowns", pd.DataFrame())
    turn_score_df = frames.get("turn_scores", pd.DataFrame())
    behavior_df = frames.get("behavior", pd.DataFrame())
    decision_df = frames.get("decisions", pd.DataFrame())
    map_df = frames.get("maps", pd.DataFrame())
    action_df = frames.get("actions", pd.DataFrame())

    if macro_df.empty:
        return f"# {APP_NAME} Dataset Report\n\n_No data_"

    stage_summary = build_stage_summary_from_decision_df(decision_df)
    search_summary = build_search_summary_from_decision_df(decision_df)
    search_mode_summary = build_search_mode_summary_from_decision_df(decision_df)
    search_depth_reason_summary = build_search_depth_reason_summary_from_decision_df(decision_df)
    search_planning_summary = build_search_planning_summary_from_decision_df(decision_df)
    search_pressure_summary = build_search_pressure_summary_from_decision_df(decision_df)
    search_matchup_summary = build_search_matchup_summary_from_macro_df(macro_df)
    search_candidate_health_summary = build_search_candidate_health_summary_from_decision_df(
        decision_df
    )
    search_road_quality_summary = build_search_road_quality_summary_from_decision_df(decision_df)
    search_record_profile_summary = build_search_record_profile_summary_from_decision_df(
        decision_df
    )
    search_score_gap_summary = build_search_score_component_gap_summary_from_score_df(score_df)
    search_turn_gap_df = build_search_turn_gap_df(macro_df, turn_score_df)
    search_lag_event_df = build_search_lag_event_df(search_turn_gap_df)
    search_lag_summary = build_search_lag_summary_from_lag_df(search_lag_event_df)
    search_lag_config_summary = build_search_lag_config_summary_from_lag_df(search_lag_event_df)
    search_lag_event_component_summary = build_search_lag_event_component_summary(
        search_lag_event_df,
        search_turn_gap_df,
    )
    search_early_state_summary = build_search_early_state_summary_from_turn_gap_df(
        search_turn_gap_df
    )
    search_city_site_summary = build_search_city_site_summary_from_decision_df(decision_df)
    search_mode_transition_summary = build_search_mode_transition_summary_from_decision_df(
        decision_df
    )
    search_greedy_anchor_summary = build_search_greedy_anchor_summary_from_decision_df(decision_df)
    search_network_food_risk_summary = build_search_network_food_risk_summary_from_decision_df(
        decision_df
    )
    search_timing_value_summary = build_search_timing_value_summary(
        decision_df,
        search_turn_gap_df,
    )
    anomaly_df = build_policy_anomaly_df_from_macro(macro_df)
    anomaly_summary = policy_anomaly_summary_from_df(anomaly_df)
    anomaly_config_summary = policy_anomaly_config_summary_from_df(anomaly_df)
    search_anomaly_cases = search_anomaly_cases_from_df(anomaly_df)
    anomaly_cases = (
        anomaly_df[anomaly_df["is_anomaly"] == 1]
        .sort_values(["policy_variant", "seed", "record_id"])
        .head(50)
        .to_dict("records")
        if not anomaly_df.empty
        else []
    )

    dataset_overview = pd.DataFrame(
        [
            {
                "total_games": len(macro_df),
                "policy_count": macro_df["ai_type"].nunique(),
                "policy_variant_count": macro_df["policy_variant"].nunique(),
                "map_size_count": macro_df["map_size"].nunique(),
                "turn_limit_count": macro_df["turn_limit"].nunique(),
                "difficulty_count": macro_df["map_difficulty"].nunique(),
                "config_count": macro_df[
                    ["policy_variant", "map_size", "turn_limit", "map_difficulty"]
                ]
                .drop_duplicates()
                .shape[0],
            }
        ]
    )
    config_coverage = (
        macro_df.groupby(
            ["policy_variant", "map_size", "turn_limit", "map_difficulty"],
            dropna=False,
        )
        .size()
        .reset_index(name="samples")
        .sort_values(["policy_variant", "map_size", "turn_limit", "map_difficulty"])
    )
    policy_summary = _summary_table(
        macro_df,
        ["policy_variant"],
        [
            "final_score",
            "city_count",
            "road_count",
            "building_count",
            "tech_count",
            "network_count",
            "largest_network_size",
            "buildings_per_city",
            "roads_per_city",
            "score_per_city",
            "score_per_building",
            "connected_city_ratio",
            "skip_count",
            "food",
            "wood",
            "ore",
            "science",
            "decision_time_ms_avg",
            "decision_time_ms_max",
            "decision_time_ms_total",
        ],
    )
    config_summary = _summary_table(
        macro_df,
        ["policy_variant", "map_size", "turn_limit", "map_difficulty"],
        [
            "final_score",
            "city_count",
            "road_count",
            "building_count",
            "tech_count",
            "network_count",
            "buildings_per_city",
            "roads_per_city",
            "connected_city_ratio",
            "skip_count",
            "first_negative_food_turn",
            "decision_time_ms_avg",
        ],
    )
    score_summary = (
        _summary_table(
            score_df,
            ["policy_variant"],
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
        if not score_df.empty
        else pd.DataFrame()
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
            ["policy_variant"],
            [column for column in turn_score_value_cols if column in turn_score_df],
        )
        if (
            not turn_score_df.empty
            and any(column in turn_score_df for column in turn_score_value_cols)
        )
        else pd.DataFrame()
    )
    behavior_summary = (
        _summary_table(
            behavior_df,
            ["policy_variant"],
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
        if not behavior_df.empty
        else pd.DataFrame()
    )
    network_summary = _summary_table(
        macro_df,
        ["policy_variant"],
        [
            "network_count",
            "connected_cities",
            "isolated_cities",
            "largest_network_size",
            "starving_network_count",
            "first_negative_food_turn",
        ],
    )
    map_summary = (
        _summary_table(
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
        if not map_df.empty
        else pd.DataFrame()
    )

    lines = [
        f"# {APP_NAME} Dataset Report",
        "",
        "_Source: artifact tables_",
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
        "### 7.1 Search Diagnostic Summary",
        "",
        make_table(search_summary),
        "",
        "### 7.2 Search Depth Reason Summary",
        "",
        make_table(search_depth_reason_summary),
        "",
        "### 7.3 Search Planning Summary",
        "",
        make_table(search_planning_summary),
        "",
        "### 7.4 Search Mode Summary",
        "",
        make_table(search_mode_summary),
        "",
        "### 7.5 Search Pressure Driver Summary",
        "",
        make_table(search_pressure_summary),
        "",
        "### 7.6 Search Same-Map Matchup Summary",
        "",
        make_table(search_matchup_summary),
        "",
        "### 7.7 Search Candidate Health Summary",
        "",
        make_table(search_candidate_health_summary),
        "",
        "### 7.8 Search Road Quality Summary",
        "",
        make_table(search_road_quality_summary),
        "",
        "### 7.9 Search Record Profile Summary",
        "",
        make_table(search_record_profile_summary),
        "",
        "### 7.10 Search Score Component Gap vs Greedy",
        "",
        make_table(search_score_gap_summary),
        "",
        "### 7.11 Search Turn Lag Summary",
        "",
        make_table(search_lag_summary),
        "",
        "### 7.12 Search Lag Config Summary",
        "",
        make_table(search_lag_config_summary),
        "",
        "### 7.13 Search Lag Event Component Gap",
        "",
        make_table(search_lag_event_component_summary),
        "",
        "### 7.14 Search Early State Gap",
        "",
        make_table(search_early_state_summary),
        "",
        "### 7.15 Search Early City Site Quality",
        "",
        make_table(search_city_site_summary),
        "",
        "### 7.16 Search Mode Transition Diagnostics",
        "",
        make_table(search_mode_transition_summary),
        "",
        "### 7.17 Search Greedy Anchor Diagnostics",
        "",
        make_table(search_greedy_anchor_summary),
        "",
        "### 7.18 Search Network Food Risk",
        "",
        make_table(search_network_food_risk_summary),
        "",
        "### 7.19 Search Timing Value Summary",
        "",
        make_table(search_timing_value_summary),
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
        make_table(anomaly_summary, floatfmt=".3f"),
        "",
        "### 10.1 Anomaly Config Summary",
        "",
        make_table(anomaly_config_summary),
        "",
        "### 10.2 Search Anomaly Cases",
        "",
    ]
    if not search_anomaly_cases:
        lines.extend(["_No data_", ""])
    else:
        for row in search_anomaly_cases:
            lines.extend(render_search_anomaly_row(row, action_df, decision_df))

    lines.extend(
        [
            "## 11. Anomaly Cases",
            "",
        ]
    )
    if not anomaly_cases:
        lines.extend(["_No data_", ""])
    else:
        for row in anomaly_cases:
            lines.extend(render_policy_anomaly_row(row, action_df))
    return "\n".join(lines)


def _macro_match_key(row: dict[str, object]) -> tuple[int, int, int, str]:
    return (
        int(_number(row.get("seed"), 0)),
        int(_number(row.get("map_size"), 0)),
        int(_number(row.get("turn_limit"), 0)),
        str(row.get("map_difficulty", "")),
    )


def _number(value: object, default: float) -> float:
    if _is_missing(value):
        return default
    if isinstance(value, Real):
        return float(value)
    if isinstance(value, str) and value:
        return float(value)
    return default


def _is_missing(value: object) -> bool:
    return value is None or bool(pd.isna(value))


def _fmt_optional(value: object) -> str:
    if _is_missing(value):
        return "N/A"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def generate_report(records: list[RecordEntry]) -> str:
    if pd is None:  # pragma: no cover - depends on local optional deps
        raise RuntimeError(
            "scripts/analyze_batch.py requires pandas and tabulate. Install dev dependencies first."
        ) from PANDAS_IMPORT_ERROR
    macro_df = build_macro_df(records)
    score_df = build_score_breakdown_df(records)
    turn_score_df = build_turn_score_breakdown_df(records)
    behavior_df = build_behavior_df(records)
    decision_df = build_decision_context_df(records)
    action_df = build_action_df(records)
    stage_df = build_stage_summary_from_decision_df(decision_df)
    search_summary = build_search_summary_from_decision_df(decision_df)
    search_mode_summary = build_search_mode_summary_from_decision_df(decision_df)
    search_depth_reason_summary = build_search_depth_reason_summary_from_decision_df(decision_df)
    search_planning_summary = build_search_planning_summary_from_decision_df(decision_df)
    search_pressure_summary = build_search_pressure_summary_from_decision_df(decision_df)
    search_matchup_summary = build_search_matchup_summary_from_macro_df(macro_df)
    search_candidate_health_summary = build_search_candidate_health_summary_from_decision_df(
        decision_df
    )
    search_road_quality_summary = build_search_road_quality_summary_from_decision_df(decision_df)
    search_record_profile_summary = build_search_record_profile_summary_from_decision_df(
        decision_df
    )
    search_score_gap_summary = build_search_score_component_gap_summary_from_score_df(score_df)
    search_turn_gap_df = build_search_turn_gap_df(macro_df, turn_score_df)
    search_lag_event_df = build_search_lag_event_df(search_turn_gap_df)
    search_lag_summary = build_search_lag_summary_from_lag_df(search_lag_event_df)
    search_lag_config_summary = build_search_lag_config_summary_from_lag_df(search_lag_event_df)
    search_lag_event_component_summary = build_search_lag_event_component_summary(
        search_lag_event_df,
        search_turn_gap_df,
    )
    search_early_state_summary = build_search_early_state_summary_from_turn_gap_df(
        search_turn_gap_df
    )
    search_city_site_summary = build_search_city_site_summary_from_decision_df(decision_df)
    search_mode_transition_summary = build_search_mode_transition_summary_from_decision_df(
        decision_df
    )
    search_greedy_anchor_summary = build_search_greedy_anchor_summary_from_decision_df(decision_df)
    search_network_food_risk_summary = build_search_network_food_risk_summary_from_decision_df(
        decision_df
    )
    search_timing_value_summary = build_search_timing_value_summary(
        decision_df,
        search_turn_gap_df,
    )
    map_df = build_map_df(records)
    anomaly_cases = collect_policy_anomaly_cases(records)
    anomaly_summary = build_policy_anomaly_summary_df(records)
    anomaly_config_summary = build_policy_anomaly_config_summary_df(records)
    anomaly_df = build_policy_anomaly_df(records)
    search_anomaly_cases = search_anomaly_cases_from_df(anomaly_df)
    samples = _sample_rows(records)

    dataset_overview = pd.DataFrame(
        [
            {
                "total_games": len(records),
                "policy_count": macro_df["ai_type"].nunique(),
                "policy_variant_count": macro_df["policy_variant"].nunique(),
                "map_size_count": macro_df["map_size"].nunique(),
                "turn_limit_count": macro_df["turn_limit"].nunique(),
                "difficulty_count": macro_df["map_difficulty"].nunique(),
                "config_count": macro_df[
                    ["policy_variant", "map_size", "turn_limit", "map_difficulty"]
                ]
                .drop_duplicates()
                .shape[0],
            }
        ]
    )
    config_coverage = (
        macro_df.groupby(
            ["policy_variant", "map_size", "turn_limit", "map_difficulty"],
            dropna=False,
        )
        .size()
        .reset_index(name="samples")
        .sort_values(["policy_variant", "map_size", "turn_limit", "map_difficulty"])
    )
    policy_summary = _summary_table(
        macro_df,
        ["policy_variant"],
        [
            "final_score",
            "city_count",
            "road_count",
            "building_count",
            "tech_count",
            "network_count",
            "largest_network_size",
            "buildings_per_city",
            "roads_per_city",
            "score_per_city",
            "score_per_building",
            "connected_city_ratio",
            "skip_count",
            "food",
            "wood",
            "ore",
            "science",
            "decision_time_ms_avg",
            "decision_time_ms_max",
            "decision_time_ms_total",
        ],
    )
    config_summary = _summary_table(
        macro_df,
        ["policy_variant", "map_size", "turn_limit", "map_difficulty"],
        [
            "final_score",
            "city_count",
            "road_count",
            "building_count",
            "tech_count",
            "network_count",
            "buildings_per_city",
            "roads_per_city",
            "connected_city_ratio",
            "skip_count",
            "first_negative_food_turn",
            "decision_time_ms_avg",
        ],
    )
    score_summary = _summary_table(
        score_df,
        ["policy_variant"],
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
            ["policy_variant"],
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
        ["policy_variant"],
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
        ["policy_variant"],
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
        "### 7.1 Search Diagnostic Summary",
        "",
        make_table(search_summary),
        "",
        "### 7.2 Search Depth Reason Summary",
        "",
        make_table(search_depth_reason_summary),
        "",
        "### 7.3 Search Planning Summary",
        "",
        make_table(search_planning_summary),
        "",
        "### 7.4 Search Mode Summary",
        "",
        make_table(search_mode_summary),
        "",
        "### 7.5 Search Pressure Driver Summary",
        "",
        make_table(search_pressure_summary),
        "",
        "### 7.6 Search Same-Map Matchup Summary",
        "",
        make_table(search_matchup_summary),
        "",
        "### 7.7 Search Candidate Health Summary",
        "",
        make_table(search_candidate_health_summary),
        "",
        "### 7.8 Search Road Quality Summary",
        "",
        make_table(search_road_quality_summary),
        "",
        "### 7.9 Search Record Profile Summary",
        "",
        make_table(search_record_profile_summary),
        "",
        "### 7.10 Search Score Component Gap vs Greedy",
        "",
        make_table(search_score_gap_summary),
        "",
        "### 7.11 Search Turn Lag Summary",
        "",
        make_table(search_lag_summary),
        "",
        "### 7.12 Search Lag Config Summary",
        "",
        make_table(search_lag_config_summary),
        "",
        "### 7.13 Search Lag Event Component Gap",
        "",
        make_table(search_lag_event_component_summary),
        "",
        "### 7.14 Search Early State Gap",
        "",
        make_table(search_early_state_summary),
        "",
        "### 7.15 Search Early City Site Quality",
        "",
        make_table(search_city_site_summary),
        "",
        "### 7.16 Search Mode Transition Diagnostics",
        "",
        make_table(search_mode_transition_summary),
        "",
        "### 7.17 Search Greedy Anchor Diagnostics",
        "",
        make_table(search_greedy_anchor_summary),
        "",
        "### 7.18 Search Network Food Risk",
        "",
        make_table(search_network_food_risk_summary),
        "",
        "### 7.19 Search Timing Value Summary",
        "",
        make_table(search_timing_value_summary),
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
        make_table(anomaly_summary, floatfmt=".3f"),
        "",
        "### 10.1 Anomaly Config Summary",
        "",
        make_table(anomaly_config_summary),
        "",
        "### 10.2 Search Anomaly Cases",
        "",
    ]

    if not search_anomaly_cases:
        lines.extend(["_No data_", ""])
    else:
        for row in search_anomaly_cases:
            lines.extend(render_search_anomaly_row(row, action_df, decision_df))

    lines.extend(
        [
            "## 11. Anomaly Cases",
            "",
        ]
    )

    if not anomaly_cases:
        lines.extend(["_No data_", ""])
    else:
        for case in anomaly_cases:
            lines.extend(render_policy_anomaly_case(case))

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
    if is_artifact_dir(args.input):
        frames = read_artifact_frames(args.input, pd)
        report = generate_report_from_artifacts(frames)
    else:
        raw = loads_json_bytes(args.input.read_bytes())
        if not isinstance(raw, dict):
            raise ValueError("Input JSON must be an object.")
        database = RecordDatabase.from_dict(raw)
        report = generate_report(database.records)
    args.output.write_text(report, encoding="utf-8")
    print(f"Report written to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
