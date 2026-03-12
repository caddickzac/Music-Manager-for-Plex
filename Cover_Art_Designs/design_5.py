"""
Cover Art Design 5 — Triangle Tiles A
Right-pointing triangle columns with alternating vertical offsets.
Outer color triangles with black inner triangles creating a relief effect,
plus a reflected copy filling the opposite side.
"""

import numpy as np
from matplotlib.collections import PolyCollection

from ._shared import draw_overlay, fig_to_bytes, setup_figure

DESIGN_NAME = "Triangle Tiles A"


def _make_triangle_tiles(
    s: float = 14,
    m: float = 7,
    x_range: tuple[float, float] = (-115, 115),
    y_range: tuple[float, float] = (-85, 65),
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """
    Return (outer_pc, inner_bk).

    outer_pc: large outer triangles (color fill)
    inner_bk: smaller inner triangles (black fill, drawn on top)
    """
    xs = np.arange(x_range[0], x_range[1] + 0.1, s)
    ys = np.arange(y_range[0], y_range[1] + 0.1, s * 2)

    outer: list[np.ndarray] = []
    inner: list[np.ndarray] = []

    for i, cx in enumerate(xs):
        v_off = s if (i % 2 == 1) else 0.0
        for cy in ys:
            cy_s = cy + v_off
            outer.append(np.array([
                [cx,      cy_s - s],
                [cx,      cy_s + s],
                [cx + s,  cy_s    ],
            ]))
            inner.append(np.array([
                [cx,          cy_s - s + m],
                [cx,          cy_s + s - m],
                [cx + s / 2,  cy_s        ],
            ]))

    return outer, inner


def draw(title: str, date_str: str, color: str = "red", dpi: int = 300,
         bg_color: str = "black") -> bytes:
    line_1 = np.linspace(-100, 100, 201)

    fig, ax = setup_figure(dpi, bg_color=bg_color)

    # ── pattern ──────────────────────────────────────────────────────────────
    outer, inner = _make_triangle_tiles(s=14, m=7)

    # Outer color triangles
    ax.add_collection(PolyCollection(
        outer, facecolors=color, edgecolors="none",
        alpha=0.6, zorder=1,
    ))
    # Background cutout triangles (on top)
    ax.add_collection(PolyCollection(
        inner, facecolors=bg_color, edgecolors="none",
        alpha=1.0, zorder=2,
    ))
    # Reflected color triangles  (x → -x - 6)
    reflected = [v * np.array([-1, 1]) - np.array([6, 0]) for v in inner]
    ax.add_collection(PolyCollection(
        reflected, facecolors=color, edgecolors="none",
        alpha=0.6, zorder=1,
    ))

    # ── overlay ──────────────────────────────────────────────────────────────
    draw_overlay(ax, title, date_str, color, line_1, bg_color=bg_color)

    return fig_to_bytes(fig, dpi)
