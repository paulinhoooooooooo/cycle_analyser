#!/usr/bin/env python3
"""Génère le graphique d'UN cycle ASYMÉTRIQUE et le sauvegarde en PNG.

Sert à VÉRIFIER visuellement le rendu des cycles asymétriques (--asym).
Env : TICKER, START (JJ/MM/AAAA), PERIOD (période du cycle à afficher).
Le meilleur découpage hausse/baisse de cette période est détecté puis tracé.
Tourne sur GitHub Actions (accès Yahoo + matplotlib).
"""
import os
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import detect_asym_cycle, CycleInfo
from cycle_analyzer.combination_analyzer import _build_combo
from cycle_analyzer.visualizer import plot_single_cycle, plot_combination


def _asym_ci(prices, period):
    r = detect_asym_cycle(prices, period)
    if r is None:
        return None
    U, D, phi, mask, val = r
    return CycleInfo(
        period=period, period_exact=float(period), amplitude=0.0, strength=0.0,
        stability=0.0, phase_state="", current_value=0.0, current_direction=0.0,
        oscillator=np.array([]), r_squared=0.0, amplitude_log=0.0,
        coeff_a=0.0, coeff_b=0.0, bull_mask=mask, asym=(U, D, phi),
    )


ticker = os.environ.get("TICKER", "CAT").upper()
start = os.environ.get("START") or None
periods = [int(p.strip()) for p in os.environ.get("PERIOD", "179").replace(" ", "").split(",")]

data = fetch_data(ticker, period="10y", interval="1d", start=start)
prices = get_close_prices(data)
dates = get_dates(data)
print(f"{ticker} | {len(prices)} barres | start {start} | périodes {periods}")

cis = [_asym_ci(prices, p) for p in periods]
if any(c is None for c in cis):
    print("Aucun cycle asymétrique exploitable pour au moins une période.")
    sys.exit(1)

outdir = Path("graphs")
outdir.mkdir(exist_ok=True)

if len(cis) == 1:
    ci = cis[0]
    cr = _build_combo(prices, [ci])
    if cr is not None:
        ci.hit_rate = float(cr.hit_rate)
        ci.short_hit_rate = float(cr.bearish_hit_rate)
        print(f"asym {ci.asym} | rdt {cr.total_return_pct:+.0f}% | "
              f"{cr.n_zones} zones | réussite {cr.hit_rate:.0f}%")
    fig = plot_single_cycle(prices, dates, ci, ticker)
    lab = f"{ci.period}_U{ci.asym[0]}_D{ci.asym[1]}"
else:
    cr = _build_combo(prices, cis)
    if cr is None:
        print("Combinaison dégénérée.")
        sys.exit(1)
    print(f"combo {[c.asym for c in cis]} | rdt {cr.total_return_pct:+.0f}% | "
          f"{cr.n_zones} zones | réussite {cr.hit_rate:.0f}%")
    fig = plot_combination(prices, dates, cr, ticker)
    lab = "_".join(str(p) for p in periods) + "_combo"

out = outdir / f"{ticker}_{lab}_asym.png"
fig.savefig(out, dpi=130, bbox_inches="tight", facecolor="#0d1117")
print(f"Graphique sauvegardé : {out.resolve()}")
