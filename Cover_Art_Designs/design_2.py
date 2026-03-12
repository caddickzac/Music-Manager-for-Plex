"""
Cover Art Design 2 — Rolling Squares
Ghost trails of a square rolling along multiple diagonal rows.
"""

import numpy as np
from matplotlib.collections import LineCollection

from ._shared import draw_overlay, fig_to_bytes, setup_figure

DESIGN_NAME = "Rolling Squares"


def _rolling_square_frames(
    N_density: int = 12,
    s: float = 12,
    start_x: float = -250,
    end_x: float = 250,
    ground_y: float = 0,
) -> list[np.ndarray]:
    """
    Return a list of closed polygon arrays (shape Nx2) representing
    each 'frame' of a square of side *s* rolling to the right.

    The pivot at each quarter-roll is the front-bottom corner.
    Clockwise rotation by theta degrees (0→90) per quarter-roll.
    """
    total_rolls = int((end_x - start_x) / s)
    N = max(round(N_density * total_rolls / max(int(200 / s), 1)), 1)

    # corners in local frame: square to the LEFT of pivot, extending up
    template = np.array([[0, 0], [-s, 0], [-s, s], [0, s], [0, 0]])

    frames: list[np.ndarray] = []
    for t in np.linspace(0, total_rolls, N):
        roll_num = int(t)
        theta_deg = (t - roll_num) * 90.0
        pivot_x = start_x + roll_num * s

        a = -np.radians(theta_deg)           # negative → clockwise
        cos_a, sin_a = np.cos(a), np.sin(a)
        x_rot = template[:, 0] * cos_a - template[:, 1] * sin_a + pivot_x
        y_rot = template[:, 0] * sin_a + template[:, 1] * cos_a + ground_y
        frames.append(np.column_stack([x_rot, y_rot]))

    return frames


def draw(title: str, date_str: str, color: str = "red", dpi: int = 300,
         bg_color: str = "black") -> bytes:
    line_1 = np.linspace(-100, 100, 201)

    fig, ax = setup_figure(dpi, bg_color=bg_color)

    # ── pattern ──────────────────────────────────────────────────────────────
    frames = _rolling_square_frames(N_density=12, s=12,
                                    start_x=-250, end_x=250, ground_y=0)

    # Each row: (x_offset, y_offset) matching the R script
    row_offsets = [
        (0,   -69), (5,  -52), (10, -35), (15, -18),
        (20,   -1), (25,  16), (30,  33), (35,  50), (40,  67),
    ]

    segments: list[np.ndarray] = []
    for dx, dy in row_offsets:
        for frame in frames:
            shifted = frame + np.array([dx, dy])
            segments.append(shifted)

    lc = LineCollection(segments, linewidths=0.7, colors=color,
                        alpha=0.9, zorder=1)
    ax.add_collection(lc)

    # ── overlay ──────────────────────────────────────────────────────────────
    draw_overlay(ax, title, date_str, color, line_1, bg_color=bg_color)

    return fig_to_bytes(fig, dpi)
