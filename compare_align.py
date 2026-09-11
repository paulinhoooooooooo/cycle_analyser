#!/usr/bin/env python3
"""PRÉVISUALISATION du calage des cycles — ne modifie PAS le logiciel.

Génère un graphique comparatif à 3 volets pour UN cycle asymétrique :
  1. ACTUEL              : le cycle démarre au jour J (date de départ) ;
  2. ROGNAGE DU DÉBUT    : rien avant le 1er vrai début de cycle haussier ;
  3. ROGNAGE + CALAGE    : en plus, chaque frontière est recalée sur le vrai
                           plus-bas / plus-haut du prix (régimes plus nets).

Sert uniquement à COMPARER visuellement les options avant de choisir.
Env : TICKER, START (JJ/MM/AAAA ou AAAA-MM-JJ), PERIOD (période du cycle).
Tourne sur GitHub Actions (accès Yahoo + matplotlib).
"""
import os
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import detect_cycles, detect_asym_cycle, build_asym_pool

GREEN = "#238636"
RED = "#da3633"
BG = "#0d1117"
FG = "#c9d1d9"


def _asym_mask(N, P, U, phi):
    return ((np.arange(N) - phi) % P) < U


def _runs(mask):
    """Liste des segments contigus True : [(start, end_inclus), ...]."""
    out = []
    N = len(mask)
    i = 0
    while i < N:
        if mask[i]:
            s = i
            while i < N and mask[i]:
                i += 1
            out.append((s, i - 1))
        else:
            i += 1
    return out


def variant_actuel(mask):
    """Masque haussier tel quel + zone active dès l'indice 0."""
    return mask.copy(), 0


def variant_trim(mask):
    """Rogne le début : zone active seulement à partir du 1er front montant
    (1er passage baissier→haussier). Avant : rien n'est affiché."""
    m = mask.astype(bool)
    rising = np.where((~m[:-1]) & (m[1:]))[0]
    active = int(rising[0] + 1) if len(rising) else 0
    out = m.copy()
    out[:active] = False
    return out, active


def variant_snap(prices, U, D, phi, win_frac=0.10):
    """Rogne + recale chaque frontière sur le vrai extremum du prix :
    - un DÉBUT de hausse est glissé vers le plus-bas local le plus proche ;
    - une FIN de hausse (début de baisse) vers le plus-haut local le plus proche.
    Cycles alors légèrement irréguliers mais régimes bien plus nets."""
    N = len(prices)
    P = U + D
    win = max(5, int(round(P * win_frac)))

    def loc_min(c):
        lo, hi = max(0, c - win), min(N, c + win + 1)
        return lo + int(np.argmin(prices[lo:hi]))

    def loc_max(c):
        lo, hi = max(0, c - win), min(N, c + win + 1)
        return lo + int(np.argmax(prices[lo:hi]))

    bull_starts, bear_starts = [], []
    k = -1
    while True:
        bs = int(round(phi + k * P))
        pk = bs + U
        if bs >= N and pk >= N:
            break
        if 0 <= bs < N:
            bull_starts.append(bs)
        if 0 <= pk < N:
            bear_starts.append(pk)
        k += 1
        if k > N // max(P, 1) + 3:
            break

    snap_bull = sorted(set(loc_min(c) for c in bull_starts))
    snap_bear = sorted(set(loc_max(c) for c in bear_starts))

    mask = np.zeros(N, dtype=bool)
    for bs in snap_bull:
        nb = next((x for x in snap_bear if x > bs), N)
        mask[bs:nb] = True
    active = snap_bull[0] if snap_bull else 0
    return mask, active


def _pct(prices, s, e):
    return (prices[e] - prices[s]) / prices[s] * 100.0


def _draw(ax, dates, prices, mask, active, title):
    ax.set_facecolor(BG)
    ax.plot(dates, prices, color="#58a6ff", lw=0.9)
    # Zone grisée « inactive » avant le 1er cycle (rien n'y est calculé).
    if active > 0:
        ax.axvspan(dates[0], dates[active], color="#8b949e", alpha=0.10)
        ax.axvline(dates[active], color="#8b949e", ls=":", lw=0.8)
    bull = mask.copy()
    bull[:active] = False
    bear = (~mask)
    bear[:active] = False
    for s, e in _runs(bull):
        ax.axvspan(dates[s], dates[e], color=GREEN, alpha=0.16)
        ax.text(dates[(s + e) // 2], prices.max() * 0.97, f"↑{_pct(prices, s, e):+.0f}%",
                color=GREEN, fontsize=6, ha="center", va="top")
    for s, e in _runs(bear):
        ax.axvspan(dates[s], dates[e], color=RED, alpha=0.14)
    n_bull = len(_runs(bull))
    ax.set_title(title + f"   ({n_bull} zones haussières affichées)",
                 color=FG, fontsize=9, loc="left")
    ax.tick_params(colors=FG, labelsize=7)
    for sp in ax.spines.values():
        sp.set_color("#30363d")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def main():
    ticker = os.environ.get("TICKER", "BTC-USD").upper()
    start = os.environ.get("START") or None
    period_env = os.environ.get("PERIOD", "").strip()

    data = fetch_data(ticker, period="15y", interval="1d", start=start)
    prices = get_close_prices(data)
    dates = get_dates(data)
    N = len(prices)
    print(f"{ticker} | {N} barres | start {start}")

    # Période : imposée (PERIOD) sinon meilleur cycle asym auto-détecté.
    if period_env:
        period = int(period_env)
        r = detect_asym_cycle(prices, period)
        if r is None:
            print("Pas de cycle asym exploitable pour cette période."); sys.exit(1)
        U, D, phi, mask, _ = r
    else:
        cyc = detect_cycles(prices, min_period=15, max_period=N // 2)
        pool = build_asym_pool(prices, [c.period for c in cyc], max_add=14)
        if not pool:
            print("Aucun cycle asym trouvé."); sys.exit(1)
        # Meilleur par rendement haussier capturé (somme des zones).
        best = None
        for ci in pool:
            m = ci.bull_mask
            tot = sum(_pct(prices, s, e) for s, e in _runs(m))
            if best is None or tot > best[0]:
                best = (tot, ci)
        ci = best[1]
        U, D, phi = ci.asym
        period = ci.period
        mask = ci.bull_mask
    print(f"Cycle {period}b  ↑{U}/↓{D}  phi={phi}")

    variants = [
        ("1. ACTUEL — le cycle démarre au jour J", *variant_actuel(mask)),
        ("2. ROGNAGE — rien avant le 1er début de cycle haussier", *variant_trim(mask)),
        ("3. ROGNAGE + CALAGE sur les vrais creux/sommets", *variant_snap(prices, U, D, phi)),
    ]

    fig, axes = plt.subplots(3, 1, figsize=(16, 11), sharex=True)
    fig.patch.set_facecolor(BG)
    for ax, (title, m, active) in zip(axes, variants):
        _draw(ax, dates, prices, m, active, title)
    fig.suptitle(f"{ticker} — cycle {period}b ↑{U}/↓{D} · comparaison du calage des cycles",
                 color="#fff", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.98])

    outdir = Path("graphs")
    outdir.mkdir(exist_ok=True)
    out = outdir / f"{ticker}_align_compare.png"
    fig.savefig(out, dpi=130, bbox_inches="tight", facecolor=BG)
    print(f"Graphique comparatif sauvegardé : {out.resolve()}")


if __name__ == "__main__":
    main()
