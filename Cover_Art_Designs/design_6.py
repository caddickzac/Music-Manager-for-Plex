"""
Cover Art Design 6 — Triangle Tiles B
Expanded multi-reflection triangle tile pattern — more densely layered
than Design 5, creating a woven lattice effect.
"""

import numpy as np
from matplotlib.collections import PolyCollection

from ._shared import draw_overlay, fig_to_bytes, setup_figure

DESIGN_NAME = "Triangle Tiles B"


def _make_triangle_tiles(
    s: float = 14,
    m: float = 7,
    x_range: tuple[float, float] = (-115, 115),
    y_range: tuple[float, float] = (-85, 65),
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Return (outer_pc, inner_bk) triangle polygon lists."""
    xs = np.arange(x_range[0], x_range[1] + 0.1, s)
    ys = np.arange(y_range[0], y_range[1] + 0.1, s * 2)

    outer: list[np.ndarray] = []
    inner: list[np.ndarray] = []

    for i, cx in enumerate(xs):
        v_off = s if (i % 2 == 1) else 0.0
        for cy in ys:
            cy_s = cy + v_off
            outer.append(np.array([
                [cx,          cy_s - s],
                [cx,          cy_s + s],
                [cx + s,      cy_s    ],
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
    _outer, inner = _make_triangle_tiles(s=14, m=7)

    def _flip_x(verts: list[np.ndarray], x_shift: float, y_shift: float = 0
                ) -> list[np.ndarray]:
        """Reflect x-axis and shift, matching R's `(x*-1)+x_shift` idiom."""
        return [v * np.array([-1, 1]) + np.array([x_shift, y_shift])
                for v in verts]

    # Background cutout base (using inner triangles as stencil)
    ax.add_collection(PolyCollection(
        inner, facecolors=bg_color, edgecolors="none",
        alpha=1.0, zorder=1,
    ))
    # Reflected copies — six transformations mirroring the R script
    # R: (x*-1)-6, (x*-1)+8, (x+14)→black, (x*-1)+15 y+7, (x*-1)+1 y+7
    for fc, verts in [
        (color,    _flip_x(inner, -6,  0)),
        (color,    _flip_x(inner, +8,  0)),
        (bg_color, [v + np.array([14, 0]) for v in inner]),
        (color,    _flip_x(inner, +15, 7)),
        (color,    _flip_x(inner,  +1, 7)),
    ]:
        ax.add_collection(PolyCollection(
            verts, facecolors=fc, edgecolors="none",
            alpha=0.6 if fc != bg_color else 1.0, zorder=2,
        ))

    # ── overlay ──────────────────────────────────────────────────────────────
    draw_overlay(ax, title, date_str, color, line_1, bg_color=bg_color)

    return fig_to_bytes(fig, dpi)
