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

from microciv.records.models import RecordDatabase  # noqa: E402


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
    return df.to_markdown(floatfmt=floatfmt)


def build_macro_df(records: list[dict]) -> pd.DataFrame:
    """Build DataFrame of top-level record fields."""
    rows = []
    for r in records:
        rows.append(
            {
                "ai_type": r["ai_type"],
                "map_size": r["map_size"],
                "turn_limit": r["turn_limit"],
                "map_difficulty": r["map_difficulty"],
                "final_score": r["final_score"],
                "city_count": r["city_count"],
                "building_count": r["building_count"],
                "tech_count": r["tech_count"],
                "skip_count": r["skip_count"],
                "actual_turns": r["actual_turns"],
            }
        )
    return pd.DataFrame(rows)


def behavior_analysis(records: list[dict]) -> dict:
    """Aggregate action logs and decision contexts."""
    greedy_records = [r for r in records if r["ai_type"] == "Greedy"]
    random_records = [r for r in records if r["ai_type"] == "Random"]

    # action type distribution
    g_actions = Counter()
    r_actions = Counter()
    for r in greedy_records:
        g_actions.update(entry["action_type"] for entry in r.get("action_log", []))
    for r in random_records:
        r_actions.update(entry["action_type"] for entry in r.get("action_log", []))

    g_total = sum(g_actions.values())
    r_total = sum(r_actions.values())

    # greedy priority distribution
    g_priorities = Counter()
    for r in greedy_records:
        g_priorities.update(
            ctx.get("greedy_priority", "unknown")
            for ctx in r.get("decision_contexts", [])
        )
    p_total = sum(g_priorities.values())

    # legal actions decay
    g_legal = []
    for r in greedy_records:
        contexts = r.get("decision_contexts", [])
        if contexts:
            g_legal.append(
                {
                    "phase": "early",
                    "legal_actions_count": contexts[0]["legal_actions_count"],
                }
            )
            g_legal.append(
                {
                    "phase": "mid",
                    "legal_actions_count": contexts[len(contexts) // 2][
                        "legal_actions_count"
                    ],
                }
            )
            g_legal.append(
                {
                    "phase": "late",
                    "legal_actions_count": contexts[-1]["legal_actions_count"],
                }
            )
    legal_df = pd.DataFrame(g_legal)
    legal_stats = (
        legal_df.groupby("phase")["legal_actions_count"].agg(["mean", "std"]).to_dict("index")
        if not legal_df.empty
        else {}
    )

    return {
        "g_action_pct": {
            k: v / g_total * 100 for k, v in g_actions.items()
        },
        "r_action_pct": {
            k: v / r_total * 100 for k, v in r_actions.items()
        },
        "g_priority_pct": {
            k: v / p_total * 100 for k, v in g_priorities.items()
        },
        "g_legal": legal_stats,
    }


def map_analysis(records: list[dict]) -> dict:
    """Analyze map-related observations using pandas."""
    tiles = []
    for r in records:
        difficulty = r["map_difficulty"]
        for t in r.get("final_map", []):
            tiles.append({"difficulty": difficulty, "terrain": t["base_terrain"]})
    df = pd.DataFrame(tiles)
    if df.empty:
        return {"normal_pct": {}, "hard_pct": {}}

    total_by_diff = df.groupby("difficulty").size()
    counts = df.groupby(["difficulty", "terrain"]).size().unstack(fill_value=0)
    pct = counts.div(total_by_diff, axis=0) * 100

    return {
        "normal_pct": pct.loc["normal"].to_dict() if "normal" in pct.index else {},
        "hard_pct": pct.loc["hard"].to_dict() if "hard" in pct.index else {},
    }


def anomalies(records: list[dict]) -> list[dict]:
    """Pick representative outlier games."""
    greedy = [r for r in records if r["ai_type"] == "Greedy"]
    random = [r for r in records if r["ai_type"] == "Random"]
    picks = []

    if greedy:
        best = max(greedy, key=lambda r: r["final_score"])
        worst = min(greedy, key=lambda r: r["final_score"])
        picks.append({"label": "Greedy highest score", "record": best})
        picks.append({"label": "Greedy lowest score", "record": worst})

    if random:
        best_r = max(random, key=lambda r: r["final_score"])
        picks.append({"label": "Random highest score", "record": best_r})

    # random beats greedy same config
    if greedy and random:
        df_g = build_macro_df(greedy)
        df_r = build_macro_df(random)
        g_mean = (
            df_g.groupby(["map_size", "turn_limit", "map_difficulty"])
            ["final_score"]
            .mean()
            .reset_index()
            .rename(columns={"final_score": "g_mean"})
        )
        r_mean = (
            df_r.groupby(["map_size", "turn_limit", "map_difficulty"])
            ["final_score"]
            .mean()
            .reset_index()
            .rename(columns={"final_score": "r_mean"})
        )
        merged = pd.merge(g_mean, r_mean, on=["map_size", "turn_limit", "map_difficulty"])
        merged = merged[merged["r_mean"] > merged["g_mean"]]
        if not merged.empty:
            row = merged.iloc[0]
            cfg = (int(row["map_size"]), int(row["turn_limit"]), str(row["map_difficulty"]))
            r_candidates = [
                r for r in random
                if (r["map_size"], r["turn_limit"], r["map_difficulty"]) == cfg
            ]
            if r_candidates:
                best_c = max(r_candidates, key=lambda r: r["final_score"])
                picks.append(
                    {
                        "label": f"Random beats Greedy on {cfg}",
                        "record": best_c,
                        "g_mean": float(row["g_mean"]),
                        "r_mean": float(row["r_mean"]),
                    }
                )
    return picks


def _clip_turn_log(record: dict, max_turns: int = 20) -> str:
    """Render first N turn actions and contexts."""
    actions = record.get("action_log", [])[:max_turns]
    contexts = record.get("decision_contexts", [])[:max_turns]
    lines = []
    for i, a in enumerate(actions):
        ctx = contexts[i] if i < len(contexts) else {}
        prio = ctx.get("greedy_priority", "-")
        legal = ctx.get("legal_actions_count", "-")
        coord = f"({a.get('x','-')},{a.get('y','-')})" if a.get("x") is not None else "-"
        lines.append(
            f"  T{a['turn']:>3} | {a['action_type']:18} | coord={coord:8} | "
            f"legal={legal:4} | priority={prio}"
        )
    return "\n".join(lines)


def generate_report(records: list[dict]) -> str:
    df = build_macro_df(records)
    behavior = behavior_analysis(records)
    map_stats = map_analysis(records)
    outlier_games = anomalies(records)

    lines = []
    lines.append("# MicroCiv AI 诊断报告")
    lines.append("")
    lines.append(f"**数据集规模**: {len(records)} 局")
    lines.append("")

    # Overall comparison
    lines.append("## 1. 宏观指标对比 (Greedy vs Random)")
    lines.append("")
    overall = (
        df.groupby("ai_type")
        .agg({
            "final_score": ["mean", "std"],
            "city_count": ["mean", "std"],
            "building_count": ["mean", "std"],
            "tech_count": ["mean", "std"],
            "skip_count": ["mean", "std"],
            "actual_turns": ["mean", "std"],
        })
        .transpose()
    )
    overall.columns = [f"{c[0]} ({c[1]})" for c in overall.columns]
    overall = overall.reset_index()
    overall.columns = ["指标"] + list(overall.columns[1:])
    lines.append(make_table(overall))
    lines.append("")

    # By map size
    lines.append("## 2. 按地图尺寸细分")
    lines.append("")
    size_df = (
        df.groupby(["ai_type", "map_size"])
        .agg(
            final_score=("final_score", "mean"),
            city_count=("city_count", "mean"),
            building_count=("building_count", "mean"),
            tech_count=("tech_count", "mean"),
            skip_count=("skip_count", "mean"),
        )
        .reset_index()
    )
    size_df["group"] = size_df["ai_type"] + "/" + size_df["map_size"].astype(str)
    size_df = size_df[
        ["group", "final_score", "city_count", "building_count", "tech_count", "skip_count"]
    ]
    lines.append(make_table(size_df))
    lines.append("")

    # By turn limit
    lines.append("## 3. 按回合上限细分")
    lines.append("")
    turn_df = (
        df.groupby(["ai_type", "turn_limit"])
        .agg(
            final_score=("final_score", "mean"),
            city_count=("city_count", "mean"),
            building_count=("building_count", "mean"),
            tech_count=("tech_count", "mean"),
            skip_count=("skip_count", "mean"),
        )
        .reset_index()
    )
    turn_df["group"] = turn_df["ai_type"] + "/" + turn_df["turn_limit"].astype(str)
    turn_df = turn_df[
        ["group", "final_score", "city_count", "building_count", "tech_count", "skip_count"]
    ]
    lines.append(make_table(turn_df))
    lines.append("")

    # Behavior patterns
    lines.append("## 4. 行为模式分析")
    lines.append("")
    lines.append("### 4.1 动作类型占比")
    lines.append("")
    lines.append("**Greedy**:")
    for k, v in sorted(behavior["g_action_pct"].items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {v:.1f}%")
    lines.append("")
    lines.append("**Random**:")
    for k, v in sorted(behavior["r_action_pct"].items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {v:.1f}%")
    lines.append("")

    lines.append("### 4.2 Greedy 优先级分布")
    lines.append("")
    for k, v in sorted(behavior["g_priority_pct"].items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {v:.1f}%")
    lines.append("")

    lines.append("### 4.3 合法动作数衰减 (Greedy)")
    lines.append("")
    for phase in ["early", "mid", "late"]:
        stats = behavior["g_legal"].get(phase, {})
        if stats:
            lines.append(f"- {phase}: {stats['mean']:.1f} ± {stats['std']:.1f}")
    lines.append("")

    # Map analysis
    lines.append("## 5. 地图地形分布 (Normal vs Hard)")
    lines.append("")
    lines.append("**Normal**:")
    for k, v in sorted(map_stats["normal_pct"].items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {v:.1f}%")
    lines.append("")
    lines.append("**Hard**:")
    for k, v in sorted(map_stats["hard_pct"].items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {v:.1f}%")
    lines.append("")

    # Anomalies
    lines.append("## 6. 异常典型案例")
    lines.append("")
    for item in outlier_games:
        r = item["record"]
        lines.append(f"### {item['label']}")
        if "g_mean" in item:
            lines.append(f"- Greedy mean={item['g_mean']:.1f}, Random mean={item['r_mean']:.1f}")
        lines.append(
            f"- score={r['final_score']}, cities={r['city_count']}, "
            f"buildings={r['building_count']}, techs={r['tech_count']}, "
            f"skips={r['skip_count']}, "
            f"config={r['map_size']}/{r['turn_limit']}/{r['map_difficulty']}"
        )
        lines.append("- 前 20 回合动作日志:")
        lines.append("```")
        lines.append(_clip_turn_log(r))
        lines.append("```")
        lines.append("")

    # Hypotheses
    lines.append("## 7. 自动检测到的可疑模式与诊断假设")
    lines.append("")

    g_building_rate = behavior["g_action_pct"].get("build_building", 0)
    r_building_rate = behavior["r_action_pct"].get("build_building", 0)
    lines.append(
        f"1. **建筑荒废**: Greedy 建筑动作仅占 {g_building_rate:.2f}%，"
        f"Random 为 {r_building_rate:.2f}%。"
        "假设：建筑成本过高，或 Greedy 的 building 优先级低于 city，导致永远轮不到。"
    )
    lines.append("")

    g_tech_rate = behavior["g_action_pct"].get("research_tech", 0)
    r_tech_rate = behavior["r_action_pct"].get("research_tech", 0)
    lines.append(
        f"2. **科技荒废**: Greedy 科技动作仅占 {g_tech_rate:.2f}%，"
        f"Random 为 {r_tech_rate:.2f}%。"
        "假设：科技收益（解锁建筑）对 Greedy 吸引力不足，或 science 产出和存储过低。"
    )
    lines.append("")

    g_skip_rate = behavior["g_action_pct"].get("skip", 0)
    lines.append(
        f"3. **Skip 陷阱**: Greedy skip 动作占 {g_skip_rate:.1f}%。"
        "假设：当建城点耗尽后 Greedy 没有有效的 fallback 策略，导致大量空过回合。"
    )
    lines.append("")

    diff_g = df[df["ai_type"] == "Greedy"]
    diff_score_normal = diff_g[diff_g["map_difficulty"] == "normal"]["final_score"].mean()
    diff_score_hard = diff_g[diff_g["map_difficulty"] == "hard"]["final_score"].mean()
    lines.append(
        f"4. **地图难度区分度弱**: Greedy 在 normal 的平均得分 {diff_score_normal:.1f}，"
        f"hard 为 {diff_score_hard:.1f}，差距可能不够显著。"
        "假设：Hard 地图的地形分布（如荒地、河流比例）调整幅度不足，或未对 AI 产生足够惩罚。"
    )
    lines.append("")

    lines.append(
        "5. **网络规则后遗症**: 相邻城市不再连通后，"
        "Greedy 的 `_city_action_key` 中仍有 'connection_bonus' 评分项，"
        "但该 bonus 在新规则下已无法通过邻接城市获得，导致选址逻辑与实际连通性脱节。"
    )
    lines.append("")

    lines.append("---")
    lines.append("*报告由 analyze_batch.py 自动生成*")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    database = RecordDatabase.from_dict(raw)
    records = [r.to_dict() for r in database.records]

    report = generate_report(records)
    args.output.write_text(report, encoding="utf-8")
    print(f"Report written to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
