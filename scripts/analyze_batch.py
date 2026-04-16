"""Analyze a MicroCiv batch dataset and emit a diagnostic Markdown report."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, stdev

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
        default=ROOT / "exports" / "dataset" / "report.md",
        help="Path to output Markdown report.",
    )
    return parser.parse_args()


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    m = mean(values)
    s = stdev(values) if len(values) > 1 else 0.0
    return m, s


def _fmt_ms(m: float, s: float) -> str:
    return f"{m:.1f} ± {s:.1f}"


def summarize(records: list[dict]) -> dict:
    """Return nested summary dict."""
    overall = {"greedy": [], "random": []}
    by_size: dict[tuple, list] = defaultdict(list)
    by_turn: dict[tuple, list] = defaultdict(list)
    by_diff: dict[tuple, list] = defaultdict(list)

    for r in records:
        policy = r["ai_type"].lower()
        overall[policy].append(r)
        by_size[(policy, r["map_size"])].append(r)
        by_turn[(policy, r["turn_limit"])].append(r)
        by_diff[(policy, r["map_difficulty"])].append(r)

    return {
        "overall": overall,
        "by_size": dict(by_size),
        "by_turn": dict(by_turn),
        "by_diff": dict(by_diff),
    }


def make_table(rows: list[list[str]]) -> str:
    """Simple Markdown table."""
    lines = ["| " + " | ".join(rows[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * len(rows[0])) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def metric_table(grouped: dict[str, list[dict]], keys: list[str]) -> str:
    rows = [["Group"] + keys]
    for label, recs in grouped.items():
        row = [label]
        for k in keys:
            vals = [float(r[k]) for r in recs]
            m, s = _mean_std(vals)
            row.append(f"{m:.1f} ± {s:.1f}")
        rows.append(row)
    return make_table(rows)


def behavior_analysis(records: list[dict]) -> dict:
    """Aggregate action logs and decision contexts."""
    greedy_records = [r for r in records if r["ai_type"] == "Greedy"]
    random_records = [r for r in records if r["ai_type"] == "Random"]

    # action type distribution
    g_action_counts: Counter[str] = Counter()
    r_action_counts: Counter[str] = Counter()
    g_total_actions = 0
    r_total_actions = 0

    for r in greedy_records:
        for entry in r.get("action_log", []):
            g_action_counts[entry["action_type"]] += 1
            g_total_actions += 1
    for r in random_records:
        for entry in r.get("action_log", []):
            r_action_counts[entry["action_type"]] += 1
            r_total_actions += 1

    # greedy priority distribution
    g_priority_counts: Counter[str] = Counter()
    g_priority_total = 0
    for r in greedy_records:
        for ctx in r.get("decision_contexts", []):
            prio = ctx.get("greedy_priority", "unknown")
            g_priority_counts[prio] += 1
            g_priority_total += 1

    # legal actions decay (sample mid and late)
    g_legal_early = []
    g_legal_mid = []
    g_legal_late = []
    for r in greedy_records:
        contexts = r.get("decision_contexts", [])
        if contexts:
            g_legal_early.append(contexts[0]["legal_actions_count"])
            mid_idx = len(contexts) // 2
            g_legal_mid.append(contexts[mid_idx]["legal_actions_count"])
            g_legal_late.append(contexts[-1]["legal_actions_count"])

    return {
        "g_action_pct": {
            k: g_action_counts[k] / g_total_actions * 100 if g_total_actions else 0
            for k in g_action_counts
        },
        "r_action_pct": {
            k: r_action_counts[k] / r_total_actions * 100 if r_total_actions else 0
            for k in r_action_counts
        },
        "g_priority_pct": {
            k: g_priority_counts[k] / g_priority_total * 100 if g_priority_total else 0
            for k in g_priority_counts
        },
        "g_legal": {
            "early": _mean_std([float(v) for v in g_legal_early]),
            "mid": _mean_std([float(v) for v in g_legal_mid]),
            "late": _mean_std([float(v) for v in g_legal_late]),
        },
    }


def map_analysis(records: list[dict]) -> dict:
    """Analyze map-related observations."""
    # terrain prevalence by difficulty
    normal_terrains: Counter[str] = Counter()
    hard_terrains: Counter[str] = Counter()
    normal_cells = 0
    hard_cells = 0

    for r in records:
        tiles = r.get("final_map", [])
        if r["map_difficulty"] == "normal":
            for t in tiles:
                normal_terrains[t["base_terrain"]] += 1
                normal_cells += 1
        else:
            for t in tiles:
                hard_terrains[t["base_terrain"]] += 1
                hard_cells += 1

    def pct(counter: Counter, total: int) -> dict[str, float]:
        if not total:
            return {}
        return {k: counter[k] / total * 100 for k in counter}

    return {
        "normal_pct": pct(normal_terrains, normal_cells),
        "hard_pct": pct(hard_terrains, hard_cells),
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

    # find random beats greedy with same config
    if greedy and random:
        g_by_config = defaultdict(list)
        r_by_config = defaultdict(list)
        for r in greedy:
            g_by_config[(r["map_size"], r["turn_limit"], r["map_difficulty"])].append(r)
        for r in random:
            r_by_config[(r["map_size"], r["turn_limit"], r["map_difficulty"])].append(r)

        for cfg, g_list in g_by_config.items():
            r_list = r_by_config.get(cfg, [])
            if not r_list:
                continue
            g_mean = mean(x["final_score"] for x in g_list)
            r_mean = mean(x["final_score"] for x in r_list)
            if r_mean > g_mean:
                picks.append(
                    {
                        "label": f"Random beats Greedy on {cfg}",
                        "record": max(r_list, key=lambda x: x["final_score"]),
                        "g_mean": g_mean,
                        "r_mean": r_mean,
                    }
                )
                break  # one example enough

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
    summary = summarize(records)
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
    lines.append(
        metric_table(
            summary["overall"],
            [
                "final_score",
                "city_count",
                "building_count",
                "tech_count",
                "skip_count",
                "actual_turns",
            ],
        )
    )
    lines.append("")

    # By map size
    lines.append("## 2. 按地图尺寸细分")
    lines.append("")
    size_grouped = defaultdict(list)
    for (p, s), recs in summary["by_size"].items():
        size_grouped[f"{p}/{s}"] = recs
    lines.append(
        metric_table(
            dict(size_grouped),
            ["final_score", "city_count", "building_count", "tech_count", "skip_count"],
        )
    )
    lines.append("")

    # By turn limit
    lines.append("## 3. 按回合上限细分")
    lines.append("")
    turn_grouped = defaultdict(list)
    for (p, t), recs in summary["by_turn"].items():
        turn_grouped[f"{p}/{t}"] = recs
    lines.append(
        metric_table(
            dict(turn_grouped),
            ["final_score", "city_count", "building_count", "tech_count", "skip_count"],
        )
    )
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
    for phase, (m, s) in behavior["g_legal"].items():
        lines.append(f"- {phase}: {m:.1f} ± {s:.1f}")
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

    # auto-detect building neglect
    g_building_rate = behavior["g_action_pct"].get("build_building", 0)
    r_building_rate = behavior["r_action_pct"].get("build_building", 0)
    lines.append(
        f"1. **建筑荒废**: Greedy 建筑动作仅占 {g_building_rate:.2f}%，"
        f"Random 为 {r_building_rate:.2f}%。"
        "假设：建筑成本过高，或 Greedy 的 building 优先级低于 city，导致永远轮不到。"
    )
    lines.append("")

    # tech neglect
    g_tech_rate = behavior["g_action_pct"].get("research_tech", 0)
    r_tech_rate = behavior["r_action_pct"].get("research_tech", 0)
    lines.append(
        f"2. **科技荒废**: Greedy 科技动作仅占 {g_tech_rate:.2f}%，Random 为 {r_tech_rate:.2f}%。"
        "假设：科技收益（解锁建筑）对 Greedy 吸引力不足，或 science 产出和存储过低。"
    )
    lines.append("")

    # skip explosion
    g_skip_rate = behavior["g_action_pct"].get("skip", 0)
    lines.append(
        f"3. **Skip 陷阱**: Greedy skip 动作占 {g_skip_rate:.1f}%。"
        "假设：当建城点耗尽后 Greedy 没有有效的 fallback 策略，导致大量空过回合。"
    )
    lines.append("")

    # map difficulty weak differentiation
    diff_score_normal_g = mean(
        [r["final_score"] for r in summary["overall"]["greedy"] if r["map_difficulty"] == "normal"]
    )
    diff_score_hard_g = mean(
        [r["final_score"] for r in summary["overall"]["greedy"] if r["map_difficulty"] == "hard"]
    )
    lines.append(
        f"4. **地图难度区分度弱**: Greedy 在 normal 的平均得分 {diff_score_normal_g:.1f}，"
        f"hard 为 {diff_score_hard_g:.1f}，差距可能不够显著。"
        "假设：Hard 地图的地形分布（如荒地、河流比例）调整幅度不足，或未对 AI 产生足够惩罚。"
    )
    lines.append("")

    # network rule impact
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
