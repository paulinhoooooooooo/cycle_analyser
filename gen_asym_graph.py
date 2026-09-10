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
from cycle_analyzer.visualizer import plot_single_cycle

ticker = os.environ.get("TICKER", "CAT").upper()
start = os.environ.get("START") or None
period = int(os.environ.get("PERIOD", "179"))

data = fetch_data(ticker, period="10y", interval="1d", start=start)
prices = get_close_prices(data)
dates = get_dates(data)
print(f"{ticker} | {len(prices)} barres | start {start} | période {period}")

r = detect_asym_cycle(prices, period)
if r is None:
    print("Aucun cycle asymétrique exploitable pour cette période.")
    sys.exit(1)
U, D, phi, mask, val = r

ci = CycleInfo(
    period=period, period_exact=float(period), amplitude=0.0, strength=0.0,
    stability=0.0, phase_state="", current_value=0.0, current_direction=0.0,
    oscillator=np.array([]), r_squared=0.0, amplitude_log=0.0,
    coeff_a=0.0, coeff_b=0.0, bull_mask=mask, asym=(U, D, phi),
)
cr = _build_combo(prices, [ci])
if cr is not None:
    ci.hit_rate = float(cr.hit_rate)
    ci.short_hit_rate = float(cr.bearish_hit_rate)
    print(f"U={U} D={D} | rdt {cr.total_return_pct:+.0f}% | "
          f"{cr.n_zones} zones | réussite {cr.hit_rate:.0f}%")

fig = plot_single_cycle(prices, dates, ci, ticker)
outdir = Path("graphs")
outdir.mkdir(exist_ok=True)
out = outdir / f"{ticker}_{period}_asym_U{U}_D{D}.png"
fig.savefig(out, dpi=130, bbox_inches="tight", facecolor="#0d1117")
print(f"Graphique sauvegardé : {out.resolve()}")
