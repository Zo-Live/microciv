"""Helpers for fitting raster assets into terminal cell regions."""

from __future__ import annotations

from PIL import Image
from textual_image._terminal import get_cell_size

from microciv.tui.renderers.assets import APP_BACKGROUND, rgba


def fit_image_to_cells(
    image: Image.Image,
    *,
    max_width_cells: int | None = None,
    max_height_cells: int | None = None,
    resample: Image.Resampling = Image.Resampling.NEAREST,
) -> Image.Image:
    """Scale an image down to fit within a terminal-cell bounding box."""
    if max_width_cells is None and max_height_cells is None:
        return image

    cell_size = get_cell_size()
    max_width_px = image.width if max_width_cells is None or max_width_cells <= 0 else max_width_cells * cell_size.width
    max_height_px = (
        image.height if max_height_cells is None or max_height_cells <= 0 else max_height_cells * cell_size.height
    )

    scale = min(max_width_px / image.width, max_height_px / image.height, 1.0)
    if scale >= 0.999:
        return image

    width = max(int(round(image.width * scale)), 1)
    height = max(int(round(image.height * scale)), 1)
    return image.resize((width, height), resample)


def blank_image_for_cells(
    width_cells: int | None,
    height_cells: int | None,
    *,
    background: str = APP_BACKGROUND,
) -> Image.Image:
    """Return a solid background image sized to a terminal-cell region."""
    width_px, height_px = image_size_for_cells(width_cells, height_cells)
    return Image.new("RGBA", (width_px, height_px), rgba(background))


def image_size_for_cells(width_cells: int | None, height_cells: int | None) -> tuple[int, int]:
    """Return pixel dimensions for a terminal-cell region."""
    cell_size = get_cell_size()
    width = max((width_cells or 1) * cell_size.width, 1)
    height = max((height_cells or 1) * cell_size.height, 1)
    return (width, height)


def pad_image_to_cells(
    image: Image.Image,
    *,
    width_cells: int | None = None,
    height_cells: int | None = None,
    background: str = APP_BACKGROUND,
    align_x: str = "center",
    align_y: str = "middle",
) -> tuple[Image.Image, int, int]:
    """Place an image on a solid background canvas sized to a terminal-cell region."""
    target_width = image.width
    target_height = image.height
    if width_cells is not None and width_cells > 0:
        target_width = max(target_width, width_cells * get_cell_size().width)
    if height_cells is not None and height_cells > 0:
        target_height = max(target_height, height_cells * get_cell_size().height)

    if target_width == image.width and target_height == image.height:
        return (image, 0, 0)

    canvas = Image.new("RGBA", (target_width, target_height), rgba(background))
    offset_x = _aligned_offset(target_width, image.width, align_x)
    offset_y = _aligned_offset(target_height, image.height, align_y)
    canvas.alpha_composite(image, (offset_x, offset_y))
    return (canvas, offset_x, offset_y)


def _aligned_offset(target: int, source: int, mode: str) -> int:
    if mode == "left" or mode == "top":
        return 0
    if mode == "right" or mode == "bottom":
        return max(target - source, 0)
    return max((target - source) // 2, 0)
