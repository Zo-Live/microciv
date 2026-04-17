# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

MicroCiv is a terminal-based, turn-based civilization simulator built with Python 3.13+ and curses. It features square-grid procedural maps, city/road/building construction, tech research, resource management, and two AI policies (Greedy, Random). Records are persisted as JSON with CSV export.

## Commands

```bash
# Run the game
python main.py
python -m microciv

# Batch AI data collection
python scripts/batch_autoplay.py -n <games> --policy <policy>

# Large-scale param-grid dataset generation
python scripts/generate_dataset.py -n <games-per-combo>

# Generate diagnostic Markdown report from dataset (requires pandas + tabulate)
python scripts/analyze_batch.py --input <dataset.json> --output <report.md>

# Tests
python -m pytest -q                                  # all tests
python -m pytest tests/<module>.py -q                # single module
python -m pytest tests/<module>.py::<test_name> -q  # single test

# Lint
ruff check src tests

# Type check
mypy
```

Install with `uv sync` (preferred) or `pip install -e ".[dev]"`.

## Architecture

**Game loop**: `GameConfig` -> `session.create_game_session()` -> `GameSession` (holds `GameState` + `GameEngine` + optional `Policy`) -> per-turn `apply_action()` cycle.

**Core layers**:

- `game/models.py` — All state dataclasses: `GameState`, `Tile`, `City`, `Road`, `Network`, `ResourcePool`, `BuildingCounts`, `GameConfig`, `Stats`. Board is `dict[Coord, Tile]` where `Coord = tuple[int, int]`. Cities, roads, networks keyed by integer ID.
- `game/engine.py` — `GameEngine.apply_action()` validates, mutates state, recomputes networks/resources/score, advances turn. Returns `EngineResult`.
- `game/actions.py` — `Action` (frozen dataclass with classmethods `build_city`, `build_road`, `build_building`, `research_tech`, `skip`), `validate_action()`, `list_legal_actions()`.
- `game/enums.py` — All enums are `StrEnum`: `TerrainType`, `OccupantType`, `ResourceType`, `BuildingType`, `TechType`, `ActionType`, `Mode`, `PolicyType`, `PlaybackMode`, `MapDifficulty`.
- `game/networks.py` — Road/city connectivity via union-find. `recompute_networks()` merges networks when roads connect cities.
- `game/resources.py` — Per-turn resource settlement (terrain yields + building yields - food consumption). `settle_resources()` is called after every action.
- `game/mapgen.py` — Procedural map generation with terrain distribution.
- `game/scoring.py` — Score calculation from cities, buildings, techs, and resources.
- `constants.py` — All balance tuning: costs, yields, weights, limits.

**AI system**: Protocol-based in `ai/policy.py`. `Policy.select_action(state) -> Action`. Two implementations:
- `GreedyPolicy` — deterministic rule-based (food rescue -> buildings -> tech -> cities -> roads).
- `RandomPolicy` — stochastic baseline with seeded RNG.
- `simulate_action()` deep-copies state for lookahead.

**Persistence**: `records/models.py` defines `RecordEntry` and snapshot dataclasses (`RecordTileSnapshot`, `RecordCitySnapshot`, etc.) with `from_dict`/`to_dict` round-trip serialization. `records/store.py` handles JSON file I/O. `records/export.py` handles CSV export.

**Batch runners**: 
- `scripts/batch_autoplay.py` runs headless autoplay games in bulk and exports results as JSON and CSV.
- `scripts/generate_dataset.py` sweeps a parameter grid (policy × map_size × turn_limit × difficulty) to build a large labeled dataset.
- `scripts/analyze_batch.py` consumes the dataset JSON and emits a diagnostic Markdown report with aggregated metrics, behavior patterns, and actionable hypotheses.
Both runners use `create_game_session()` and `GameSession.step_autoplay()` to advance turns without the curses UI.

**UI**: `curses_app.py` is the main curses controller with mouse-driven interaction. `tui/` contains UI component helpers.

**Utilities**: `utils/grid.py` has `Coord` type alias, `cardinal_neighbors()`, `moore_neighbors()`, `coord_sort_key()`. `utils/rng.py` wraps seeded random.

## Key Patterns

- Dataclasses use `slots=True` throughout; frozen for immutable value objects (`Action`, record snapshots).
- All enums are `StrEnum` for JSON serialization.
- `from __future__ import annotations` in every module.
- Game state is mutable; AI simulation uses `deepcopy` to avoid side effects.
- Coordinates are `tuple[int, int]` (row, col), sorted by `coord_sort_key` for deterministic ordering.
- Network merging: when roads connect separate city networks, `recompute_networks()` union-finds and calls `Network.merge_from()`.
- Resource settlement runs after every action, not just at end of turn.

## Ruff Config

Line length 100, target Python 3.13, rules: B (bugbear), E (pycodestyle errors), F (pyflakes), I (isort), UP (pyupgrade).

## 请使用中文回答所有问题和交流

与用户的所有互动都应该使用中文，包括代码解释、错误消息和建议
