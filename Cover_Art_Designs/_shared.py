"""
Shared utilities for all cover art designs.

Canvas conventions (inherited from the R originals):
  - Axes: x ∈ [-100, 100], y ∈ [-100, 100]  →  perfect square
  - Background: solid black
  - Title area: y ∈ [bright_y, 100]  (covered by a solid black rect)
  - Date area:  y ∈ [-100, -75] (covered by a solid black rect)
  - Decorative horizontal lines:
      • dim line  — at y = 71, alpha = 0.3, only drawn for 1-line titles
      • bright line — at bottom of title block, alpha = 1.0
        (y = 71 for 1-line, y = 50 for 2-line, y = 29 for 3-line title)

Figure: 6.667 × 6.667 in @ 300 DPI  →  ~2000 × 2000 px
"""

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

# ---------------------------------------------------------------------------
# Figure setup
# ---------------------------------------------------------------------------

def setup_figure(dpi: int = 300, bg_color: str = "black"):
    """
    Create a square, axis-fill figure with [-100, 100] coordinate space.
    Returns (fig, ax).
    """
    fig = plt.figure(figsize=(6.667, 6.667), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])          # fill entire figure — no margins
    ax.set_xlim(-100, 100)
    ax.set_ylim(-100, 100)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    # Explicit base rect so pattern code can always clip to it
    ax.add_patch(patches.Rectangle((-100, -100), 200, 200,
                                   color=bg_color, zorder=0))
    return fig, ax


# ---------------------------------------------------------------------------
# Title wrapping
# ---------------------------------------------------------------------------

_MAX_CHARS_PER_LINE = 18
_MAX_LINES = 3


def wrap_title(title: str, max_chars: int = _MAX_CHARS_PER_LINE,
               max_lines: int = _MAX_LINES) -> tuple[list[str], bool]:
    """
    Word-wrap *title* into at most *max_lines* lines of ≤ *max_chars* chars.
    Returns (lines, was_truncated).  was_truncated is True when words were
    dropped because the limit was reached.
    """
    words = title.split() if title else ["Playlist"]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    was_truncated = len(lines) > max_lines
    return lines[:max_lines], was_truncated


def _wrap_title(title: str, max_chars: int = _MAX_CHARS_PER_LINE) -> list[str]:
    """Internal helper — returns lines only (no truncation flag)."""
    lines, _ = wrap_title(title, max_chars=max_chars, max_lines=_MAX_LINES)
    return lines


# ---------------------------------------------------------------------------
# Standard overlay (title + date + decorative lines)
# ---------------------------------------------------------------------------

def draw_overlay(ax, title: str, date_str: str, color: str,
                 line_1: np.ndarray, bg_color: str = "black") -> None:
    """
    Draw the standardised title / date overlay on top of any pattern.
    Must be called *last* so it renders above everything else.

    Layout
    ------
    • Titles left-aligned; date right-aligned
    • 1-line:  bright_y = 71  — title at y = 85
    • 2-line:  bright_y = 50  — titles at y = 85, 65
    • 3-line:  bright_y = 29  — titles at y = 85, 65, 45
    • dim line at y = 71 only for 1-line titles (hidden for 2/3-line)
    • bright separator line at bright_y
    • bottom line at y = -75
    • Date right-aligned at y = -88
    """
    lines = _wrap_title(title)
    n = len(lines)
    if n == 1:
        bright_y = 71.0
    elif n == 2:
        bright_y = 50.0
    else:
        bright_y = 29.0

    # ── cover rectangles (use bg_color so they blend with the canvas) ────────
    # Title backdrop — bottom edge at bright_y
    ax.add_patch(patches.Rectangle((-100, bright_y), 200, 100 - bright_y,
                                   color=bg_color, alpha=1.0, zorder=10))
    # Date backdrop — strip at the bottom
    ax.add_patch(patches.Rectangle((-100, -100), 200, 25,
                                   color=bg_color, alpha=1.0, zorder=10))

    # ── decorative horizontal lines ─────────────────────────────────────────
    # Dim line only for 1-line titles (for 2/3-line it would bleed through
    # since the rect ends lower and the line is drawn above it in zorder)
    if n == 1:
        y_fill = np.full_like(line_1, 71.0)
        ax.plot(line_1, y_fill, color=color, linewidth=2, alpha=0.3, zorder=12)

    y_bright = np.full_like(line_1, bright_y)
    ax.plot(line_1, y_bright, color=color, linewidth=2, alpha=1.0, zorder=13)

    y_bottom = np.full_like(line_1, -75.0)
    ax.plot(line_1, y_bottom, color=color, linewidth=2, alpha=1.0, zorder=12)

    # ── title text ──────────────────────────────────────────────────────────
    ax.text(-95, 85, lines[0], color=color, fontsize=48,
            ha="left", va="center", clip_on=True, zorder=14)
    if n >= 2:
        ax.text(-95, 65, lines[1], color=color, fontsize=48,
                ha="left", va="center", clip_on=True, zorder=14)
    if n >= 3:
        ax.text(-95, 45, lines[2], color=color, fontsize=48,
                ha="left", va="center", clip_on=True, zorder=14)

    # ── date text ───────────────────────────────────────────────────────────
    ax.text(95, -88, date_str, color=color, fontsize=40,
            ha="right", va="center", clip_on=True, zorder=14)


# ---------------------------------------------------------------------------
# Export helper
# ---------------------------------------------------------------------------

def fig_to_bytes(fig, dpi: int = 300) -> bytes:
    """Save *fig* to a PNG byte-string and close it."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
