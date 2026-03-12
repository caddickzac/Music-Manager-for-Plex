"""
Cover Art Design 9 — Spiral Wide
600-layer spiral of shrinking rectangles rotating 8° per layer.
"""

import numpy as np
import matplotlib.colors as mcolors
from matplotlib.collections import LineCollection

from ._shared import draw_overlay, fig_to_bytes, setup_figure

DESIGN_NAME = "Spiral Wide"


def _make_spiral_rects(
    N: int = 600,
    scale_factor: float = 0.99,
    rotation_deg: float = 8,
    start_size: float = 300,
    lw_start: float = 0.8,
    lw_end: float = 0.01,
) -> tuple[list[np.ndarray], list[float]]:
    """
    Return (segments, linewidths).
    Each segment is a (5, 2) array — a closed rotated rectangle path.
    """
    segments: list[np.ndarray] = []
    linewidths: list[float] = []

    for i in range(N):
        size = start_size * (scale_factor ** i)
        angle = np.radians(rotation_deg * i)
        lw = lw_start + (lw_end - lw_start) * i / max(N - 1, 1)

        h = size / 2
        corners = np.array([[-h, -h], [h, -h], [h, h], [-h, h], [-h, -h]])
        cos_a, sin_a = np.cos(angle), np.sin(angle)
        x_rot = corners[:, 0] * cos_a - corners[:, 1] * sin_a
        y_rot = corners[:, 0] * sin_a + corners[:, 1] * cos_a

        segments.append(np.column_stack([x_rot, y_rot]))
        linewidths.append(lw)

    return segments, linewidths


def draw(title: str, date_str: str, color: str = "red", dpi: int = 300,
         bg_color: str = "black") -> bytes:
    line_1 = np.linspace(-100, 100, 201)

    fig, ax = setup_figure(dpi, bg_color=bg_color)

    # ── pattern ──────────────────────────────────────────────────────────────
    rgba = list(mcolors.to_rgba(color))
    rgba[3] = 0.6                             # bake alpha into border colour
    border_color = tuple(rgba)

    segments, lws = _make_spiral_rects(
        N=600, scale_factor=0.99, rotation_deg=8,
        start_size=300, lw_start=0.8, lw_end=0.01,
    )

    lc = LineCollection(segments, linewidths=lws,
                        colors=border_color, zorder=1)
    ax.add_collection(lc)

    # ── overlay ──────────────────────────────────────────────────────────────
    draw_overlay(ax, title, date_str, color, line_1, bg_color=bg_color)

    return fig_to_bytes(fig, dpi)
