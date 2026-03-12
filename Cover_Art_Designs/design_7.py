"""
Cover Art Design 7 — Circle Rows
Five rows of evenly-spaced circles, each pair of rows separated by a
cluster of dashed/dotted lines.  Y-values taken directly from the R original.
"""

import numpy as np
from matplotlib.collections import PolyCollection

from ._shared import draw_overlay, fig_to_bytes, setup_figure

DESIGN_NAME = "Circle Rows"


def _make_circle_row(
    cx_center: float = 0,
    cy: float = 0,
    r: float = 7,
    gap: float = 14,
    n_circles: int = 15,
    n_pts: int = 100,
) -> list[np.ndarray]:
    spacing = r * 2 + gap
    n_each = n_circles // 2
    centers = cx_center + np.arange(-n_each, n_each + 1) * spacing
    theta = np.linspace(0, 2 * np.pi, n_pts)
    return [np.column_stack([cx + r * np.cos(theta), cy + r * np.sin(theta)])
            for cx in centers]


def draw(title: str, date_str: str, color: str = "red", dpi: int = 300,
         bg_color: str = "black") -> bytes:
    line_1 = np.linspace(-100, 100, 201)

    fig, ax = setup_figure(dpi, bg_color=bg_color)

    # ── pattern ──────────────────────────────────────────────────────────────
    # Five circle rows — (x_shift, y_centre) exactly as in R script
    circle_rows = [
        (  0, +64),
        (+14, +32),
        (  0,   0),
        (-14, -32),
        (  0, -64),
    ]
    all_polys: list[np.ndarray] = []
    for dx, dy in circle_rows:
        all_polys.extend(_make_circle_row(cx_center=dx, cy=dy, r=7, gap=14, n_circles=15))

    ax.add_collection(PolyCollection(
        all_polys, facecolors=color, edgecolors="none",
        alpha=0.6, zorder=1,
    ))

    # Divider bands — exact y-values copied from R script
    # Each band: [top_y, ..., bottom_y] with linestyles dashed→dotdash→dotted→dotdash→dashed
    bands = [
        [54, 51, 48, 45, 42],     # between row 1 and row 2
        [22, 19, 16, 13, 10],     # between row 2 and row 3
        [-10, -13, -16, -19, -22],# between row 3 and row 4
        [-42, -45, -48, -51, -54],# between row 4 and row 5
    ]
    styles = ["dashed", "dashdot", "dotted", "dashdot", "dashed"]

    for band in bands:
        for y, sty in zip(band, styles):
            ax.plot(line_1, np.full_like(line_1, float(y)),
                    color=color, linestyle=sty,
                    linewidth=1, alpha=0.6, zorder=1)

    # Single dashed line below the bottom circle row
    ax.plot(line_1, np.full_like(line_1, -73.0),
            color=color, linestyle="dashed",
            linewidth=1, alpha=0.6, zorder=1)

    # ── overlay ──────────────────────────────────────────────────────────────
    draw_overlay(ax, title, date_str, color, line_1, bg_color=bg_color)

    return fig_to_bytes(fig, dpi)
