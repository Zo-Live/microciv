from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual_image.widget import Image as AutoBackendImage

from microciv.game.engine import GameEngine
from microciv.game.models import GameConfig
from microciv.tui.presenters.game_session import build_state_from_config
from microciv.tui.presenters.game_session import GameSession
from microciv.tui.renderers.assets import APP_BACKGROUND, SHADOW_COLOR, TEXT_ACCENT, rgba
from microciv.tui.renderers.digits import (
    render_final_score_number_image,
    render_large_number_image,
    render_small_number_image,
    scale_number_image,
)
from microciv.tui.renderers.hexes import PLAIN_COLOR, RESOURCE_HEX_METRICS, SELECTED_BORDER_COLOR, render_hex_image
from microciv.tui.renderers.logo import render_logo_image
from microciv.tui.renderers.map import render_map_image
from microciv.tui.renderers.scaling import fit_image_to_cells
from microciv.tui.screens.final import FinalScreen
from microciv.tui.widgets.image_surface import ImageSurface
from microciv.tui.widgets.logo import LogoWidget
from microciv.tui.widgets.map_preview import MapPreview
from microciv.tui.widgets.map_view import MapView
from microciv.tui.widgets.metric_panel import MetricPanel


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


def test_image_surface_uses_textual_image_auto_backend() -> None:
    class DemoApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ImageSurface(render_logo_image(), id="demo-image")

    async def runner() -> None:
        app = DemoApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            surface = app.query_one("#demo-image", ImageSurface)
            child = surface.query_one(AutoBackendImage)
            assert child.image is not None

    asyncio.run(runner())


def test_scale_number_image_preserves_original_palette() -> None:
    base = render_large_number_image(1288)
    scaled = scale_number_image(base, 0.5)
    base_colors = {color for _count, color in base.getcolors(maxcolors=65536) or []}
    scaled_colors = {color for _count, color in scaled.getcolors(maxcolors=65536) or []}

    assert scaled.width < base.width
    assert scaled.height < base.height
    assert scaled_colors <= base_colors


def test_fit_image_to_cells_preserves_palette_for_pixel_art() -> None:
    base = render_logo_image()
    scaled = fit_image_to_cells(base, max_width_cells=4, max_height_cells=4)
    base_colors = {color for _count, color in base.getcolors(maxcolors=65536) or []}
    scaled_colors = {color for _count, color in scaled.getcolors(maxcolors=65536) or []}

    assert scaled.width <= base.width
    assert scaled.height <= base.height
    assert scaled_colors <= base_colors


def test_final_score_number_image_renders() -> None:
    """Test that final score rendering works with simplified API."""
    image = render_final_score_number_image(1234)
    assert image.mode == "RGBA"
    assert image.width > 0
    assert image.height > 0


def test_image_surface_set_image_is_safe_after_backend_child_removal() -> None:
    class DemoApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ImageSurface(render_logo_image(), id="demo-image")

    async def runner() -> None:
        app = DemoApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            surface = app.query_one("#demo-image", ImageSurface)
            await surface.remove_children()
            surface.set_image(render_logo_image())

    asyncio.run(runner())


def test_metric_panel_refresh_is_safe_after_children_removed() -> None:
    class DemoApp(App[None]):
        def compose(self) -> ComposeResult:
            yield MetricPanel(score=12, turn=3, turn_limit=80, info_lines=["mode: normal"], autoplay=True, id="metric-panel")

    async def runner() -> None:
        app = DemoApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            panel = app.query_one("#metric-panel", MetricPanel)
            await panel.remove_children()
            panel.update_render(score=30, turn=4, turn_limit=80, info_lines=["mode: speed"])

    asyncio.run(runner())


def test_map_view_preview_logo_and_final_callbacks_are_safe_after_children_removed() -> None:
    state = build_state_from_config(GameConfig.for_play(map_size=4, turn_limit=30, seed=2))

    class DemoApp(App[None]):
        def compose(self) -> ComposeResult:
            yield MapView(state, id="map-view")
            yield MapPreview(state, id="map-preview")
            yield LogoWidget(id="logo-widget")

    async def runner() -> None:
        app = DemoApp()
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            map_view = app.query_one("#map-view", MapView)
            map_preview = app.query_one("#map-preview", MapPreview)
            logo = app.query_one("#logo-widget", LogoWidget)

            await map_view.remove_children()
            await map_preview.remove_children()
            await logo.remove_children()

            # Simplified API - these should be no-ops or safe to call
            map_view.set_state(state, None)
            map_preview.set_state(state)

    asyncio.run(runner())

    session_state = build_state_from_config(GameConfig.for_play(map_size=4, turn_limit=30, seed=3))
    session = GameSession(state=session_state, engine=GameEngine(session_state))

    class FinalDemoApp(App[None]):
        def on_mount(self) -> None:
            self.push_screen(FinalScreen(session))

    async def final_runner() -> None:
        app = FinalDemoApp()
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            screen = app.screen
            await screen.remove_children()
            screen._refresh_score_image()

    asyncio.run(final_runner())
