#!/usr/bin/env python3
"""PRÉVISUALISATION d'une calibration : cycles réguliers ANCRÉS, objectif LONG-SHORT.

Différence clé avec le détecteur actuel : au lieu de maximiser SEULEMENT le
rendement de la hausse (ce qui décale la baisse), on maximise à la fois :
  - le rendement de la phase HAUSSE (elle doit monter), ET
  - le gain d'un short pendant la phase BAISSE (elle doit vraiment baisser).
=> la phase baissière se cale sur les VRAIS krachs (ex. BTC nov.2021→nov.2022).

Le cycle reste RÉGULIER (U hausse / D baisse fixes, période P=U+D) et ANCRÉ sur
un vrai creux (rien avant). On sort les TOP N cycles simples en images.

Env : TICKER, START, TOPN (défaut 5). Ne modifie pas le vrai logiciel.
Tourne sur GitHub Actions.
"""
import os
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from scipy.signal import find_peaks

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import detect_cycles

GREEN, RED, BG, FG = "#238636", "#da3633", "#0d1117", "#c9d1d9"


def _runs(mask):
    out, N, i = [], len(mask), 0
    while i < N:
        if mask[i]:
            s = i
            while i < N and mask[i]:
                i += 1
            out.append((s, i - 1))
        else:
            i += 1
    return out


def _pct(prices, s, e):
    return (prices[e] - prices[s]) / prices[s] * 100.0


def _troughs(prices, min_sep):
    idx, _ = find_peaks(-np.asarray(prices, float), distance=max(3, int(min_sep)))
    cand = list(idx)
    head = int(np.argmin(prices[:max(2, min_sep)]))
    if head not in cand:
        cand = [head] + cand
    return sorted(set(cand))


def detect_anchored_ls(prices, P, u_lo=0.30, u_hi=0.88):
    """Cycle régulier ancré, objectif LONG-SHORT. Cherche (U, ancrage) qui
    maximise (rdt hausse + gain short baisse), les deux devant être fiables.
    Retourne dict ou None."""
    N = len(prices)
    anchors = _troughs(prices, min_sep=max(5, P // 4))
    lo, hi = int(P * u_lo), int(P * u_hi)
    step = max(1, P // 80)
    best = None
    for U in range(lo, hi + 1, step):
        D = P - U
        for a in anchors:
            up = np.zeros(N, dtype=bool)
            k = 0
            while a + k * P < N:
                s = a + k * P
                up[s:min(N, s + U)] = True
                k += 1
            up_runs = [(s, e) for s, e in _runs(up) if e > s]
            dn = (~up).copy()
            dn[:a] = False
            dn_runs = [(s, e) for s, e in _runs(dn) if e > s]
            up_full = [r for r in up_runs if r[0] >= a and (r[1] - r[0] + 1) >= U - 1]
            if len(up_full) < 2 or len(dn_runs) < 2:
                continue
            up_ret = sum(_pct(prices, s, e) for s, e in up_full)
            dn_gain = sum(-_pct(prices, s, e) for s, e in dn_runs)      # gain short
            up_hit = 100.0 * sum(1 for s, e in up_full if prices[e] > prices[s]) / len(up_full)
            dn_hit = 100.0 * sum(1 for s, e in dn_runs if prices[e] < prices[s]) / len(dn_runs)
            # Objectif : les deux jambes rapportent, pondéré par la fiabilité MINIMALE.
            val = (up_ret + dn_gain) * (min(up_hit, dn_hit) / 100.0)
            if best is None or val > best["val"]:
                best = dict(val=val, U=U, D=D, anchor=a, up_ret=up_ret, dn_gain=dn_gain,
                            up_hit=up_hit, dn_hit=dn_hit, up=up.copy())
    return best


def _candidate_periods(prices):
    N = len(prices)
    cyc = detect_cycles(prices, min_period=15, max_period=N // 2)
    periods = {int(round(c.period)) for c in cyc}
    # Bande « halving » BTC ~3.5-4.5 ans pour ne pas rater le grand cycle.
    for p in range(1150, 1600, 40):
        if p < N // 2:
            periods.add(p)
    return sorted(periods)


def _draw(ax, dates, prices, best, title):
    N = len(prices)
    a = best["anchor"]
    up = best["up"].copy()
    up[:a] = False
    dn = (~best["up"]).copy(); dn[:a] = False
    ax.set_facecolor(BG)
    ax.plot(dates, prices, color="#58a6ff", lw=0.9)
    if a > 0:
        ax.axvspan(dates[0], dates[a], color="#8b949e", alpha=0.10)
        ax.axvline(dates[a], color="#8b949e", ls=":", lw=0.8)
    for s, e in _runs(up):
        ax.axvspan(dates[s], dates[e], color=GREEN, alpha=0.16)
        ax.text(dates[(s + e) // 2], prices.max() * 0.98, f"↑{_pct(prices, s, e):+.0f}%",
                color=GREEN, fontsize=6, ha="center", va="top")
    for s, e in _runs(dn):
        ax.axvspan(dates[s], dates[e], color=RED, alpha=0.14)
        # date de début/fin de la plus grosse baisse pour vérifier le calage
        ax.text(dates[(s + e) // 2], prices.min(),
                f"{dates[s].strftime('%d/%m/%y')}→{dates[e].strftime('%d/%m/%y')}",
                color="#f85149", fontsize=5, ha="center", va="bottom")
    ax.set_title(title, color=FG, fontsize=9, loc="left")
    ax.tick_params(colors=FG, labelsize=7)
    for sp in ax.spines.values():
        sp.set_color("#30363d")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def main():
    ticker = os.environ.get("TICKER", "BTC-USD").upper()
    start = os.environ.get("START") or None
    topn = int(os.environ.get("TOPN", "5"))

    data = fetch_data(ticker, period="15y", interval="1d", start=start)
    prices = get_close_prices(data)
    dates = get_dates(data)
    print(f"{ticker} | {len(prices)} barres | start {start}")

    results = []
    for P in _candidate_periods(prices):
        b = detect_anchored_ls(prices, P)
        if b is None:
            continue
        b["P"] = P
        results.append(b)
    results.sort(key=lambda b: b["val"], reverse=True)

    # Déduplication : périodes proches (<12%) → on garde la meilleure.
    kept = []
    for b in results:
        if any(abs(b["P"] - k["P"]) <= 0.12 * max(b["P"], k["P"]) for k in kept):
            continue
        kept.append(b)
        if len(kept) >= topn:
            break

    outdir = Path("graphs")
    outdir.mkdir(exist_ok=True)
    print(f"TOP {len(kept)} cycles réguliers ancrés (objectif long-short) :")
    for i, b in enumerate(kept, 1):
        d = dates[b["anchor"]].strftime("%d/%m/%Y")
        print(f"  #{i} P={b['P']}b ↑{b['U']}/↓{b['D']} · début {d} · "
              f"hausse {b['up_ret']:+.0f}% (réu {b['up_hit']:.0f}%) · "
              f"short {b['dn_gain']:+.0f}% (réu {b['dn_hit']:.0f}%)")
        fig, ax = plt.subplots(figsize=(16, 4.5))
        fig.patch.set_facecolor(BG)
        title = (f"{ticker} #{i} — cycle {b['P']}b  ↑{b['U']} hausse / ↓{b['D']} baisse  ·  "
                 f"débute {d}  ·  hausse {b['up_ret']:+.0f}% / short {b['dn_gain']:+.0f}%  "
                 f"(réu ↑{b['up_hit']:.0f}% / ↓{b['dn_hit']:.0f}%)")
        _draw(ax, dates, prices, b, title)
        fig.tight_layout()
        out = outdir / f"{ticker}_ancre_{i:02d}_{b['P']}_U{b['U']}_D{b['D']}.png"
        fig.savefig(out, dpi=130, bbox_inches="tight", facecolor=BG)
        print(f"     -> {out}")


if __name__ == "__main__":
    main()
