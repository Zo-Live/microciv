"""Analyze a MicroCiv batch dataset and emit a descriptive Markdown report."""

from __future__ import annotations

import argparse
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
from microciv.game.enums import PlaybackMode, PolicyType  # noqa: E402
from microciv.game.models import GameState  # noqa: E402
from microciv.records.artifacts import (  # noqa: E402
    is_artifact_dir,
    loads_json_bytes,
    read_artifact_frames,
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
        "search_max_depth",
        "search_beam_width",
        "search_candidate_limit",
        "search_root_candidate_build_city_count",
        "search_root_candidate_build_road_count",
        "search_root_candidate_build_building_count",
        "search_root_candidate_research_tech_count",
        "search_root_candidate_skip_count",
        "search_nodes_expanded",
        "search_candidates_considered",
        "search_leaf_count",
        "search_best_value",
        "search_sequence_adjustment",
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
                "best_value_mean": _metric_mean(group, "search_best_value"),
            }
        )
    return pd.DataFrame(rows).sort_values(["policy_variant", "search_mode"])


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
            avg_score_gap_vs_greedy=("score_gap_vs_greedy", "mean"),
            median_score_gap_vs_greedy=("score_gap_vs_greedy", "median"),
            avg_score_gap_vs_random=("score_gap_vs_random", "mean"),
            median_score_gap_vs_random=("score_gap_vs_random", "median"),
        )
        .reset_index()
    )
    summary["same_map_win_rate"] = summary["same_map_win_rate"] * 100
    summary["task7_acceptance_candidate"] = (
        (summary["same_map_win_rate"] >= 95)
        & (summary["avg_score_gap_vs_greedy"] >= 0)
        & (summary["median_score_gap_vs_greedy"] >= 0)
        & (summary["avg_score_gap_vs_random"] >= 0)
        & (summary["median_score_gap_vs_random"] >= 0)
    ).astype(int)
    return summary.sort_values(["task7_acceptance_candidate", "same_map_win_rate"], ascending=False)


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
    search_matchup_summary = build_search_matchup_summary_from_macro_df(macro_df)
    anomaly_df = build_policy_anomaly_df_from_macro(macro_df)
    anomaly_summary = policy_anomaly_summary_from_df(anomaly_df)
    anomaly_config_summary = policy_anomaly_config_summary_from_df(anomaly_df)
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
        "### 7.3 Search Mode Summary",
        "",
        make_table(search_mode_summary),
        "",
        "### 7.4 Search Same-Map Matchup Summary",
        "",
        make_table(search_matchup_summary),
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
        "## 11. Anomaly Cases",
        "",
    ]
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
    if isinstance(value, int | float):
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
    stage_df = build_stage_summary_from_decision_df(decision_df)
    search_summary = build_search_summary_from_decision_df(decision_df)
    search_mode_summary = build_search_mode_summary_from_decision_df(decision_df)
    search_depth_reason_summary = build_search_depth_reason_summary_from_decision_df(decision_df)
    search_matchup_summary = build_search_matchup_summary_from_macro_df(macro_df)
    map_df = build_map_df(records)
    anomaly_cases = collect_policy_anomaly_cases(records)
    anomaly_summary = build_policy_anomaly_summary_df(records)
    anomaly_config_summary = build_policy_anomaly_config_summary_df(records)
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
        "### 7.3 Search Mode Summary",
        "",
        make_table(search_mode_summary),
        "",
        "### 7.4 Search Same-Map Matchup Summary",
        "",
        make_table(search_matchup_summary),
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
        "## 11. Anomaly Cases",
        "",
    ]

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
