from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from microciv.game.models import GameConfig
from microciv.tui.presenters.game_session import build_state_from_config
from microciv.tui.renderers.assets import APP_BACKGROUND, SHADOW_COLOR, TEXT_ACCENT, rgba
from microciv.tui.renderers.digits import render_large_number_image, render_small_number_image
from microciv.tui.renderers.hexes import PLAIN_COLOR, RESOURCE_HEX_METRICS, SELECTED_BORDER_COLOR, render_hex_image
from microciv.tui.renderers.logo import render_logo_image
from microciv.tui.renderers.map import render_map_image
from microciv.tui.widgets.image_surface import ImageSurface


def test_hex_image_renders_background_fill_and_selected_border() -> None:
    image = render_hex_image(PLAIN_COLOR, selected=True, metrics=RESOURCE_HEX_METRICS)
    colors = {color for _count, color in image.getcolors(maxcolors=4096) or []}

    assert image.mode == "RGBA"
    assert image.width > 0
    assert image.height > 0
    assert rgba(APP_BACKGROUND) in colors
    assert rgba(PLAIN_COLOR) in colors
    assert rgba(SELECTED_BORDER_COLOR) in colors


def test_digit_images_use_body_and_shadow_colors() -> None:
    small = render_small_number_image(12)
    large = render_large_number_image(12)
    large_colors = {color for _count, color in large.getcolors(maxcolors=65536) or []}

    assert small.height < large.height
    assert small.width < large.width
    assert rgba(TEXT_ACCENT) in large_colors
    assert rgba(SHADOW_COLOR) in large_colors


def test_unselected_logo_and_map_images_do_not_render_selection_border() -> None:
    state = build_state_from_config(GameConfig.for_play(map_size=4, turn_limit=30, seed=2))
    logo = render_logo_image()
    game_map = render_map_image(state)
    logo_colors = {color for _count, color in logo.getcolors(maxcolors=65536) or []}
    map_colors = {color for _count, color in game_map.getcolors(maxcolors=65536) or []}

    assert rgba(SELECTED_BORDER_COLOR) not in logo_colors
    assert rgba(SELECTED_BORDER_COLOR) not in map_colors


def test_logo_and_map_images_render_as_raster_assets() -> None:
    state = build_state_from_config(GameConfig.for_play(map_size=4, turn_limit=30, seed=1))
    selected_coord = next(iter(state.board))

    logo = render_logo_image()
    game_map = render_map_image(state, selected_coord=selected_coord)

    assert logo.mode == "RGBA"
    assert logo.width > 0
    assert logo.height > 0
    assert game_map.mode == "RGBA"
    assert game_map.width > logo.width
    assert game_map.height > 0
    assert rgba(SELECTED_BORDER_COLOR) in {color for _count, color in game_map.getcolors(maxcolors=65536) or []}


def test_image_surface_accepts_pil_images() -> None:
    class DemoApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ImageSurface(render_logo_image(), id="demo-image")

    async def runner() -> None:
        app = DemoApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            widget = app.query_one("#demo-image", ImageSurface)
            assert widget.image is not None

    asyncio.run(runner())
