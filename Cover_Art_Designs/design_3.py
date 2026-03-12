"""
Cover Art Design 3 — Diamond Grid
Alternating solid and hollow diamonds tiling the canvas.
"""

import numpy as np
from matplotlib.collections import PolyCollection

from ._shared import draw_overlay, fig_to_bytes, setup_figure

DESIGN_NAME = "Diamond Grid"


def _make_diamond_grid(
    r: float = 5,
    x_range: tuple[float, float] = (-110, 110),
    y_range: tuple[float, float] = (-80, 80),
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """
    Return (solid_verts, empty_verts) where each entry is a (5, 2) array
    forming a closed diamond polygon.

    Grid A  (solid, fill=color)   — centres on even grid
    Grid B  (empty, fill=black)   — centres offset by (r, r)
    """
    def diamond(cx: float, cy: float) -> np.ndarray:
        return np.array([
            [cx,     cy - r],
            [cx + r, cy    ],
            [cx,     cy + r],
            [cx - r, cy    ],
        ])

    xs_a = np.arange(x_range[0], x_range[1] + 0.1, r * 2)
    ys_a = np.arange(y_range[0], y_range[1] + 0.1, r * 2)
    solid = [diamond(cx, cy) for cy in ys_a for cx in xs_a]

    xs_b = xs_a + r
    ys_b = ys_a + r
    empty = [diamond(cx, cy) for cy in ys_b for cx in xs_b]

    return solid, empty


def draw(title: str, date_str: str, color: str = "red", dpi: int = 300,
         bg_color: str = "black") -> bytes:
    line_1 = np.linspace(-100, 100, 201)

    fig, ax = setup_figure(dpi, bg_color=bg_color)

    # ── pattern ──────────────────────────────────────────────────────────────
    solid, empty = _make_diamond_grid(r=5)

    ax.add_collection(PolyCollection(
        solid, facecolors=color, edgecolors=color,
        linewidths=0.7, alpha=0.3, zorder=1,
    ))
    ax.add_collection(PolyCollection(
        empty, facecolors=bg_color, edgecolors=color,
        linewidths=0.7, alpha=0.3, zorder=1,
    ))

    # ── overlay ──────────────────────────────────────────────────────────────
    draw_overlay(ax, title, date_str, color, line_1, bg_color=bg_color)

    return fig_to_bytes(fig, dpi)
