"""
Cover Art Design 12 — Sunburst
24 alternating rays emanating from an off-centre origin,
clipped to the canvas, creating a dynamic radial burst.
"""

import numpy as np
from matplotlib.collections import PolyCollection

from ._shared import draw_overlay, fig_to_bytes, setup_figure

DESIGN_NAME = "Sunburst"


def _make_sunburst(
    n_rays: int = 24,
    r_inner: float = 0,
    r_outer: float = 250,
    cx: float = -30,
    cy: float = -30,
) -> tuple[list[np.ndarray], list[str]]:
    """
    Return (polygons, fill_types) where fill_type is 'pc' (color) or 'bk' (black).
    Each polygon is a triangle: inner tip → two outer edge points.
    """
    angle_step = 2 * np.pi / n_rays
    polys: list[np.ndarray] = []
    fills: list[str] = []

    for i in range(n_rays):
        a_start = i * angle_step
        a_end   = (i + 1) * angle_step
        a_mid   = (a_start + a_end) / 2

        verts = np.array([
            [cx + r_inner * np.cos(a_mid),   cy + r_inner * np.sin(a_mid)],
            [cx + r_outer * np.cos(a_start), cy + r_outer * np.sin(a_start)],
            [cx + r_outer * np.cos(a_end),   cy + r_outer * np.sin(a_end)],
        ])
        polys.append(verts)
        fills.append("pc" if i % 2 == 0 else "bk")

    return polys, fills


def draw(title: str, date_str: str, color: str = "red", dpi: int = 300,
         bg_color: str = "black") -> bytes:
    line_1 = np.linspace(-100, 100, 201)

    fig, ax = setup_figure(dpi, bg_color=bg_color)

    # ── pattern ──────────────────────────────────────────────────────────────
    polys, fills = _make_sunburst(n_rays=24, r_inner=0, r_outer=250,
                                  cx=-30, cy=-30)

    color_polys = [p for p, f in zip(polys, fills) if f == "pc"]
    bg_polys    = [p for p, f in zip(polys, fills) if f == "bk"]

    ax.add_collection(PolyCollection(
        color_polys, facecolors=color, edgecolors="none",
        alpha=0.6, zorder=1,
    ))
    ax.add_collection(PolyCollection(
        bg_polys, facecolors=bg_color, edgecolors="none",
        alpha=1.0, zorder=1,
    ))

    # ── overlay ──────────────────────────────────────────────────────────────
    draw_overlay(ax, title, date_str, color, line_1, bg_color=bg_color)

    return fig_to_bytes(fig, dpi)
