#!/usr/bin/env python3
"""DIAGNOSTIC : montre le pool de cycles et le classement des combos pour un
ticker, afin de comprendre pourquoi tel combo (ex. 80+177) apparaît ou non.
Env : TICKER, START. Ne modifie rien."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices
from cycle_analyzer.cycle_detector import detect_cycles, build_anchored_pool
from cycle_analyzer.combination_analyzer import (
    analyze_combinations, compute_single_cycle_hit_rates, _build_combo,
)

ticker = os.environ.get("TICKER", "ITW").upper()
start = os.environ.get("START") or None
data = fetch_data(ticker, period="15y", interval="1d", start=start)
prices = get_close_prices(data)
N = len(prices)
print(f"{ticker} | {N} barres | start {start}\n")

# Pool CLASSIQUE (FFT + scan), comme dans analyze_combinations
cyc = detect_cycles(prices, min_period=10, max_period=None)
for c in cyc:
    c.hit_rate, c.short_hit_rate = compute_single_cycle_hit_rates(prices, c.period)
classic_periods = sorted({c.period for c in cyc})
print(f"Périodes CLASSIQUES détectées ({len(classic_periods)}): {classic_periods}")
print("  80 présent ?", 80 in classic_periods, "| ~177 présent ?",
      any(170 <= p <= 184 for p in classic_periods),
      "->", [p for p in classic_periods if 170 <= p <= 184])

# Pool ANCRÉ (hausse seule), périodes = classiques + bande longue
_cap = N // 2
periods = set(classic_periods)
for p in range(300, N // 2 + 1, 60):
    periods.add(p)
anch = build_anchored_pool(prices, sorted(periods), per_bucket=5, max_add=16)
print(f"\nCycles ANCRÉS retenus ({len(anch)}):")
for c in anch:
    print(f"   {c.period}b ↑{c.asym[0]}/↓{c.asym[1]} (ancre {c.active_start})")

# Combo 80+177 CLASSIQUE : le construit-on, et que vaut-il ?
def _find(p):
    cand = [c for c in cyc if abs(c.period - p) <= 4]
    return min(cand, key=lambda c: abs(c.period - p)) if cand else None
c80, c177 = _find(80), _find(177)
print("\n--- Combo CLASSIQUE 80+177 (symétrique) ---")
if c80 and c177:
    cr = _build_combo(prices, [c80, c177])
    if cr:
        print(f"   {c80.period}+{c177.period} : rdt {cr.total_return_pct:+.0f}% · "
              f"{cr.n_zones} zones · réussite {cr.hit_rate:.0f}%")
    else:
        print("   combo dégénéré")
else:
    print(f"   introuvable dans le pool (80={c80 is not None}, 177={c177 is not None})")

# Classement des paires par rendement (asym=True, hausse seule)
res = analyze_combinations(prices, cyc, top_n_per_size=5, asym=True)
print("\n--- results (asym) : cycles simples et paires proposés ---")
for k in (1, 2, 3):
    for cr in res.get(k, [])[:6]:
        print(f"   size{k}: {cr.label:28} rdt {cr.total_return_pct:+.0f}% · "
              f"{cr.n_zones} zones · {cr.hit_rate:.0f}%")
