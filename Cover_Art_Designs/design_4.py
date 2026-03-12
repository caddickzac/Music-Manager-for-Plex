"""
Cover Art Design 4 — Nested Diamonds
Large diamonds (filled) each containing a smaller black cutout diamond,
with small accent diamonds at the corner gaps between tiles.
"""

import numpy as np
from matplotlib.collections import PolyCollection

from ._shared import draw_overlay, fig_to_bytes, setup_figure

DESIGN_NAME = "Nested Diamonds"


def _make_nested_diamonds(
    r_outer: float = 12,
    r_inner: float = 5,
    x_range: tuple[float, float] = (-115, 115),
    y_range: tuple[float, float] = (-85, 65),
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """
    Return (outer_verts, inner_verts).

    outer_verts: large + accent diamonds  (fill=color, alpha 0.6)
    inner_verts: cutout diamonds          (fill=black, alpha 1.0)
    """
    tile = r_outer * 2

    def diamond(cx: float, cy: float, r: float) -> np.ndarray:
        return np.array([
            [cx,     cy - r],
            [cx + r, cy    ],
            [cx,     cy + r],
            [cx - r, cy    ],
        ])

    xs = np.arange(x_range[0], x_range[1] + 0.1, tile)
    ys = np.arange(y_range[0], y_range[1] + 0.1, tile)

    outer_verts: list[np.ndarray] = []
    inner_verts: list[np.ndarray] = []

    for cy in ys:
        for cx in xs:
            outer_verts.append(diamond(cx, cy, r_outer))           # large
            inner_verts.append(diamond(cx, cy, r_inner))           # cutout
            # small accent diamond at corner gap
            outer_verts.append(diamond(cx + r_outer, cy + r_outer, r_inner))

    return outer_verts, inner_verts


def draw(title: str, date_str: str, color: str = "red", dpi: int = 300,
         bg_color: str = "black") -> bytes:
    line_1 = np.linspace(-100, 100, 201)

    fig, ax = setup_figure(dpi, bg_color=bg_color)

    # ── pattern ──────────────────────────────────────────────────────────────
    outer, inner = _make_nested_diamonds(r_outer=12, r_inner=5)

    ax.add_collection(PolyCollection(
        outer, facecolors=color, edgecolors="none",
        alpha=0.6, zorder=1,
    ))
    ax.add_collection(PolyCollection(
        inner, facecolors=bg_color, edgecolors="none",
        alpha=1.0, zorder=2,
    ))

    # ── overlay ──────────────────────────────────────────────────────────────
    draw_overlay(ax, title, date_str, color, line_1, bg_color=bg_color)

    return fig_to_bytes(fig, dpi)
