from __future__ import annotations

import io
import base64
from typing import List, Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import pandas as pd

from .cycle_detector import CycleInfo, get_oscillator_series
from .combination_analyzer import CombinationResult

# ── Dark theme colours ────────────────────────────────────────────────────────
BG = "#0d1117"
PANEL = "#161b22"
GRID = "#21262d"
TEXT = "#c9d1d9"
GREEN = "#3fb950"
GREEN_FILL = "#238636"
RED = "#f85149"
RED_FILL = "#da3633"
ORANGE = "#d29922"
BLUE = "#58a6ff"
PURPLE = "#bc8cff"
YELLOW = "#e3b341"
CYCLE_COLORS = [BLUE, ORANGE, PURPLE, GREEN, RED, YELLOW, "#79c0ff", "#ffa657"]

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor": PANEL,
    "axes.edgecolor": GRID,
    "axes.labelcolor": TEXT,
    "axes.titlecolor": TEXT,
    "xtick.color": TEXT,
    "ytick.color": TEXT,
    "grid.color": GRID,
    "text.color": TEXT,
    "legend.facecolor": PANEL,
    "legend.edgecolor": GRID,
    "legend.labelcolor": TEXT,
    "font.family": "DejaVu Sans",
})


def _phase_color(phase_state: str) -> str:
    return {"bullish": GREEN, "bearish": RED, "peak": ORANGE, "trough": ORANGE}.get(phase_state, TEXT)


def fig_to_base64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return encoded


# ── Cycle table figure ────────────────────────────────────────────────────────

def plot_cycle_table(cycles: List[CycleInfo]) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(9, max(4, 0.38 * len(cycles) + 1.2)))
    ax.set_facecolor(PANEL)
    fig.patch.set_facecolor(BG)
    ax.axis("off")

    cols = ["#", "Longueur", "Amplitude", "Force", "Stabilité", "Phase"]
    col_widths = [0.06, 0.18, 0.18, 0.14, 0.14, 0.14]
    col_x = [sum(col_widths[:i]) + 0.04 for i in range(len(col_widths))]
    header_y = 0.96

    for cx, label in zip(col_x, cols):
        ax.text(cx, header_y, label, transform=ax.transAxes, fontsize=9,
                color=TEXT, fontweight="bold", va="top")

    ax.plot([0.02, 0.98], [header_y - 0.035, header_y - 0.035], color=GRID, linewidth=1,
            transform=ax.transAxes, clip_on=False)

    row_h = (header_y - 0.05) / max(len(cycles), 1)

    for i, c in enumerate(cycles):
        y = header_y - 0.05 - i * row_h
        bg_color = "#1c2128" if i % 2 == 0 else PANEL
        bg_rect = mpatches.FancyBboxPatch(
            (0.01, y - row_h * 0.85), 0.98, row_h * 0.9,
            boxstyle="round,pad=0.002", linewidth=0,
            facecolor=bg_color, transform=ax.transAxes, clip_on=False,
        )
        ax.add_patch(bg_rect)

        phase_col = _phase_color(c.phase_state)
        badge_x = col_x[1] + 0.005
        badge_rect = mpatches.FancyBboxPatch(
            (badge_x, y - row_h * 0.65), 0.1, row_h * 0.65,
            boxstyle="round,pad=0.004", linewidth=0,
            facecolor=phase_col + "40", edgecolor=phase_col,
            transform=ax.transAxes, clip_on=True,
        )
        ax.add_patch(badge_rect)

        stab_bold = c.stability >= 0.5
        values = [
            str(c.rank),
            str(c.period),
            f"{c.amplitude:,.2f}",
            f"{c.strength:.2f}",
            f"{c.stability:.2f}",
            c.phase_state.capitalize(),
        ]
        colors_row = [TEXT, phase_col, TEXT, TEXT,
                      GREEN if stab_bold else TEXT, phase_col]
        weights = ["normal"] * 6
        if stab_bold:
            weights[4] = "bold"

        for cx, val, col, wt in zip(col_x, values, colors_row, weights):
            ax.text(cx, y - row_h * 0.25, val, transform=ax.transAxes,
                    fontsize=8.5, color=col, fontweight=wt, va="center")

    ax.set_title("Spectre des Cycles", color=TEXT, fontsize=11, fontweight="bold",
                 pad=8, loc="left")
    return fig


# ── Single cycle chart ────────────────────────────────────────────────────────

def plot_single_cycle(
    prices: np.ndarray,
    dates: pd.DatetimeIndex,
    cycle: CycleInfo,
    ticker: str = "",
) -> plt.Figure:
    fig = plt.figure(figsize=(12, 6), facecolor=BG)
    gs = GridSpec(2, 1, figure=fig, height_ratios=[2.5, 1], hspace=0.08)

    ax_price = fig.add_subplot(gs[0])
    ax_osc = fig.add_subplot(gs[1], sharex=ax_price)

    ax_price.set_facecolor(PANEL)
    ax_osc.set_facecolor(PANEL)

    N = len(prices)
    x = np.arange(N)

    # Price
    ax_price.plot(x, prices, color="#58a6ff", linewidth=1.2, zorder=2)

    # Oscillator
    osc = get_oscillator_series(prices, cycle.period)
    amp = cycle.amplitude_log

    # Bullish/Bearish zones from this cycle
    direction = np.gradient(osc)
    bullish = direction > 0

    # Shade zones on price chart
    i = 0
    while i < N:
        if bullish[i]:
            start = i
            while i < N and bullish[i]:
                i += 1
            end = i
            ax_price.axvspan(start, end, color=GREEN_FILL, alpha=0.12, zorder=1)
            ax_osc.axvspan(start, end, color=GREEN_FILL, alpha=0.15, zorder=1)
        else:
            start = i
            while i < N and not bullish[i]:
                i += 1
            end = i
            ax_price.axvspan(start, end, color=RED_FILL, alpha=0.08, zorder=1)
            ax_osc.axvspan(start, end, color=RED_FILL, alpha=0.10, zorder=1)

    ax_price.set_title(
        f"{ticker} — Cycle {cycle.period} barres  "
        f"| Amp: {cycle.amplitude:,.2f}  "
        f"| Force: {cycle.strength:.2f}  "
        f"| Stabilité: {cycle.stability:.2f}  "
        f"| Phase: {cycle.phase_state.capitalize()}",
        color=TEXT, fontsize=9.5, pad=6, loc="left",
    )
    ax_price.set_ylabel("Prix", fontsize=8.5)
    ax_price.grid(True, color=GRID, linewidth=0.5)
    ax_price.tick_params(labelbottom=False)

    # Draw oscillator normalized
    osc_norm = osc / (amp + 1e-10)
    ax_osc.plot(x, osc_norm, color=BLUE, linewidth=1.5, zorder=3, label=f"Oscillateur {cycle.period}")
    ax_osc.axhline(0, color=GRID, linewidth=1, zorder=2)
    ax_osc.axhline(1, color=GREEN, linewidth=0.7, linestyle="--", alpha=0.5, zorder=2)
    ax_osc.axhline(-1, color=RED, linewidth=0.7, linestyle="--", alpha=0.5, zorder=2)
    ax_osc.set_ylabel("Oscillateur", fontsize=8)
    ax_osc.grid(True, color=GRID, linewidth=0.5)

    # Date ticks
    _set_date_ticks(ax_osc, dates, N)

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig.tight_layout()
    return fig


# ── Combination chart ─────────────────────────────────────────────────────────

def plot_combination(
    prices: np.ndarray,
    dates: pd.DatetimeIndex,
    combo: CombinationResult,
    ticker: str = "",
) -> plt.Figure:
    n_cycles = len(combo.cycles)
    fig = plt.figure(figsize=(14, 5 + 1.2 * n_cycles), facecolor=BG)
    gs = GridSpec(1 + n_cycles, 1, figure=fig, height_ratios=[3] + [1] * n_cycles, hspace=0.08)

    ax_price = fig.add_subplot(gs[0])
    ax_price.set_facecolor(PANEL)

    N = len(prices)
    x = np.arange(N)

    ax_price.plot(x, prices, color="#c9d1d9", linewidth=1.0, zorder=2, alpha=0.9)

    # Fix ylim first so annotations are placed correctly
    ymax = prices.max() * 1.02
    ymin = prices.min() * 0.98
    ax_price.set_ylim(ymin, ymax)
    y_top = ymin + (ymax - ymin) * 0.985
    y_bot = ymin + (ymax - ymin) * 0.015

    # ── Shade bullish zones (green) ───────────────────────────────────────
    for zone in combo.zones:
        ax_price.axvspan(zone.start, zone.end, color=GREEN_FILL, alpha=0.22, zorder=1)
        if zone.duration >= 3:
            mid = (zone.start + zone.end) / 2
            col = GREEN if zone.return_pct >= 0 else RED
            ax_price.text(mid, y_top, f"{zone.return_pct:+.1f}%",
                          color=col, fontsize=7.5, ha="center", va="top",
                          fontweight="bold", zorder=5)

    # ── Shade bearish zones (red) ─────────────────────────────────────────
    for zone in combo.bearish_zones:
        ax_price.axvspan(zone.start, zone.end, color=RED_FILL, alpha=0.18, zorder=1)
        if zone.duration >= 3:
            mid = (zone.start + zone.end) / 2
            col = RED if zone.return_pct <= 0 else GREEN
            ax_price.text(mid, y_bot, f"{zone.return_pct:+.1f}%",
                          color=col, fontsize=7.5, ha="center", va="bottom",
                          fontweight="bold", zorder=5)

    periods_str = " + ".join(str(p) for p in combo.periods)
    bear_str = (f"  |  Baissier: {combo.bearish_total_return_pct:+.1f}% "
                f"({len(combo.bearish_zones)} zones)") if combo.bearish_zones else ""
    ax_price.set_title(
        f"{ticker} — Cycles {periods_str}  "
        f"| Haussier: {combo.total_return_pct:+.1f}% · {combo.hit_rate:.0f}% réussite · {combo.n_zones} zones"
        f"{bear_str}",
        color=TEXT, fontsize=9, pad=6, loc="left",
    )
    ax_price.set_ylabel("Prix", fontsize=8.5)
    ax_price.grid(True, color=GRID, linewidth=0.5)
    ax_price.tick_params(labelbottom=False)

    # ── Individual oscillators below ──────────────────────────────────────
    for ci, cycle in enumerate(combo.cycles):
        ax = fig.add_subplot(gs[1 + ci], sharex=ax_price)
        ax.set_facecolor(PANEL)
        col = CYCLE_COLORS[ci % len(CYCLE_COLORS)]

        osc = get_oscillator_series(prices, cycle.period)
        osc_norm = osc / (cycle.amplitude_log + 1e-10)

        ax.plot(x, osc_norm, color=col, linewidth=1.5, zorder=3)
        ax.axhline(0, color=GRID, linewidth=1, zorder=2)

        bull = np.gradient(osc) > 0
        ax.fill_between(x, osc_norm, 0, where=bull, color=GREEN, alpha=0.25, zorder=1)
        ax.fill_between(x, osc_norm, 0, where=~bull, color=RED, alpha=0.20, zorder=1)

        ax.set_ylabel(f"{cycle.period}b", fontsize=8, color=col)
        ax.grid(True, color=GRID, linewidth=0.4)

        if ci < n_cycles - 1:
            ax.tick_params(labelbottom=False)
        else:
            _set_date_ticks(ax, dates, N)

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig.tight_layout()
    return fig


# ── Spectral power chart ──────────────────────────────────────────────────────

def plot_power_spectrum(prices: np.ndarray, cycles: List[CycleInfo]) -> plt.Figure:
    from .cycle_detector import _detrend_log

    fig, ax = plt.subplots(figsize=(11, 3.5), facecolor=BG)
    ax.set_facecolor(PANEL)

    N = len(prices)
    detrended, _ = _detrend_log(prices)
    win = np.hanning(N)
    fft = np.fft.rfft(detrended * win)
    freqs = np.fft.rfftfreq(N)
    power = np.abs(fft[1:]) ** 2
    periods = 1.0 / freqs[1:]

    valid = (periods >= 5) & (periods <= N // 2)
    ax.plot(periods[valid], power[valid], color=BLUE, linewidth=1.0, alpha=0.8)
    ax.fill_between(periods[valid], power[valid], color=BLUE, alpha=0.15)

    for c in cycles[:8]:
        col = _phase_color(c.phase_state)
        ax.axvline(c.period, color=col, linewidth=1.2, linestyle="--", alpha=0.8)
        ax.text(c.period, ax.get_ylim()[1] * 0.9, str(c.period),
                color=col, fontsize=7, ha="center", va="top", rotation=90)

    ax.set_xlabel("Période (barres)", fontsize=8.5)
    ax.set_ylabel("Puissance", fontsize=8.5)
    ax.set_title("Spectre de Puissance", color=TEXT, fontsize=10, fontweight="bold", loc="left")
    ax.grid(True, color=GRID, linewidth=0.4, alpha=0.6)
    ax.set_xlim(left=4)

    fig.tight_layout()
    return fig


# ── Helper ─────────────────────────────────────────────────────────────────────

def _set_date_ticks(ax: plt.Axes, dates: pd.DatetimeIndex, N: int, n_ticks: int = 8) -> None:
    step = max(1, N // n_ticks)
    tick_pos = list(range(0, N, step))
    tick_labels = [dates[i].strftime("%b %Y") if i < len(dates) else "" for i in tick_pos]
    ax.set_xticks(tick_pos)
    ax.set_xticklabels(tick_labels, fontsize=7.5, rotation=20, ha="right")
