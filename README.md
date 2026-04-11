# MicroCiv

A terminal-based micro strategy civilization simulator built with Python and Textual.

![Python](https://img.shields.io/badge/python-3.13%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Overview

MicroCiv is a minimalist turn-based strategy game that runs in your terminal. Build cities, connect them with roads, manage resources, and research technologies across a hexagonal map.

### Features

- **Hexagonal Map System**: Procedurally generated maps with multiple terrain types (Plains, Forests, Mountains, Rivers, Wastelands)
- **City Building**: Found cities, construct buildings (Farms, Lumber Mills, Mines, Libraries)
- **Resource Management**: Balance Food, Wood, Ore, and Science across connected city networks
- **Technology Tree**: Research Agriculture, Logging, Mining, and Education
- **AI Opponents**: Baseline and Random AI policies for autonomous play
- **Records System**: Local persistence of game results with CSV export
- **Terminal UI**: Built with [Textual](https://textual.textualize.io/) for a rich terminal experience

## Installation

### Requirements

- Python 3.13 or higher
- Terminal with Unicode and color support (Windows Terminal, iTerm2, GNOME Terminal, etc.)

### Using uv (Recommended)

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone git@github.com:Zo-Live/microciv.git
cd microciv

# Create virtual environment and install dependencies
uv venv
uv sync
```

### Using pip

```bash
# Clone the repository
git clone git@github.com:Zo-Live/microciv.git
cd microciv

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
```

## Usage

### Start the Game

```bash
# Using uv
uv run microciv

# Or using the entry point
python -m microciv

# Or directly
python main.py
```

### Game Controls

| Key | Action |
|-----|--------|
| `Enter` / Click | Select menu items, confirm actions |
| `q` | Quit current screen |
| `m` | Open in-game menu |
| Arrow keys / Mouse | Navigate and interact |

### Game Flow

1. **Main Menu**: Choose Play, Autoplay, Records, or Exit
2. **Map Setup**: Select difficulty, map size, and turn limit
3. **Gameplay**: 
   - Click hexes to select terrain or cities
   - Build cities on empty terrain
   - Build roads to connect cities
   - Construct buildings in cities
   - Research technologies
4. **Game Over**: View final score and statistics

## Project Structure

```
microciv/
├── src/microciv/
│   ├── game/          # Core game logic
│   │   ├── engine.py  # Game loop and action execution
│   │   ├── models.py  # Game state and data structures
│   │   ├── actions.py # Action validation
│   │   ├── mapgen.py  # Map generation
│   │   ├── resources.py  # Resource management
│   │   ├── networks.py   # City network logic
│   │   └── scoring.py    # Score calculation
│   ├── tui/           # Terminal UI
│   │   ├── screens/   # Game screens
│   │   ├── widgets/   # UI components
│   │   ├── renderers/ # Image rendering
│   │   └── presenters/# State transformation
│   ├── ai/            # AI policies
│   │   ├── baseline.py
│   │   └── random_policy.py
│   ├── records/       # Persistence layer
│   └── utils/         # Utilities
├── tests/             # Test suite
├── docs/              # Documentation
├── data/              # Runtime data (created automatically)
└── exports/           # CSV exports (created automatically)
```

## Development

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/microciv

# Run specific test file
uv run pytest tests/test_engine.py
```

### Code Quality

```bash
# Format code
uv run ruff format src/

# Lint code
uv run ruff check src/

# Type check
uv run mypy src/microciv
```

### Project Structure Notes

- **Logic Layer** (`game/`): Pure game logic, no UI dependencies
- **TUI Layer** (`tui/`): Textual-based terminal interface
- **AI Layer** (`ai/`): Policy implementations that interact only with the logic layer
- **Records Layer** (`records/`): Local persistence and CSV export

## Game Rules Summary

### Terrain Types

| Terrain | Base Yield |
|---------|-----------|
| Plains | 1 Food |
| Forest | 1 Wood |
| Mountain | 1 Ore |
| River | 1 Science |
| Wasteland | -1 Food |

### Buildings

| Building | Cost | Yield |
|----------|------|-------|
| Farm | 3 Food | +1 Food |
| Lumber Mill | 3 Wood | +1 Wood |
| Mine | 3 Ore | +1 Ore |
| Library | 3 Science | +1 Science |

### Network Rules

- Cities connected by roads form a network
- Resources and technologies are shared within a network
- Networks can merge when cities are connected
- Famine occurs if a network's total food production ≤ 0

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

Built with:
- [Textual](https://textual.textualize.io/) - Terminal UI framework
- [Pillow](https://python-pillow.org/) - Image rendering
- [textual-image](https://github.com/adamchen123/textual-image) - Terminal image display
