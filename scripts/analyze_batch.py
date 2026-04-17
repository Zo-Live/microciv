"""Analyze a MicroCiv batch dataset and emit a diagnostic Markdown report."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from microciv.constants import APP_NAME  # noqa: E402
from microciv.game.enums import TechType  # noqa: E402
from microciv.game.models import (  # noqa: E402
    BuildingCounts,
    City,
    GameConfig,
    GameState,
    Network,
    ResourcePool,
)
from microciv.game.scoring import score_breakdown  # noqa: E402
from microciv.records.models import RecordDatabase, RecordEntry  # noqa: E402


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
    """Render a pandas DataFrame as a Markdown table."""
    return df.to_markdown(index=False, floatfmt=floatfmt)


def build_macro_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows = []
    for record in records:
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
            }
        )
    return pd.DataFrame(rows)


def build_score_breakdown_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows = []
    for record in records:
        breakdown = score_breakdown(record_to_state(record))
        rows.append(
            {
                "ai_type": record.ai_type,
                "city_score": breakdown.city_score,
                "connected_city_score": breakdown.connected_city_score,
                "resource_ring_score": breakdown.resource_ring_score,
                "building_score": breakdown.building_score,
                "tech_score": breakdown.tech_score,
                "tech_utilization_score": breakdown.tech_utilization_score,
                "resource_score": breakdown.resource_score,
                "starving_penalty": breakdown.starving_network_penalty,
                "fragmentation_penalty": breakdown.fragmented_network_penalty,
                "total_score": breakdown.total,
            }
        )
    return pd.DataFrame(rows)


def build_behavior_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows = []
    for record in records:
        action_counts = Counter(entry.action_type for entry in record.action_log)
        total_actions = sum(action_counts.values()) or 1
        legal_denominator = sum(ctx.legal_actions_count for ctx in record.decision_contexts) or 1
        rows.append(
            {
                "ai_type": record.ai_type,
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
            }
        )
    return pd.DataFrame(rows)


def build_network_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows = []
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
        road_city_ratio = len(record.roads) / max(record.city_count, 1)
        rows.append(
            {
                "ai_type": record.ai_type,
                "connected_cities": connected_cities,
                "isolated_cities": isolated_cities,
                "largest_network_size": largest_network_size,
                "network_count": len(record.networks),
                "road_city_ratio": road_city_ratio,
            }
        )
    return pd.DataFrame(rows)


def build_map_df(records: list[RecordEntry]) -> pd.DataFrame:
    rows = []
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


def automatic_observations(
    macro_df: pd.DataFrame,
    score_df: pd.DataFrame,
    behavior_df: pd.DataFrame,
    network_df: pd.DataFrame,
    map_df: pd.DataFrame,
) -> list[str]:
    observations: list[str] = []

    macro_mean = macro_df.groupby("ai_type").mean(numeric_only=True)
    behavior_mean = behavior_df.groupby("ai_type").mean(numeric_only=True)
    map_mean = map_df.groupby("map_difficulty").mean(numeric_only=True)
    score_mean = score_df.groupby("ai_type").mean(numeric_only=True)

    if {"Greedy", "Random"} <= set(macro_mean.index):
        greedy_food = macro_mean.loc["Greedy", "food"]
        random_food = macro_mean.loc["Random", "food"]
        if greedy_food > random_food:
            observations.append(
                f"`Greedy` 的终局粮食均值高于 `Random`（{greedy_food:.1f} vs {random_food:.1f}），"
                "说明一层前瞻已经显著改善了生存性。"
            )

        greedy_building = behavior_mean.loc["Greedy", "chosen_building_pct"]
        random_city = behavior_mean.loc["Random", "chosen_city_pct"]
        if greedy_building >= 15:
            observations.append(
                f"`Greedy` 的建筑动作占比达到 {greedy_building:.1f}% ，"
                "建城不再垄断策略空间。"
            )
        if random_city < 50:
            observations.append(
                f"`Random` 的建城动作占比降到 {random_city:.1f}% ，"
                "带权随机已经压制了“海量合法建城动作”的偏置。"
            )

        greedy_fragment = score_mean.loc["Greedy", "fragmentation_penalty"]
        random_fragment = score_mean.loc["Random", "fragmentation_penalty"]
        if greedy_fragment < random_fragment:
            observations.append(
                f"`Greedy` 的碎片化惩罚均值更低（{greedy_fragment:.1f} vs {random_fragment:.1f}），"
                "修路与并网行为正在转化成稳定收益。"
            )

    if {"normal", "hard"} <= set(map_mean.index):
        build_gap = (
            map_mean.loc["normal", "buildable_ratio"]
            - map_mean.loc["hard", "buildable_ratio"]
        )
        if build_gap > 0.03:
            observations.append(
                f"`Hard` 地图的平均可建设比例比 `Normal` 低 {build_gap:.3f}，"
                "难度差异已经不再只体现在荒地数量。"
            )
        turn_ratio = map_mean.loc["normal", "river_turn_ratio"]
        if turn_ratio > 0.3:
            observations.append(
                f"平均河流转折率达到 {turn_ratio:.3f}，河流形态已经脱离原先的近似直线。"
            )

    legal_vs_chosen = behavior_mean[["chosen_building_pct", "legal_building_pct"]].copy()
    for ai_type, row in legal_vs_chosen.iterrows():
        gap = row["legal_building_pct"] - row["chosen_building_pct"]
        if gap > 10:
            observations.append(
                f"`{ai_type}` 仍存在建筑机会未充分利用的现象："
                f"合法占比比实际选择高 {gap:.1f} 个百分点。"
            )

    if not observations:
        observations.append("当前数据没有出现明显单点瓶颈，建议继续扩大种子规模再观察。")
    return observations


def anomalies(records: list[RecordEntry]) -> list[dict[str, object]]:
    greedy = [record for record in records if record.ai_type == "Greedy"]
    random = [record for record in records if record.ai_type == "Random"]
    picks: list[dict[str, object]] = []

    if greedy:
        picks.append(
            {
                "label": "Greedy highest score",
                "record": max(greedy, key=lambda r: r.final_score),
            }
        )
        picks.append(
            {
                "label": "Greedy lowest score",
                "record": min(greedy, key=lambda r: r.final_score),
            }
        )
    if random:
        picks.append(
            {
                "label": "Random highest score",
                "record": max(random, key=lambda r: r.final_score),
            }
        )
    return picks


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
    state = GameState.empty(
        GameConfig.for_play(
            map_size=record.map_size,
            turn_limit=record.turn_limit,
            seed=record.seed,
        )
    )
    state.turn = max(record.actual_turns, 1)
    state.score = record.final_score
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


def generate_report(records: list[RecordEntry]) -> str:
    macro_df = build_macro_df(records)
    score_df = build_score_breakdown_df(records)
    behavior_df = build_behavior_df(records)
    network_df = build_network_df(records)
    map_df = build_map_df(records)
    outlier_games = anomalies(records)
    observations = automatic_observations(macro_df, score_df, behavior_df, network_df, map_df)

    lines = []
    lines.append(f"# {APP_NAME} AI 诊断报告")
    lines.append("")
    lines.append(f"**数据集规模**: {len(records)} 局")
    lines.append("")

    lines.append("## 1. 宏观结果")
    lines.append("")
    overall = (
        macro_df.groupby("ai_type")
        .agg(
            final_score=("final_score", "mean"),
            city_count=("city_count", "mean"),
            road_count=("road_count", "mean"),
            building_count=("building_count", "mean"),
            tech_count=("tech_count", "mean"),
            food=("food", "mean"),
            starving_network_count=("starving_network_count", "mean"),
        )
        .reset_index()
    )
    lines.append(make_table(overall))
    lines.append("")

    lines.append("## 2. 评分拆解")
    lines.append("")
    score_table = (
        score_df.groupby("ai_type")
        .mean(numeric_only=True)
        .reset_index()
    )
    lines.append(make_table(score_table))
    lines.append("")

    lines.append("## 3. 行为与动作空间")
    lines.append("")
    behavior_table = (
        behavior_df.groupby("ai_type")
        .mean(numeric_only=True)
        .reset_index()
    )
    lines.append(make_table(behavior_table))
    lines.append("")

    lines.append("## 4. 网络与粮食健康")
    lines.append("")
    network_table = (
        macro_df.groupby("ai_type")
        .agg(
            first_negative_food_turn=("first_negative_food_turn", "mean"),
            network_count=("network_count", "mean"),
            starving_network_count=("starving_network_count", "mean"),
        )
        .reset_index()
        .merge(
            network_df.groupby("ai_type").mean(numeric_only=True).reset_index(),
            on="ai_type",
            how="left",
        )
    )
    lines.append(make_table(network_table))
    lines.append("")

    lines.append("## 5. 地图结构诊断")
    lines.append("")
    map_table = (
        map_df.groupby("map_difficulty")
        .mean(numeric_only=True)
        .reset_index()
    )
    lines.append(make_table(map_table, floatfmt=".3f"))
    lines.append("")

    lines.append("## 6. 自动观察")
    lines.append("")
    for item in observations:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## 7. 代表性样本")
    lines.append("")
    for item in outlier_games:
        record = item["record"]
        assert isinstance(record, RecordEntry)
        lines.append(f"### {item['label']}")
        lines.append(
            f"- score={record.final_score}, cities={record.city_count}, roads={len(record.roads)}, "
            f"buildings={record.building_count}, techs={record.tech_count}, "
            f"food={record.food}, "
            f"config={record.map_size}/{record.turn_limit}/{record.map_difficulty}"
        )
        lines.append("- 前 20 回合动作日志:")
        lines.append("```")
        lines.append(render_turn_log(record))
        lines.append("```")
        lines.append("")

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
