# MicroCiv

A terminal-based micro strategy civilization simulator built with Python and curses.

## Overview

MicroCiv is a turn-based civilization management game that runs in the terminal. It uses a square-grid world, mouse-first curses interaction, and Unicode block elements for map rendering.

### Features

- Square-grid procedural map generation with plains, forests, mountains, rivers, and wastelands
- City building, road networks, buildings, technologies, and score-based progression
- Manual play and autoplay
- Two autoplay AI policies: `Greedy` and `Random`
- Local records with JSON export
- Timing metrics for AI analysis: decision time, per-turn time, and full-session time

## Requirements

- Python 3.13 or higher
- A terminal with Unicode color support
- A terminal that supports mouse events in curses

## Installation

### Using uv

```bash
git clone git@github.com:Zo-Live/microciv.git
cd microciv
uv venv
uv sync
```

### Using pip

```bash
git clone git@github.com:Zo-Live/microciv.git
cd microciv
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
python main.py
```

or

```bash
python -m microciv
```

## Controls

MicroCiv is primarily mouse-driven.

- Left click: select tiles, buttons, buildings, technologies, records
- Mouse wheel: scroll record pages
- `m`: open in-game menu
- `b`: return to the previous layer in records and in-game subpanels
- `t`: jump to the top of the records list
- `d`: jump to the bottom of the records list
- `q`: exit the program
- Arrow keys: move map selection or scroll record pages

## Project Structure

```text
microciv/
├── src/microciv/
│   ├── ai/            # AI policies
│   ├── game/          # Core rules and state transitions
│   ├── records/       # Local persistence and CSV export
│   ├── session.py     # Runtime session helpers
│   ├── curses_app.py  # curses controller and rendering
│   └── app.py         # Entry point
├── docs/              # Project documents
├── tests/             # Test suite
├── data/              # Runtime records
└── exports/           # JSON exports
```

## Development

Run tests:

```bash
.venv/bin/python -m pytest -q
```

Run lint:

```bash
.venv/bin/ruff check src tests
```

## License

MIT
