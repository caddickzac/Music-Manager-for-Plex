"""
Cover_Art_Designs — registry of all available cover art designs.

Usage
-----
    from Cover_Art_Designs import DESIGNS, generate_cover_art

    png_bytes = generate_cover_art(
        design_key="design_1",
        title="My Playlist",
        date_str="03/10/2026",
        color="red",
    )
"""

import numpy as np
from importlib import import_module

from ._shared import wrap_title  # re-export for app use

# Ordered display-name → module-key mapping.
# The display names are what users see in the selectbox.
# The module keys map to Cover_Art_Designs/design_N.py files.
DESIGNS: dict[str, str] = {
    "None":             "none",
    "Crosshatch":       "design_1",
    "Rolling Squares":  "design_2",
    "Diamond Grid":     "design_3",
    "Nested Diamonds":  "design_4",
    "Triangle Tiles A": "design_5",
    "Triangle Tiles B": "design_6",
    "Circle Rows":      "design_7",
    "Spiral A":         "design_9",
    "Spiral B":         "design_10",
    "Fractal Spirals":  "design_11",
    "Sunburst":         "design_12",
    "Sine Waves":       "design_13",
}


def generate_cover_art(
    design_key: str,
    title: str,
    date_str: str,
    color: str = "red",
    bg_color: str = "black",
    dpi: int = 300,
) -> bytes | None:
    """
    Generate a cover-art PNG and return raw bytes.

    Parameters
    ----------
    design_key : str
        One of the values in DESIGNS (e.g. "design_1").
    title : str
        Playlist title printed on the image.
    date_str : str
        Date string printed on the image (e.g. "03/10/2026").
    color : str
        Matplotlib colour string for the primary (pattern + text) elements.
    bg_color : str
        Matplotlib colour string for the background / canvas.
    dpi : int
        Output resolution.

    Returns
    -------
    bytes or None
    """
    from ._shared import draw_overlay, fig_to_bytes, setup_figure

    if not design_key or design_key == "none":
        # Plain canvas — same text layout as all other designs
        fig, ax = setup_figure(dpi=dpi, bg_color=bg_color)
        line_1 = np.linspace(-100, 100, 200)
        draw_overlay(ax, title, date_str, color, line_1, bg_color=bg_color)
        return fig_to_bytes(fig, dpi=dpi)

    try:
        mod = import_module(f".{design_key}", package=__name__)
    except ModuleNotFoundError:
        return None

    return mod.draw(title=title, date_str=date_str, color=color,
                    bg_color=bg_color, dpi=dpi)
