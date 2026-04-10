from __future__ import annotations

from microciv.tui.renderers.logo import (
    LOGO_TAGLINE,
    render_logo_image,
    render_logo_rows,
    render_logo_specs,
    render_logo_text,
)


def test_logo_renderer_exposes_seven_hex_layout_and_text_shape() -> None:
    rows = render_logo_rows()
    specs = render_logo_specs()
    image = render_logo_image()
    rendered = render_logo_text()

    assert len(rows) == 5
    assert sum(len(row) for row in rows) == 7
    assert len(rows[0]) == 1
    assert len(rows[1]) == 2
    assert len(rows[2]) == 1
    assert len(rows[3]) == 2
    assert len(rows[4]) == 1
    assert len(specs) == 7
    assert image.width > 0
    assert image.height > 0
    assert "__/  \\__" in rendered
    assert rendered.count("\n") == 6
    assert LOGO_TAGLINE == "Grow roads. Balance networks. Reach the final turn."
