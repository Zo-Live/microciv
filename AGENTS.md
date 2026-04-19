# MicroCiv Project Guide

This file is for AI programming assistants to quickly understand and modify the project. It assumes zero prior knowledge.

---

## Project Overview

**MicroCiv** is a terminal-based, turn-based miniature civilization simulator built with Python 3.13+ and the standard library `curses`. It uses a square-grid map, supports mouse-first curses interaction, and renders tiles with Unicode block characters (2×4 pixel blocks).

Main features:

- Procedural random map generation (plains, forests, mountains, rivers, wasteland)
- City construction, road networks, building construction, tech research, and scoring system
- Manual play (Play) and automatic demo (Autoplay) modes
- Two AI strategies: `Greedy` and `Random`
- Local Records system with JSON persistence and export
- Pixel font rendering (title, score, turn count)

The core game has **zero** runtime dependencies — it uses only the Python standard library (`curses`). `pandas` and `tabulate` are provided through the optional `analysis` extras, and are only needed by `scripts/analyze_batch.py` for dataset diagnostics.

---

## Tech Stack

- **Language**: Python >= 3.13
- **UI Framework**: Standard library `curses` (mouse events, color pairs, Unicode block rendering)
- **Package Manager**: `uv` (recommended), `pip` also supported
- **Build Backend**: `hatchling`
- **Linting**: `ruff` (lint + format), `mypy` (type checking)
- **Test Framework**: `pytest` + `pytest-cov`
- **No CI/CD, no Makefile, no Docker**

---

## Installation & Run

### Using uv (recommended)

```bash
uv venv
uv sync
python main.py
```

### Using pip

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python main.py
```

### Optional: analysis scripts extras

`scripts/analyze_batch.py` needs `pandas` and `tabulate`, which are declared under the `analysis` optional-dependencies group:

```bash
uv sync --extra analysis
# or
pip install -e ".[analysis]"
```

### Entry Points

- `python main.py`
- `python -m microciv`

`main.py` injects `src/` into `sys.path`, then calls `microciv.app:main()`.

---

## Common Commands

```bash
# Run the game
python main.py

# Batch AI data collection
python scripts/batch_autoplay.py -n <games> --policy <policy> --label <tag>

# Large-scale param-grid dataset generation
python scripts/generate_dataset.py -n <games-per-combo> --label <tag>

# Generate diagnostic report from dataset (requires pandas + tabulate)
python scripts/analyze_batch.py --input <dataset.json> --output <report.md>

# Run all tests
python -m pytest -q

# Run single test module
python -m pytest tests/<module>.py -q

# Run single test
python -m pytest tests/<module>.py::<test_name> -q

# Lint
ruff check src tests

# Type check
mypy
```

---

## Project Structure

```
microciv/
├── src/microciv/
│   ├── ai/                  # AI strategies
│   │   ├── policy.py        # Policy Protocol
│   │   ├── greedy.py        # GreedyPolicy
│   │   ├── heuristics.py    # City/road site scoring and resource ring helpers
│   │   ├── random_policy.py # RandomPolicy
│   │   └── custom.py        # Custom strategy placeholder
│   ├── game/                # Core game rules and state machine
│   │   ├── models.py        # All state dataclasses
│   │   ├── engine.py        # GameEngine state transitions
│   │   ├── actions.py       # Action models and validation
│   │   ├── enums.py         # All StrEnum enums
│   │   ├── networks.py      # Road network connectivity (BFS / union-find)
│   │   ├── resources.py     # Resource ownership and per-turn settlement
│   │   ├── mapgen.py        # Procedural map generation
│   │   └── scoring.py       # Score calculation
│   ├── records/             # Local persistence and export
│   │   ├── models.py        # RecordEntry and snapshot dataclasses
│   │   ├── store.py         # JSON file I/O, schema versioning
│   │   └── export.py        # JSON export to exports/
│   ├── tui/                 # Terminal UI components
│   │   └── pixel_font.py    # Block character pixel font rendering
│   ├── utils/               # Utility functions
│   │   ├── grid.py          # Coord type, neighbor calc, sorting
│   │   └── rng.py           # Seeded RNG wrapper
│   ├── app.py               # Application entry point
│   ├── curses_app.py        # Curses controller and rendering (largest file)
│   ├── session.py           # Runtime session helpers
│   ├── config.py            # Path configuration
│   └── constants.py         # Global constants and balance parameters
├── scripts/                 # Batch runners and data analysis scripts
│   ├── batch_autoplay.py    # Single-config bulk runs
│   ├── generate_dataset.py  # Parameter-grid dataset generation
│   └── analyze_batch.py     # Dataset diagnostic report generation
├── tests/                   # Test suite (pytest)
├── data/                    # Runtime Records data (records.json)
├── exports/                 # JSON export directory
├── docs/                    # Chinese project docs and flowcharts
├── main.py                  # Startup script
├── pyproject.toml           # Project configuration
└── uv.lock                  # uv dependency lock
```

---

## Runtime Architecture

**Entry flow**:

```
main.py -> inject src into sys.path -> microciv.app.main()
    -> CursesMicroCivApp().run()
    -> curses.wrapper(_main)
```

**Core game loop**:

```
GameConfig
    -> session.create_game_session()
        -> MapGenerator().generate(config)   # map generation
        -> GameState.empty(config) + fill board
        -> attach Policy (Greedy/Random/None)
    -> GameSession (holds GameState + GameEngine + Policy)
    -> per turn: apply_action(action)
        -> validate_action()                 # action legality check
        -> _apply_*()                        # state mutation
        -> recompute_networks()              # network connectivity
        -> recompute_resource_ownership()    # resource ownership
        -> settle_resources()                # resource settlement
        -> calculate_score()                 # score calculation
        -> turn += 1 or is_game_over = True
```

**Application layers**:

1. **UI Layer**: `CursesMicroCivApp` (curses event loop + rendering)
2. **Controller Layer**: `MicroCivController` (UI-agnostic state routing and interaction logic)
3. **Session Layer**: `GameSession` (wraps `GameState`, `GameEngine`, `Policy`)
4. **Engine Layer**: `GameEngine` (all state transitions and turn advancement)
5. **Domain Layer**: `game/models.py`, `game/actions.py`, `game/enums.py`
6. **System Layer**: `networks.py`, `resources.py`, `scoring.py`, `mapgen.py`
7. **Persistence Layer**: `records/store.py`, `records/models.py`, `records/export.py`

**UI page flow** (managed by `ScreenRoute` in `curses_app.py`):

```
Main Menu
    -> Play / Autoplay -> Setup (map preview + config)
        -> Start -> Game Screen (manual or autoplay)
            -> m key / click -> In-game Menu (Resume / Restart / Menu / Exit)
            -> select empty tile -> Settlement panel (City / Road + Build / Cancel)
            -> select city -> City panel (Buildings / Technologies)
                -> Buildings -> Build subpanel (4 building types + Build / Cancel)
                -> Technologies -> Tech subpanel (4 techs + Research / Cancel)
            -> final turn -> Final screen (Restart / Menu / Exit)
    -> Records -> Records grid (paginated list)
        -> click slot -> Record detail (final map + stats)
    -> Exit
```

---

## Coding Conventions & Development Guidelines

### General Conventions

- **First line of every module**: `from __future__ import annotations`
- **Coordinate system**: `Coord = tuple[int, int]`, format is `(row, col)` / `(x, y)`
  - Deterministic sorting via `coord_sort_key()`
- **Enums**: All are `StrEnum` for easy JSON serialization
- **Dataclasses**:
  - State classes use `@dataclass(slots=True)`
  - Immutable value objects use `@dataclass(frozen=True, slots=True)` (e.g. `Action`, record snapshots)
- **State mutability**: `GameState` and nested objects are mutable; AI lookahead uses `deepcopy` + `simulate_action()`
- **Network merging**: When roads connect cities, `recompute_networks()` uses BFS to discover connected components and merges resources/tech via `Network.merge_from()`
- **Resource settlement**: `settle_resources()` is called after every `apply_action()`, not just at end of turn
- **Map generation quality gate**: `MAX_MAP_RETRIES = 20`, enforcing constraints on buildable ratio, plain ratio, wasteland ratio, river adjacency to wasteland, etc.

### Ruff Config

- `line-length = 100`
- `target-version = "py313"`
- Enabled rules: `B` (bugbear), `E` (pycodestyle errors), `F` (pyflakes), `I` (isort), `UP` (pyupgrade)

### Key Classes & Functions Cheatsheet

**State models**:
- `GameConfig.for_play(...)` / `GameConfig.for_autoplay(...)` — config factories
- `GameState.empty(config)` — empty state factory
- `Tile(base_terrain, occupant=OccupantType.NONE)`
- `ResourcePool(food, wood, ore, science)` — `.can_afford()`, `.spend()`, `.merge()`

**Actions**:
- `Action.build_city(coord)`, `Action.build_road(coord)`, `Action.build_building(city_id, type)`, `Action.research_tech(city_id, type)`, `Action.skip()`

**Engine**:
- `GameEngine(state).apply_action(action) -> EngineResult`

**AI**:
- `GreedyPolicy().select_action(state) -> Action`
- `RandomPolicy(seed).select_action(state) -> Action`
- `simulate_action(state, action) -> GameState` (deepcopy lookahead)
- `resource_ring_counts(state, coord) -> tuple[forest, mountain, river, plain, occupied]` — neighbor terrain analysis used by both scoring and AI
- `city_site_score(state, coord) -> int` — heuristic city placement score
- `road_site_score(state, coord) -> int` — heuristic road placement score
- `GreedyPolicy.explain_decision(state) -> dict[str, object]` — staged greedy telemetry (`rescue / consolidate / expand / fill`, score delta, site/network budgets)

**Records**:
- `RecordEntry.from_game_state(record_id=..., timestamp=..., state=...)`
- `RecordStore(path).append_completed_game(state) -> RecordEntry`
- `export_records_json(database, output_dir) -> Path`
- `turn_snapshots[*].score_breakdown` — per-turn score composition
- `decision_contexts[*]` — Greedy stage/budget telemetry or Random type weights

---

## Testing Strategy

Test framework is `pytest`, configured in `pyproject.toml`.

**Test file layout**:

- `test_smoke.py` — config defaults and enum basic assertions
- `test_engine.py` — core engine action validation (city build, road build, building, tech, skip, game over)
- `test_models.py` — data model validation
- `test_mapgen.py` — map generation reproducibility, size, quality rules, river count
- `test_networks.py` — network connectivity
- `test_resources.py` — resource settlement
- `test_scoring.py` — score calculation
- `test_ai.py` — Greedy/Random strategy legality, staged Greedy food rescue behavior, full game completion, fixed-seed score baselines
- `test_records.py` — RecordEntry serialization, Store persistence, schema migration, FIFO trimming, export
- `test_batch_autoplay.py` — `scripts/batch_autoplay.py` single-config bulk run + JSON/CSV/summary outputs
- `test_generate_dataset.py` — `scripts/generate_dataset.py` parameter-grid dataset generation and manifest
- `test_analyze_batch.py` — `scripts/analyze_batch.py` Markdown report generation (requires `analysis` extras)
- `test_grid.py`, `test_curses_app.py` — utility and UI tests

**Testing style characteristics**:

- Heavy use of `GameState.empty(GameConfig.for_play())` to manually construct minimal states
- Mixed integration and unit tests: e.g. `test_greedy_and_random_can_finish_full_games` runs a full 30-turn game
- Uses `tmp_path` and `monkeypatch` for filesystem and constant isolation
- Contains performance/baseline assertions (e.g. `assert state.score >= 500`)

---

## Security & Deployment Notes

- **No traditional deployment pipeline**: this is a locally-run terminal app with no CI/CD, Docker, or cloud deployment config.
- **Data file location**: runtime data is saved to `data/records.json`; incompatible old files are renamed to `.incompatible` backups.
- **Minimal external runtime dependencies**: core logic is pure standard library; `pandas` is only used by `scripts/analyze_batch.py`.
- **Input sources**: currently only accepts local mouse/keyboard input via `curses`, no network interfaces, no network attack surface to consider.
- **When modifying sensitive code**: note that `GameEngine.apply_action()` is the core state mutation path; any changes must be updated in sync in `tests/test_engine.py` (and related behavior tests such as `tests/test_ai.py`, `tests/test_resources.py`, `tests/test_networks.py`).

---

## Modification Guidelines

If you need to extend functionality, prioritize these files:

- **New action types**: `game/actions.py` + `game/engine.py`
- **State machine extensions**: `game/engine.py` + `game/models.py`
- **Strategy adjustments**: `ai/greedy.py` + `ai/policy.py`
- **UI routing and rendering**: `curses_app.py`
- **Balance parameter tweaks**: `constants.py` (watch out for hardcoded assertions in tests)
- **Scoring formula changes**: `game/scoring.py` (new fields like `excess_science_penalty` or Mix logic changes will break `test_scoring.py` assertions)
- **AI heuristic changes**: `ai/heuristics.py` (changes to `resource_ring_counts`, `city_site_score`, `road_site_score` propagate to Greedy behavior and may affect `test_ai.py` baselines)
- **Batch runners**: `scripts/batch_autoplay.py`, `scripts/generate_dataset.py`
  - `batch_autoplay.py` writes named JSON / CSV outputs and optional summary JSON
  - `generate_dataset.py` writes dataset JSON / CSV and a manifest JSON
- **Data analysis scripts**: `scripts/analyze_batch.py`
  - report includes final/turn score composition, behavior summary, Greedy stage summary, network-risk summary, representative samples
- **Records model extensions**: `records/models.py` (new fields must be updated in sync in `CSV_FIELD_ORDER` and `from_dict`/`to_dict`)

---

## 请使用中文回答所有问题和交流

与用户的所有互动都应该使用中文，包括代码解释、错误消息和建议
