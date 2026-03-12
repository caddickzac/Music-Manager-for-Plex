"""
Cover Art Design 13 — Sine Waves
Grouped horizontal bands of sinusoidal curves at varying heights,
creating a flowing rhythmic pattern.
"""

import numpy as np

from ._shared import draw_overlay, fig_to_bytes, setup_figure

DESIGN_NAME = "Sine Waves"


def draw(title: str, date_str: str, color: str = "red", dpi: int = 300,
         bg_color: str = "black") -> bytes:
    line_1 = np.linspace(-100, 100, 201)
    sin_2 = np.sin(2 * np.pi * line_1 / 200)

    fig, ax = setup_figure(dpi, bg_color=bg_color)

    # ── pattern ──────────────────────────────────────────────────────────────
    # Six bands of three sine-wave lines — matching R script offsets
    band_offsets = [0, 5, 10, 30, 35, 40, 60, 65, 70,
                    -20, -25, -30, -50, -55, -60, -80, -85]

    for off in band_offsets:
        ax.plot(line_1, sin_2 * 14 + off,
                color=color, linewidth=0.8, alpha=0.9, zorder=1)

    # ── overlay ──────────────────────────────────────────────────────────────
    draw_overlay(ax, title, date_str, color, line_1, bg_color=bg_color)

    return fig_to_bytes(fig, dpi)
