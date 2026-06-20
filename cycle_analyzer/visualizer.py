from __future__ import annotations

import io
import base64
from typing import List, Optional, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import pandas as pd

from .cycle_detector import CycleInfo, get_oscillator_series, get_bullish_mask
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


# ── Next-event helpers ────────────────────────────────────────────────────────

def _bars_to_next_transition(A: float, B: float, T: float, N: int) -> Tuple[int, str]:
    """Bars from last data point until the cycle changes direction (pic or creux)."""
    phi = np.arctan2(A, B)
    t_last = float(N - 1)
    curr_sign = 1 if np.cos(2 * np.pi * t_last / T + phi) >= 0 else -1
    for k in range(1, int(2 * T) + 4):
        new_sign = 1 if np.cos(2 * np.pi * (t_last + k) / T + phi) >= 0 else -1
        if new_sign != curr_sign:
            return k, ("pic" if curr_sign == 1 else "creux")
    return max(1, int(T // 2)), "pic"


def _next_combo_alignments(
    cycles: List[CycleInfo], N: int, max_bars: int = 3000
) -> Tuple[Optional[int], Optional[int]]:
    """Return (bars_to_next_bull_start, bars_to_next_bear_start) from last bar."""
    def state_at(t: float):
        bull = bear = True
        for c in cycles:
            phi = np.arctan2(c.coeff_a, c.coeff_b)
            d = np.cos(2 * np.pi * t / c.period + phi)
            if d < 0:
                bull = False
            if d >= 0:
                bear = False
        return bull, bear

    t_last = float(N - 1)
    prev_bull, prev_bear = state_at(t_last)
    next_bull: Optional[int] = None
    next_bear: Optional[int] = None

    for k in range(1, max_bars + 1):
        b, e = state_at(t_last + k)
        if b and not prev_bull and next_bull is None:
            next_bull = k
        if e and not prev_bear and next_bear is None:
            next_bear = k
        prev_bull, prev_bear = b, e
        if next_bull is not None and next_bear is not None:
            break

    return next_bull, next_bear


def _future_date_str(dates: pd.DatetimeIndex, bars_ahead: int) -> str:
    avg_days = (dates[-1] - dates[0]).days / max(len(dates) - 1, 1)
    future = dates[-1] + pd.Timedelta(days=int(round(bars_ahead * avg_days)))
    return future.strftime("%d/%m/%Y")


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

    ax_price.plot(x, prices, color="#58a6ff", linewidth=1.2, zorder=2)

    osc = get_oscillator_series(prices, cycle.period)
    amp = cycle.amplitude_log
    bullish = get_bullish_mask(prices, cycle.period)

    # Set ylim before annotating so text positions are correct
    ymax = prices.max() * 1.02
    ymin = prices.min() * 0.98
    ax_price.set_ylim(ymin, ymax)
    y_top = ymin + (ymax - ymin) * 0.985
    y_bot = ymin + (ymax - ymin) * 0.015

    bull_simple = 0.0
    bear_simple = 0.0
    bull_cmp = 1.0
    bear_cmp = 1.0

    i = 0
    while i < N:
        if bullish[i]:
            start = i
            while i < N and bullish[i]:
                i += 1
            zone_end = i
            last_idx = i - 1
            ax_price.axvspan(start, zone_end, color=GREEN_FILL, alpha=0.12, zorder=1)
            ax_osc.axvspan(start, zone_end, color=GREEN_FILL, alpha=0.15, zorder=1)
            if last_idx > start:
                ret = (prices[last_idx] - prices[start]) / prices[start] * 100
                bull_simple += ret
                bull_cmp *= 1 + ret / 100
                if last_idx - start + 1 >= 3:
                    mid = (start + last_idx) / 2
                    col = GREEN if ret >= 0 else RED
                    ax_price.text(mid, y_top, f"{ret:+.1f}%",
                                  color=col, fontsize=7, ha="center", va="top",
                                  fontweight="bold", zorder=5)
        else:
            start = i
            while i < N and not bullish[i]:
                i += 1
            zone_end = i
            last_idx = i - 1
            ax_price.axvspan(start, zone_end, color=RED_FILL, alpha=0.08, zorder=1)
            ax_osc.axvspan(start, zone_end, color=RED_FILL, alpha=0.10, zorder=1)
            if last_idx > start:
                ret = (prices[last_idx] - prices[start]) / prices[start] * 100
                bear_simple += ret
                bear_cmp *= 1 + ret / 100
                if last_idx - start + 1 >= 3:
                    mid = (start + last_idx) / 2
                    col = RED if ret <= 0 else GREEN
                    ax_price.text(mid, y_bot, f"{ret:+.1f}%",
                                  color=col, fontsize=7, ha="center", va="bottom",
                                  fontweight="bold", zorder=5)

    bull_compound = (bull_cmp - 1) * 100
    bear_compound = (bear_cmp - 1) * 100

    ax_price.set_title(
        f"{ticker} — Cycle {cycle.period} barres  "
        f"| Amp: {cycle.amplitude:,.2f}  | Force: {cycle.strength:.2f}  "
        f"| Stabilité: {cycle.stability:.2f}  "
        f"| ↑ {bull_simple:+.1f}% (Σ) / {bull_compound:+.1f}% (composé)"
        f"  | ↓ {bear_simple:+.1f}% (Σ) / {bear_compound:+.1f}% (composé)",
        color=TEXT, fontsize=9, pad=6, loc="left",
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

    # ── Next reversal vertical marker ─────────────────────────────────────────
    bars_ahead, event_type = _bars_to_next_transition(
        cycle.coeff_a, cycle.coeff_b, float(cycle.period), N
    )
    next_x = (N - 1) + bars_ahead
    event_color = RED if event_type == "pic" else GREEN
    event_label = "Pic ↓" if event_type == "pic" else "Creux ↑"
    date_str = _future_date_str(dates, bars_ahead)

    # Extend x-axis to show the future marker
    pad = max(5, int(cycle.period * 0.12))
    ax_price.set_xlim(0, next_x + pad)
    ax_osc.set_xlim(0, next_x + pad)

    # Draw future oscillator as dashed extension
    t_fut = np.arange(N - 1, next_x + pad + 1, dtype=float)
    A_c, B_c = cycle.coeff_a, cycle.coeff_b
    amp_c = cycle.amplitude_log
    fut_osc_norm = (
        A_c * np.cos(2 * np.pi * t_fut / cycle.period)
        + B_c * np.sin(2 * np.pi * t_fut / cycle.period)
    ) / (amp_c + 1e-10)
    ax_osc.plot(t_fut, fut_osc_norm, color=BLUE, linewidth=1.0,
                linestyle="--", alpha=0.45, zorder=3)

    # Vertical lines
    ax_price.axvline(next_x, color=event_color, linewidth=1.4,
                     linestyle="--", alpha=0.85, zorder=5)
    ax_osc.axvline(next_x, color=event_color, linewidth=1.4,
                   linestyle="--", alpha=0.85, zorder=5)

    # Annotation on price panel
    y_mid = ymin + (ymax - ymin) * 0.50
    ax_price.text(
        next_x + pad * 0.15, y_mid,
        f"{event_label}\n{date_str}\n(dans {bars_ahead}b)",
        color=event_color, fontsize=7.5, ha="left", va="center",
        fontweight="bold", zorder=6,
        bbox=dict(boxstyle="round,pad=0.3", facecolor=PANEL,
                  edgecolor=event_color, alpha=0.85),
    )

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
    bear_str = (
        f"  |  ↓ {combo.bearish_total_return_pct:+.1f}% (Σ) / {combo.bearish_compound_return_pct:+.1f}% (composé)"
        f" · {len(combo.bearish_zones)} zones"
    ) if combo.bearish_zones else ""
    ax_price.set_title(
        f"{ticker} — Cycles {periods_str}  "
        f"| ↑ {combo.total_return_pct:+.1f}% (Σ) / {combo.compound_return_pct:+.1f}% (composé)"
        f" · {combo.hit_rate:.0f}% réussite · {combo.n_zones} zones"
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

        bull = get_bullish_mask(prices, cycle.period)
        ax.fill_between(x, osc_norm, 0, where=bull, color=GREEN, alpha=0.25, zorder=1)
        ax.fill_between(x, osc_norm, 0, where=~bull, color=RED, alpha=0.20, zorder=1)

        ax.set_ylabel(f"{cycle.period}b", fontsize=8, color=col)
        ax.grid(True, color=GRID, linewidth=0.4)

        if ci < n_cycles - 1:
            ax.tick_params(labelbottom=False)
        else:
            _set_date_ticks(ax, dates, N)

    # ── Next alignment markers ────────────────────────────────────────────────
    next_bull, next_bear = _next_combo_alignments(combo.cycles, N)

    x_max_extra = max(v for v in [next_bull, next_bear, 1] if v is not None)
    pad_combo = max(10, int(x_max_extra * 0.12))
    new_xlim = (0, N - 1 + x_max_extra + pad_combo)
    ax_price.set_xlim(*new_xlim)
    for ci in range(n_cycles):
        fig.axes[1 + ci].set_xlim(*new_xlim)

    def _add_combo_marker(ax_p, bars, col, label_txt, y_frac):
        if bars is None:
            return
        xv = N - 1 + bars
        date_s = _future_date_str(dates, bars)
        ax_p.axvline(xv, color=col, linewidth=1.4, linestyle="--", alpha=0.85, zorder=5)
        y_pos = ymin + (ymax - ymin) * y_frac
        ax_p.text(
            xv + pad_combo * 0.15, y_pos,
            f"{label_txt}\n{date_s}\n(dans {bars}b)",
            color=col, fontsize=7, ha="left", va="center", fontweight="bold", zorder=6,
            bbox=dict(boxstyle="round,pad=0.3", facecolor=PANEL,
                      edgecolor=col, alpha=0.85),
        )

    _add_combo_marker(ax_price, next_bull, GREEN, "↑ Alignement\nhaussier", 0.72)
    _add_combo_marker(ax_price, next_bear, RED,   "↓ Alignement\nbaissier", 0.28)

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
