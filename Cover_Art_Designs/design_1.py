"""
Cover Art Design 1 — Crosshatch
Two families of diagonal lines crossing at ±45° over a black background.
"""

import numpy as np

from ._shared import draw_overlay, fig_to_bytes, setup_figure

DESIGN_NAME = "Crosshatch"


def draw(title: str, date_str: str, color: str = "red", dpi: int = 300,
         bg_color: str = "black") -> bytes:
    line_1 = np.linspace(-100, 100, 201)

    fig, ax = setup_figure(dpi, bg_color=bg_color)

    # ── pattern ──────────────────────────────────────────────────────────────
    # Direction 1 (y = x + offset)
    for off in np.arange(-187.5, 188.5, 15.0):
        ax.plot(line_1, line_1 + off,
                color=color, linewidth=0.4, alpha=0.9, zorder=1)

    # Direction 2 (x = x_rev + offset, i.e. y = -x + offset)
    line_1_rev = line_1[::-1]
    for off in np.arange(-172.5, 188.5, 15.0):
        ax.plot(line_1_rev + off, line_1,
                color=color, linewidth=0.4, alpha=0.9, zorder=1)

    # ── overlay ──────────────────────────────────────────────────────────────
    draw_overlay(ax, title, date_str, color, line_1, bg_color=bg_color)

    return fig_to_bytes(fig, dpi)
