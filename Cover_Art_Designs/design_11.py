"""
Cover Art Design 11 — Fractal Spirals
Six nested spirals at decreasing scales (300 → 0.2 starting size),
all rotating at 1°/layer, creating a fractal-like recursive effect.
"""

import numpy as np
import matplotlib.colors as mcolors
from matplotlib.collections import LineCollection

from ._shared import draw_overlay, fig_to_bytes, setup_figure

DESIGN_NAME = "Fractal Spirals"


def _spiral_segments(
    N: int,
    scale_factor: float,
    rotation_deg: float,
    start_size: float,
    lw_start: float,
    lw_end: float,
) -> tuple[list[np.ndarray], list[float]]:
    segments: list[np.ndarray] = []
    linewidths: list[float] = []

    for i in range(N):
        size = start_size * (scale_factor ** i)
        angle = np.radians(rotation_deg * i)
        lw = lw_start + (lw_end - lw_start) * i / max(N - 1, 1)

        h = size / 2
        c = np.array([[-h, -h], [h, -h], [h, h], [-h, h], [-h, -h]])
        cos_a, sin_a = np.cos(angle), np.sin(angle)
        x_rot = c[:, 0] * cos_a - c[:, 1] * sin_a
        y_rot = c[:, 0] * sin_a + c[:, 1] * cos_a

        segments.append(np.column_stack([x_rot, y_rot]))
        linewidths.append(lw)

    return segments, linewidths


# Six spiral definitions matching the R script exactly
_SPIRAL_DEFS = [
    dict(N=60, start_size=300, lw_start=0.8,    lw_end=0.01),
    dict(N=60, start_size=110, lw_start=0.5,    lw_end=0.01),
    dict(N=60, start_size=35,  lw_start=0.1,    lw_end=0.01),
    dict(N=60, start_size=10,  lw_start=0.01,   lw_end=0.001),
    dict(N=60, start_size=2,   lw_start=0.001,  lw_end=0.001),
    dict(N=60, start_size=0.2, lw_start=0.0001, lw_end=0.0001),
]


def draw(title: str, date_str: str, color: str = "red", dpi: int = 300,
         bg_color: str = "black") -> bytes:
    line_1 = np.linspace(-100, 100, 201)

    fig, ax = setup_figure(dpi, bg_color=bg_color)

    # ── pattern ──────────────────────────────────────────────────────────────
    rgba = list(mcolors.to_rgba(color))
    rgba[3] = 0.6
    border_color = tuple(rgba)

    all_segs: list[np.ndarray] = []
    all_lws: list[float] = []

    for defn in _SPIRAL_DEFS:
        segs, lws = _spiral_segments(
            N=defn["N"],
            scale_factor=0.99,
            rotation_deg=1,
            start_size=defn["start_size"],
            lw_start=defn["lw_start"],
            lw_end=defn["lw_end"],
        )
        all_segs.extend(segs)
        all_lws.extend(lws)

    lc = LineCollection(all_segs, linewidths=all_lws,
                        colors=border_color, zorder=1)
    ax.add_collection(lc)

    # ── overlay ──────────────────────────────────────────────────────────────
    draw_overlay(ax, title, date_str, color, line_1, bg_color=bg_color)

    return fig_to_bytes(fig, dpi)
