"""Block-element pixel font renderer for MicroCiv."""

from __future__ import annotations

import curses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _curses import window as CursesWindow

# Each glyph is 6 cols x 5 rows (5 cols main + 1 col shadow).
# Stride includes 1 blank column gap between adjacent glyphs.
GLYPH_HEIGHT = 5
GLYPH_WIDTH = 6
GLYPH_STRIDE = 7

CHAR_MAP: dict[str, tuple[str, ...]] = {
    "0": (
        "█████░",
        "█░  █░",
        "█░  █░",
        "█░  █░",
        "█████░",
    ),
    "1": (
        "  █░  ",
        " ██░  ",
        "  █░  ",
        "  █░  ",
        "█████░",
    ),
    "2": (
        "████░ ",
        "   ██░",
        " ███░ ",
        "██░   ",
        "█████░",
    ),
    "3": (
        "█████░",
        "    █░",
        " ████░",
        "    █░",
        "█████░",
    ),
    "4": (
        "█░  █░",
        "█░  █░",
        "█████░",
        "    █░",
        "    █░",
    ),
    "5": (
        "█████░",
        "█░    ",
        "████░ ",
        "    █░",
        "████░ ",
    ),
    "6": (
        " ████░",
        "█░    ",
        "█████░",
        "█░  █░",
        "█████░",
    ),
    "7": (
        "█████░",
        "   █░ ",
        "  █░  ",
        "  █░  ",
        "  █░  ",
    ),
    "8": (
        " ███░ ",
        "█░  █░",
        " ███░ ",
        "█░  █░",
        " ███░ ",
    ),
    "9": (
        "█████░",
        "█░  █░",
        "█████░",
        "    █░",
        "████░ ",
    ),
    "A": (
        " ███░ ",
        "█░  █░",
        "█████░",
        "█░  █░",
        "█░  █░",
    ),
    "B": (
        "████░ ",
        "█░  █░",
        "████░ ",
        "█░  █░",
        "████░ ",
    ),
    "C": (
        " ████░",
        "█░    ",
        "█░    ",
        "█░    ",
        " ████░",
    ),
    "D": (
        "████░ ",
        "█░  █░",
        "█░  █░",
        "█░  █░",
        "████░ ",
    ),
    "E": (
        "█████░",
        "█░    ",
        "███░  ",
        "█░    ",
        "█████░",
    ),
    "F": (
        "█████░",
        "█░    ",
        "███░  ",
        "█░    ",
        "█░    ",
    ),
    "G": (
        " ████░",
        "█░    ",
        "█░ ██░",
        "█░  █░",
        " ████░",
    ),
    "H": (
        "█░  █░",
        "█░  █░",
        "█████░",
        "█░  █░",
        "█░  █░",
    ),
    "I": (
        "█████░",
        "  █░  ",
        "  █░  ",
        "  █░  ",
        "█████░",
    ),
    "J": (
        "█████░",
        "   █░ ",
        "   █░ ",
        "█░ █░ ",
        " ██░  ",
    ),
    "K": (
        "█░  █░",
        "█░ █░ ",
        "███░  ",
        "█░ █░ ",
        "█░ █░ ",
    ),
    "L": (
        "█░    ",
        "█░    ",
        "█░    ",
        "█░    ",
        "█████░",
    ),
    "M": (
        "█░  █░",
        "██░██░",
        "█░█░█░",
        "█░  █░",
        "█░  █░",
    ),
    "N": (
        "█░  █░",
        "██░ █░",
        "█░█░█░",
        "█░ ██░",
        "█░  █░",
    ),
    "O": (
        " ███░ ",
        "█░  █░",
        "█░  █░",
        "█░  █░",
        " ███░ ",
    ),
    "P": (
        "████░ ",
        "█░  █░",
        "████░ ",
        "█░    ",
        "█░    ",
    ),
    "Q": (
        " ███░ ",
        "█░  █░",
        "█░  █░",
        " ███░ ",
        "   ██░",
    ),
    "R": (
        "████░ ",
        "█░  █░",
        "████░ ",
        "█░  █░",
        "█░  █░",
    ),
    "S": (
        " ████░",
        "█░    ",
        " ███░ ",
        "    █░",
        "████░ ",
    ),
    "T": (
        "█████░",
        "  █░  ",
        "  █░  ",
        "  █░  ",
        "  █░  ",
    ),
    "U": (
        "█░  █░",
        "█░  █░",
        "█░  █░",
        "█░  █░",
        " ███░ ",
    ),
    "V": (
        "█░  █░",
        "█░  █░",
        "█░  █░",
        " █░█░ ",
        "  █░  ",
    ),
    "W": (
        "█░  █░",
        "█░  █░",
        "█░█░█░",
        "██░██░",
        "█░  █░",
    ),
    "X": (
        "█░  █░",
        " █░█░ ",
        "  █░  ",
        " █░█░ ",
        "█░  █░",
    ),
    "Y": (
        "█░  █░",
        " █░█░ ",
        "  █░  ",
        "  █░  ",
        "  █░  ",
    ),
    "Z": (
        "█████░",
        "   █░ ",
        "  █░  ",
        " █░   ",
        "█████░",
    ),
    " ": (
        "      ",
        "      ",
        "      ",
        "      ",
        "      ",
    ),
    ":": (
        "      ",
        "  █░  ",
        "      ",
        "  █░  ",
        "      ",
    ),
    "/": (
        "      ",
        "   █░ ",
        "  █░  ",
        " █░   ",
        "      ",
    ),
    "=": (
        "      ",
        " ███░ ",
        "      ",
        " ███░ ",
        "      ",
    ),
    "-": (
        "      ",
        "      ",
        " ███░ ",
        "      ",
        "      ",
    ),
}


def _get_glyph(char: str) -> tuple[str, ...]:
    return CHAR_MAP.get(char.upper(), CHAR_MAP.get(" ", CHAR_MAP[" "]))


def render_text(
    stdscr: CursesWindow,
    x: int,
    y: int,
    text: str,
    color_pair: int,
    *,
    dim: bool = False,
) -> None:
    """Render pixel text at (x, y) using block elements."""
    attr = color_pair | (curses.A_DIM if dim else curses.A_NORMAL)
    for col_idx, ch in enumerate(text):
        glyph = _get_glyph(ch)
        base_x = x + col_idx * GLYPH_STRIDE
        for row_idx, row in enumerate(glyph):
            for pix_idx, pixel in enumerate(row):
                if pixel != " ":
                    try:
                        stdscr.addstr(y + row_idx, base_x + pix_idx, pixel, attr)
                    except curses.error:
                        pass


def render_number(
    stdscr: CursesWindow,
    x: int,
    y: int,
    value: int,
    width: int,
    *,
    align: str = "left",
    pad_zero: bool = False,
    color_pair: int,
    dim: bool = False,
) -> None:
    """Render a fixed-width pixel number."""
    text = str(value)
    if pad_zero:
        text = text.zfill(width)
    if align == "left":
        text = text[:width].ljust(width)
    else:
        text = text[:width].rjust(width)
    render_text(stdscr, x, y, text, color_pair, dim=dim)
