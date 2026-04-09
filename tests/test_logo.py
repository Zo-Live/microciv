from __future__ import annotations

from microciv.tui.renderers.logo import LOGO_TAGLINE, render_logo_rows, render_logo_text


def test_logo_renderer_exposes_seven_hex_layout_and_text_shape() -> None:
    rows = render_logo_rows()
    rendered = render_logo_text()

    assert len(rows) == 4
    assert sum(len(row) for row in rows) == 7
    assert len(rows[0]) == 1
    assert len(rows[1]) == 3
    assert len(rows[2]) == 2
    assert len(rows[3]) == 1
    assert "__/  \\__" in rendered
    assert rendered.count("\n") == 6
    assert LOGO_TAGLINE == "Grow roads. Balance networks. Reach the final turn."
