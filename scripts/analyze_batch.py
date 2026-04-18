"""Analyze a MicroCiv batch dataset and emit a descriptive Markdown report."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Final

import pandas as pd

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


def render_turn_log(record: RecordEntry, max_turns: int = 20) -> str:
    actions = record.action_log[:max_turns]
    contexts = record.decision_contexts[:max_turns]
    lines = []
    for index, action in enumerate(actions):
        context = contexts[index] if index < len(contexts) else None
        priority = context.greedy_priority if context is not None else "-"
        legal = context.legal_actions_count if context is not None else "-"
        coord = f"({action.x},{action.y})" if action.x is not None else "-"
        lines.append(
            f"  T{action.turn:>3} | {action.action_type:18} | coord={coord:8} | "
            f"legal={legal:4} | priority={priority or '-'}"
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


def generate_report(records: list[RecordEntry]) -> str:
    macro_df = build_macro_df(records)
    score_df = build_score_breakdown_df(records)
    behavior_df = build_behavior_df(records)
    map_df = build_map_df(records)
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
        "## 5. Behavior Summary",
        "",
        make_table(behavior_summary),
        "",
        "## 6. Network And Risk Summary",
        "",
        make_table(network_summary),
        "",
        "## 7. Map Summary",
        "",
        make_table(map_summary, floatfmt=".3f"),
        "",
        "## 8. Representative Samples",
        "",
    ]

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
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    database = RecordDatabase.from_dict(raw)
    report = generate_report(database.records)
    args.output.write_text(report, encoding="utf-8")
    print(f"Report written to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
