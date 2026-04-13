"""Application entrypoints for MicroCiv."""

from __future__ import annotations

from microciv.curses_app import CursesMicroCivApp


def main() -> None:
    """Run the curses application."""
    CursesMicroCivApp().run()
