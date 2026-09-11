#!/usr/bin/env python3
"""Génère UN graphique PNG par CYCLE SIMPLE du rapport (asym ou symétrique).

Rejoue la même détection/sélection que cycle_analyser.py (detect_cycles +
analyze_combinations) puis trace chaque cycle simple retenu (combinations[1])
avec le MÊME rendu que le rapport (plot_single_cycle). Sert à voir en image ce
que le rapport donne, sans ouvrir le HTML.

Env :
  TICKER   : ticker Yahoo
  START    : date de départ (JJ/MM/AAAA ou AAAA-MM-JJ), vide = période 15y
  ASYM     : "oui" pour activer les cycles asymétriques (--asym)
  REUSSITE : réussite minimum en % (comme --reussite), vide = aucun filtre
Tourne sur GitHub Actions (accès Yahoo + matplotlib).
"""
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import detect_cycles
from cycle_analyzer.combination_analyzer import (
    analyze_combinations, compute_single_cycle_hit_rates,
)
from cycle_analyzer.visualizer import plot_single_cycle


def _lab(ci):
    a = getattr(ci, "asym", None)
    return f"↑{a[0]}/↓{a[1]}" if a else "symétrique"


ticker = os.environ.get("TICKER", "CAT").upper()
start = os.environ.get("START") or None
asym = os.environ.get("ASYM", "non").strip().lower() in ("oui", "yes", "true", "1")
_re = os.environ.get("REUSSITE", "").strip()
min_hit = float(_re) if _re else None

data = fetch_data(ticker, period="15y", interval="1d", start=start)
prices = get_close_prices(data)
dates = get_dates(data)
print(f"{ticker} | {len(prices)} barres | start {start} | asym={asym} | reussite={min_hit}")

cycles = detect_cycles(prices, min_period=10, max_period=None)
for c in cycles:
    c.hit_rate, c.short_hit_rate = compute_single_cycle_hit_rates(prices, c.period)

combinations = analyze_combinations(
    prices, cycles, top_n_per_size=3,
    recency_halflife=None, min_hit=min_hit,
    min_zones=None, min_return=None, max_period=None,
    both_sides=False, asym=asym,
)

singles = combinations.get(1, [])
if not singles:
    print("Aucun cycle simple retenu."); sys.exit(1)

outdir = Path("graphs")
outdir.mkdir(exist_ok=True)
print(f"{len(singles)} cycle(s) simple(s) retenu(s) :")
for i, sc in enumerate(singles, 1):
    ci = sc.cycles[0]
    # Réussite affichée = celle du combo (comme le rapport)
    ci.hit_rate = float(sc.hit_rate)
    ci.short_hit_rate = float(sc.bearish_hit_rate)
    a = getattr(ci, "asym", None)
    tag = f"U{a[0]}_D{a[1]}" if a else "sym"
    print(f"  #{i} cycle {ci.period}b {_lab(ci)} · rdt {sc.total_return_pct:+.0f}% · "
          f"{sc.n_zones} zones · réussite {sc.hit_rate:.0f}%")
    fig = plot_single_cycle(prices, dates, ci, ticker)
    out = outdir / f"{ticker}_rapport_{i:02d}_{ci.period}_{tag}.png"
    fig.savefig(out, dpi=130, bbox_inches="tight", facecolor="#0d1117")
    print(f"     -> {out}")
