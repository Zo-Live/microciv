"""Dot-matrix style logo and title renderers using the same style as score digits."""

from __future__ import annotations

from PIL import Image, ImageDraw

from microciv.tui.renderers.assets import APP_BACKGROUND, TEXT_ACCENT, SHADOW_COLOR, rgba
from microciv.tui.renderers.hexes import (
    CITY_COLOR,
    FOREST_COLOR,
    MOUNTAIN_COLOR,
    PLAIN_COLOR,
    RIVER_COLOR,
    ROAD_COLOR,
    WASTELAND_COLOR,
)

LOGO_TAGLINE = "Grow roads. Balance networks. Reach the final turn."

# Dot matrix patterns for "MicroCiv" - large blocky letters
# Using the same visual style as the score digits (BODY = █, SHADOW = ▒)
# All patterns have consistent 8-row height and compact width
TITLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "M": (
        "██▒   ░░██▒",
        "████▒  ████▒",
        "██░██▒██░██▒",
        "██░░███░░██▒",
        "██░░░█░░░██▒",
        "██░░░░░░░██▒",
        "██░░░░░░░██▒",
        "██░░░░░░░██▒",
    ),
    "i": (
        "░░██▒",
        "░░░░░",
        "░░██▒",
        "░░██▒",
        "░░██▒",
        "░░██▒",
        "░░██▒",
        "░░██▒",
    ),
    "c": (
        "░░████▒",
        "░██▒░░░",
        "██▒░░░░",
        "██▒░░░░",
        "██▒░░░░",
        "██▒░░░░",
        "░██▒░░░",
        "░░████▒",
    ),
    "r": (
        "░████░░░",
        "██▒░██▒░",
        "██▒░░░░░",
        "██▒░░░░░",
        "██▒░░░░░",
        "██▒░░░░░",
        "██▒░░░░░",
        "██▒░░░░░",
    ),
    "o": (
        "░░████▒",
        "░██▒░██▒",
        "██▒░░██▒",
        "██▒░░██▒",
        "██▒░░██▒",
        "██▒░░██▒",
        "░██▒░██▒",
        "░░████▒",
    ),
    "C": (
        "░░█████▒",
        "░██▒░░░░",
        "██▒░░░░░",
        "██▒░░░░░",
        "██▒░░░░░",
        "██▒░░░░░",
        "░██▒░░░░",
        "░░█████▒",
    ),
    "v": (
        "██▒░░░██▒",
        "██▒░░░██▒",
        "██▒░░░██▒",
        "░██▒░██▒░",
        "░██▒░██▒░",
        "░░██░██░░",
        "░░░███░░░",
        "░░░░█░░░░",
    ),
}

# Space between letters
LETTER_GAP = 2


# Dot-matrix hex patterns - representing the seven-hex logo layout
# Each hex is a small diamond pattern made of dots
HEX_CELL_SIZE = 6  # Size of each dot in the hex
HEX_PATTERN_SIZE = 7  # 7x7 grid for each hex


def _draw_dot_matrix_hex(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    center_y: int,
    color: str,
    cell_size: int = 6,
) -> None:
    """Draw a single hexagon using dot-matrix style (filled diamond shape)."""
    # Diamond pattern for a hex (approximated with dots)
    # 0 = empty, 1 = body color, 2 = shadow
    pattern = [
        [0, 0, 0, 1, 0, 0, 0],
        [0, 0, 1, 1, 1, 0, 0],
        [0, 1, 1, 1, 1, 1, 0],
        [1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1],
        [0, 1, 1, 1, 1, 1, 0],
        [0, 0, 1, 1, 1, 0, 0],
        [0, 0, 0, 1, 0, 0, 0],
    ]
    
    # Shadow offset
    shadow_offset = max(1, cell_size // 3)
    
    for row_idx, row in enumerate(pattern):
        for col_idx, cell in enumerate(row):
            if cell == 0:
                continue
            
            # Calculate position relative to center
            x = center_x + (col_idx - 3) * cell_size
            y = center_y + (row_idx - 3) * cell_size
            
            # Draw shadow first (offset)
            if cell == 1 or cell == 2:
                shadow_rect = (
                    x + shadow_offset, 
                    y + shadow_offset,
                    x + cell_size - 1 + shadow_offset,
                    y + cell_size - 1 + shadow_offset,
                )
                # Use a darker version for shadow or SHADOW_COLOR
                draw.rectangle(shadow_rect, fill=rgba("#5b5448"))
            
            # Draw body
            body_rect = (
                x,
                y,
                x + cell_size - 1,
                y + cell_size - 1,
            )
            draw.rectangle(body_rect, fill=rgba(color))


def render_dotmatrix_logo(
    *,
    hex_cell_size: int = 8,
    background: str = APP_BACKGROUND,
) -> Image.Image:
    """Render the seven-hex logo using dot-matrix style.
    
    Layout matches the original logo:
          [0,-1] RIVER
    [-1,0]WASTE  [1,-1]ROAD
          [0,0] CITY
    [-1,1]MTN    [1,0]FOREST
          [0,1] PLAIN
    """
    # Hex positions in the dot matrix grid
    # Each hex is offset in a hexagonal pattern
    hex_positions = [
        ((0, -1), RIVER_COLOR),
        ((-1, 0), WASTELAND_COLOR),
        ((1, -1), ROAD_COLOR),
        ((0, 0), CITY_COLOR),
        ((-1, 1), MOUNTAIN_COLOR),
        ((1, 0), FOREST_COLOR),
        ((0, 1), PLAIN_COLOR),
    ]
    
    # Calculate image dimensions
    # Horizontal spacing: 4 cells per hex column offset
    # Vertical spacing: 3 cells per hex row offset
    h_spacing = hex_cell_size * 5
    v_spacing = hex_cell_size * 4
    
    # Find bounds
    min_q = min(pos[0][0] for pos in hex_positions)
    max_q = max(pos[0][0] for pos in hex_positions)
    min_r = min(pos[0][1] for pos in hex_positions)
    max_r = max(pos[0][1] for pos in hex_positions)
    
    # Calculate image size with padding
    padding = hex_cell_size * 4
    width = (max_q - min_q) * h_spacing + padding * 4
    height = (max_r - min_r) * v_spacing + padding * 4
    
    image = Image.new("RGBA", (width, height), rgba(background))
    draw = ImageDraw.Draw(image)
    
    # Center offset
    center_x = width // 2
    center_y = height // 2
    
    # Draw each hex
    for (q, r), color in hex_positions:
        # Convert axial to pixel position (flat-top hexes)
        # Offset for flat-top hex layout
        x = center_x + int(q * h_spacing * 0.866)  # sqrt(3)/2
        y = center_y + int(r * v_spacing + q * v_spacing * 0.5)
        
        _draw_dot_matrix_hex(draw, x, y, color, cell_size=hex_cell_size)
    
    return image


def render_dotmatrix_title(
    text: str = "MicroCiv",
    *,
    cell_size: int = 6,
    body_color: str = TEXT_ACCENT,
    shadow_color: str = SHADOW_COLOR,
    background: str = APP_BACKGROUND,
) -> Image.Image:
    """Render text using dot-matrix style (same as score digits)."""
    if not text:
        return Image.new("RGBA", (1, 1), rgba(background))
    
    # Get patterns for each character
    patterns = []
    total_width = 0
    max_height = 0
    
    for char in text:
        pattern = TITLE_PATTERNS.get(char, TITLE_PATTERNS.get("o", ("",)))
        patterns.append(pattern)
        # Calculate width in cells
        if pattern:
            width_cells = max(len(row) for row in pattern)
        else:
            width_cells = 4
        total_width += width_cells
        max_height = max(max_height, len(pattern))
    
    # Add gaps between letters
    total_width += LETTER_GAP * (len(text) - 1)
    
    # Calculate image dimensions
    shadow_offset = max(1, cell_size // 3)
    width = total_width * cell_size + shadow_offset
    height = max_height * cell_size + shadow_offset
    
    image = Image.new("RGBA", (width, height), rgba(background))
    draw = ImageDraw.Draw(image)
    
    # Draw each character
    x_offset = 0
    for pattern in patterns:
        if not pattern:
            continue
        
        rows = len(pattern)
        cols = max(len(row) for row in pattern)
        
        for row_idx, row in enumerate(pattern):
            for col_idx, cell in enumerate(row.ljust(cols)):
                if cell in ("░", " "):  # Blank/empty - skip both special char and space
                    continue
                
                left = x_offset + col_idx * cell_size
                top = row_idx * cell_size
                right = left + cell_size - 1
                bottom = top + cell_size - 1
                
                # Draw shadow
                if cell in ("█", "▒"):
                    shadow_rect = (
                        left + shadow_offset,
                        top + shadow_offset,
                        right + shadow_offset,
                        bottom + shadow_offset,
                    )
                    draw.rectangle(shadow_rect, fill=rgba(shadow_color))
                
                # Draw body
                if cell == "█":
                    body_rect = (left, top, right, bottom)
                    draw.rectangle(body_rect, fill=rgba(body_color))
        
        x_offset += cols * cell_size + LETTER_GAP * cell_size
    
    return image


def render_menu_logo_mark(
    *,
    hex_cell_size: int = 10,
    background: str = APP_BACKGROUND,
) -> Image.Image:
    """Render just the dot-matrix logo mark (no title)."""
    return render_dotmatrix_logo(hex_cell_size=hex_cell_size, background=background)


def render_menu_logo_title(
    *,
    cell_size: int = 7,
    body_color: str = TEXT_ACCENT,
    shadow_color: str = SHADOW_COLOR,
    background: str = APP_BACKGROUND,
) -> Image.Image:
    """Render just the dot-matrix title."""
    return render_dotmatrix_title(
        "MicroCiv",
        cell_size=cell_size,
        body_color=body_color,
        shadow_color=shadow_color,
        background=background,
    )


