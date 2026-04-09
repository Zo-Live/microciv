"""Blocky numeric renderers for score and turn displays."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text

BODY = "█"
SHADOW = "▒"
BLANK = " "

SMALL_PATTERNS: dict[str, tuple[str, ...]] = {
    "0": ("███▒", "█  █▒", "█  █▒", " ███▒"),
    "1": (" ██▒", "  █▒", "  █▒", " ███▒"),
    "2": ("███▒", "  ██▒", "██▒  ", "████▒"),
    "3": ("███▒", "  ██▒", "  ██▒", "███▒"),
    "4": ("█  █▒", "████▒", "   █▒", "   █▒"),
    "5": ("████▒", "██▒  ", "  ██▒", "███▒"),
    "6": (" ███▒", "██▒  ", "█  █▒", " ███▒"),
    "7": ("████▒", "  ██▒", "  █▒ ", "  █▒ "),
    "8": (" ███▒", "█  █▒", "█  █▒", " ███▒"),
    "9": (" ███▒", "█  █▒", "  ██▒", " ███▒"),
}

LARGE_PATTERNS: dict[str, tuple[str, ...]] = {
    "0": (
        "   █████▒▒",
        " ██▒▒   ██▒▒",
        "██▒▒     ██▒▒",
        "██▒▒     ██▒▒",
        "██▒▒     ██▒▒",
        "██▒▒     ██▒▒",
        " ██▒▒   ██▒▒",
        "   █████▒▒",
    ),
    "1": (
        "    ██▒▒",
        "  ████▒▒",
        "    ██▒▒",
        "    ██▒▒",
        "    ██▒▒",
        "    ██▒▒",
        "    ██▒▒",
        "  █████▒▒",
    ),
    "2": (
        "   █████▒▒",
        " ██▒▒   ██▒▒",
        "      ██▒▒",
        "    ██▒▒  ",
        "  ██▒▒    ",
        "██▒▒      ",
        "██▒▒      ",
        "████████▒▒",
    ),
    "3": (
        "   █████▒▒",
        " ██▒▒   ██▒▒",
        "      ██▒▒",
        "   ████▒▒ ",
        "      ██▒▒",
        "      ██▒▒",
        " ██▒▒   ██▒▒",
        "   █████▒▒",
    ),
    "4": (
        "██▒▒   ██▒▒",
        "██▒▒   ██▒▒",
        "██▒▒   ██▒▒",
        "████████▒▒",
        "      ██▒▒",
        "      ██▒▒",
        "      ██▒▒",
        "      ██▒▒",
    ),
    "5": (
        "████████▒▒",
        "██▒▒      ",
        "██▒▒      ",
        "██████▒▒  ",
        "      ██▒▒",
        "      ██▒▒",
        " ██▒▒   ██▒▒",
        "   █████▒▒",
    ),
    "6": (
        "   █████▒▒",
        " ██▒▒     ",
        "██▒▒      ",
        "██████▒▒  ",
        "██▒▒   ██▒▒",
        "██▒▒   ██▒▒",
        " ██▒▒   ██▒▒",
        "   █████▒▒",
    ),
    "7": (
        "████████▒▒",
        "     ██▒▒ ",
        "    ██▒▒  ",
        "   ██▒▒   ",
        "   ██▒▒   ",
        "  ██▒▒    ",
        "  ██▒▒    ",
        "  ██▒▒    ",
    ),
    "8": (
        "   █████▒▒",
        " ██▒▒   ██▒▒",
        "██▒▒     ██▒▒",
        " ███████▒▒",
        "██▒▒     ██▒▒",
        "██▒▒     ██▒▒",
        " ██▒▒   ██▒▒",
        "   █████▒▒",
    ),
    "9": (
        "   █████▒▒",
        " ██▒▒   ██▒▒",
        "██▒▒     ██▒▒",
        "██▒▒     ██▒▒",
        " ██████▒▒▒",
        "      ██▒▒",
        "    ██▒▒  ",
        " ████▒▒   ",
    ),
}


def render_small_number(value: int | str, *, body_color: str = "#f4e7c9", shadow_color: str = "#7f7562") -> RenderableType:
    """Render a compact numeric display."""
    return _render_number(str(value), SMALL_PATTERNS, body_color=body_color, shadow_color=shadow_color)


def render_large_number(value: int | str, *, body_color: str = "#f4e7c9", shadow_color: str = "#7f7562") -> RenderableType:
    """Render a larger numeric display."""
    return _render_number(str(value), LARGE_PATTERNS, body_color=body_color, shadow_color=shadow_color)


def _render_number(
    value: str,
    patterns: dict[str, tuple[str, ...]],
    *,
    body_color: str,
    shadow_color: str,
) -> RenderableType:
    rows = len(next(iter(patterns.values())))
    lines: list[Text] = []
    for row_index in range(rows):
        line = Text()
        for char_index, char in enumerate(value):
            if char_index:
                line.append("  ")
            pattern = patterns.get(char, patterns["0"])
            line.append(_styled_row(pattern[row_index], body_color=body_color, shadow_color=shadow_color))
        lines.append(line)
    return Group(*lines)


def _styled_row(row: str, *, body_color: str, shadow_color: str) -> Text:
    text = Text()
    for char in row:
        if char == BODY:
            text.append(char, style=body_color)
        elif char == SHADOW:
            text.append(char, style=shadow_color)
        else:
            text.append(char)
    return text
