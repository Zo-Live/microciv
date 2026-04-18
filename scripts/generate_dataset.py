"""Generate a large labeled dataset for AI rule analysis."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from microciv.game.enums import MapDifficulty, PlaybackMode, PolicyType  # noqa: E402
from microciv.game.models import GameConfig  # noqa: E402
from microciv.records.models import CSV_FIELD_ORDER, RecordDatabase, RecordEntry  # noqa: E402
from microciv.session import create_game_session  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate large MicroCiv dataset.")
    parser.add_argument(
        "-n", "--games-per-combo", type=int, default=10, help="Games per parameter combo."
    )
    parser.add_argument(
        "--seed-start", type=int, default=1, help="Global starting seed offset."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "exports" / "dataset",
        help="Output directory.",
    )
    parser.add_argument(
        "--policies",
        type=str,
        default="greedy,random",
        help="Comma-separated policies.",
    )
    parser.add_argument(
        "--map-sizes",
        type=str,
        default="12,16,20,24",
        help="Comma-separated map sizes.",
    )
    parser.add_argument(
        "--turn-limits",
        type=str,
        default="30,80,150",
        help="Comma-separated turn limits.",
    )
    parser.add_argument(
        "--difficulties",
        type=str,
        default="normal,hard",
        help="Comma-separated difficulties.",
    )
    parser.add_argument(
        "--label",
        type=str,
        default="",
        help="Optional label appended to output filenames.",
    )
    return parser.parse_args()


def _policy_type(value: str) -> PolicyType:
    if value == "greedy":
        return PolicyType.GREEDY
    if value == "random":
        return PolicyType.RANDOM
    raise ValueError(value)


def _map_difficulty(value: str) -> MapDifficulty:
    if value == "normal":
        return MapDifficulty.NORMAL
    if value == "hard":
        return MapDifficulty.HARD
    raise ValueError(value)


def _parse_csv_values(raw: str, *, field_name: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if values:
        return values
    raise ValueError(f"{field_name} must contain at least one value.")


def run_game(
    *,
    seed: int,
    policy_type: PolicyType,
    map_size: int,
    turn_limit: int,
    map_difficulty: MapDifficulty,
) -> RecordEntry:
    config = GameConfig.for_autoplay(
        map_size=map_size,
        turn_limit=turn_limit,
        map_difficulty=map_difficulty,
        policy_type=policy_type,
        playback_mode=PlaybackMode.SPEED,
        seed=seed,
    )
    session = create_game_session(config)
    while not session.state.is_game_over:
        session.step_autoplay()

    timestamp = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    return RecordEntry.from_game_state(
        record_id=seed,
        timestamp=timestamp,
        state=session.state,
    )


def main() -> int:
    args = _parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    param_grid = {
        "policy": _parse_csv_values(args.policies, field_name="policies"),
        "map_size": [
            int(item) for item in _parse_csv_values(args.map_sizes, field_name="map_sizes")
        ],
        "turn_limit": [
            int(item) for item in _parse_csv_values(args.turn_limits, field_name="turn_limits")
        ],
        "map_difficulty": _parse_csv_values(args.difficulties, field_name="difficulties"),
    }
    combos = list(product(*param_grid.values()))
    total_games = len(combos) * args.games_per_combo
    records: list[RecordEntry] = []
    global_seed = args.seed_start
    run_tag = args.label.strip().replace(" ", "_")
    base_name = "dataset"
    if run_tag:
        base_name = f"{base_name}_{run_tag}"

    print(
        f"Dataset plan: {len(combos)} combos x {args.games_per_combo} games = "
        f"{total_games} total",
        file=sys.stderr,
    )
    batch_start = perf_counter()

    for combo_idx, (policy, map_size, turn_limit, difficulty) in enumerate(combos, start=1):
        combo_start = perf_counter()
        policy_type = _policy_type(policy)
        map_difficulty = _map_difficulty(difficulty)
        for _ in range(args.games_per_combo):
            record = run_game(
                seed=global_seed,
                policy_type=policy_type,
                map_size=map_size,
                turn_limit=turn_limit,
                map_difficulty=map_difficulty,
            )
            records.append(record)
            global_seed += 1
        combo_elapsed = perf_counter() - combo_start
        print(
            f"[{combo_idx}/{len(combos)}] {policy}/{map_size}/{turn_limit}/{difficulty} "
            f"done in {combo_elapsed:.2f}s",
            file=sys.stderr,
        )

    total_elapsed = perf_counter() - batch_start
    print(
        f"Dataset complete: {total_games} games in {total_elapsed:.2f}s "
        f"({total_elapsed/total_games:.3f}s per game)",
        file=sys.stderr,
    )

    database = RecordDatabase(records=records)

    json_path = output_dir / f"{base_name}.json"
    json_path.write_text(
        json.dumps(database.to_dict(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Dataset JSON exported: {json_path}", file=sys.stderr)

    csv_path = output_dir / f"{base_name}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_FIELD_ORDER))
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())
    print(f"Dataset CSV exported: {csv_path}", file=sys.stderr)

    manifest_path = output_dir / f"{base_name}_manifest.json"
    manifest = {
        "games_per_combo": args.games_per_combo,
        "seed_start": args.seed_start,
        "seed_end": global_seed - 1,
        "param_grid": param_grid,
        "combo_count": len(combos),
        "total_games": total_games,
        "total_elapsed_seconds": round(total_elapsed, 3),
        "avg_elapsed_seconds": round(total_elapsed / total_games, 3),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Dataset manifest exported: {manifest_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
