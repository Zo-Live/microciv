"""Application entrypoints for MicroCiv."""

from __future__ import annotations

from microciv.tui.app import MicroCivApp


def main() -> None:
    """Run the Textual application."""
    MicroCivApp().run()
