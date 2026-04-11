"""Static dot-matrix logo and title renderers for menu screens."""

from __future__ import annotations

BODY = "█"
SHADOW = "▒"

LOGO_MARK_ROWS: tuple[str, ...] = (
    "      BBB      ",
    "   BBBSSSBBB   ",
    " BBBSSBBBSSBBB ",
    "BBSSBBBBBBBSSBB",
    "BBBBBBBBBBBBBBB",
    "BBSSBBBBBBBSSBB",
    " BBBSSBBBSSBBB ",
    "   BBBSSSBBB   ",
    "      BBB      ",
)

TITLE_LINES: tuple[str, ...] = ("MICRO", "CIV")

LETTER_PATTERNS: dict[str, tuple[str, ...]] = {
    " ": (
        "     ",
        "     ",
        "     ",
        "     ",
        "     ",
        "     ",
        "     ",
    ),
    "C": (
        " BBBB",
        "BB   ",
        "BB   ",
        "BB   ",
        "BB   ",
        "BB   ",
        " BBBB",
    ),
    "I": (
        "BBBBB",
        "  B  ",
        "  B  ",
        "  B  ",
        "  B  ",
        "  B  ",
        "BBBBB",
    ),
    "M": (
        "BB BB",
        "BBBBB",
        "BBBBB",
        "BB BB",
        "BB BB",
        "BB BB",
        "BB BB",
    ),
    "O": (
        " BBB ",
        "BB BB",
        "BB BB",
        "BB BB",
        "BB BB",
        "BB BB",
        " BBB ",
    ),
    "R": (
        "BBBB ",
        "BB BB",
        "BB BB",
        "BBBB ",
        "BB B ",
        "BB BB",
        "BB BB",
    ),
    "V": (
        "BB BB",
        "BB BB",
        "BB BB",
        "BB BB",
        "BB BB",
        " BBB ",
        "  B  ",
    ),
}


def render_menu_logo_mark(
    cell_width: int = 2,
) -> str:
    """Render the static menu emblem."""
    return _render_rows(LOGO_MARK_ROWS, cell_width=cell_width)


def render_menu_logo_title(
    cell_width: int = 2,
    letter_gap: int = 1,
) -> str:
    """Render the large static MicroCiv title as two dot-matrix lines."""
    return "\n\n".join(
        _render_word(
            line,
            cell_width=cell_width,
            letter_gap=letter_gap,
        )
        for line in TITLE_LINES
    )


def _render_word(
    value: str,
    *,
    cell_width: int,
    letter_gap: int,
) -> str:
    glyphs = [LETTER_PATTERNS.get(char, LETTER_PATTERNS[" "]) for char in value.upper()]
    row_count = len(next(iter(LETTER_PATTERNS.values())))
    lines: list[str] = []
    for row_index in range(row_count):
        line_parts: list[str] = []
        for glyph_index, glyph in enumerate(glyphs):
            if glyph_index:
                line_parts.append(" " * letter_gap)
            line_parts.append(_styled_cells(glyph[row_index], cell_width=cell_width))
        lines.append("".join(line_parts))
    return "\n".join(lines)


def _render_rows(
    rows: tuple[str, ...],
    *,
    cell_width: int,
) -> str:
    lines = [_styled_cells(row, cell_width=cell_width) for row in rows]
    return "\n".join(lines)


def _styled_cells(
    row: str,
    *,
    cell_width: int,
) -> str:
    cells: list[str] = []
    for cell in row:
        repeated = cell_width
        if cell == "B":
            cells.append(BODY * repeated)
        elif cell == "S":
            cells.append(SHADOW * repeated)
        else:
            cells.append(" " * repeated)
    return "".join(cells)
