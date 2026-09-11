#!/usr/bin/env python3
"""DIAGNOSTIC ciblé : pourquoi 80+177 disparaît-il ? Compare SANS --asym
(comportement d'origine) et AVEC. Env : TICKER, START. Ne modifie rien."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices
from cycle_analyzer.cycle_detector import detect_cycles
from cycle_analyzer.combination_analyzer import (
    analyze_combinations, compute_single_cycle_hit_rates, _build_combo,
    _return_scan_pool,
)

ticker = os.environ.get("TICKER", "ITW").upper()
start = os.environ.get("START") or None
data = fetch_data(ticker, period="15y", interval="1d", start=start)
prices = get_close_prices(data)
N = len(prices)
print(f"{ticker} | {N} barres | start {start}\n")

cyc = detect_cycles(prices, min_period=10, max_period=None)
for c in cyc:
    c.hit_rate, c.short_hit_rate = compute_single_cycle_hit_rates(prices, c.period)

# Reconstitue le POOL symétrique EXACTEMENT comme analyze_combinations (FFT + scan)
seen, pool_sym = set(), []
for c in cyc[:30]:
    if c.period not in seen:
        pool_sym.append(c); seen.add(c.period)
    if len(pool_sym) >= 25:
        break
for c in _return_scan_pool(prices):
    if c.period not in seen:
        pool_sym.append(c); seen.add(c.period)
sym_periods = sorted(c.period for c in pool_sym)
print(f"POOL symétrique ({len(sym_periods)}): {sym_periods}")
print("  177 présent ?", 177 in sym_periods, "| 356 ?", 356 in sym_periods,
      "| 80 ?", 80 in sym_periods)

def _closest(pool, p):
    cand = sorted(pool, key=lambda c: abs(c.period - p))
    return cand[0] if cand else None

c80, c177 = _closest(pool_sym, 80), _closest(pool_sym, 177)
cr = _build_combo(prices, [c80, c177])
print(f"\nCombo direct {c80.period}+{c177.period} : "
      f"rdt {cr.total_return_pct:+.0f}% · {cr.n_zones} zones · réussite {cr.hit_rate:.0f}%")

def _show(res, tag):
    print(f"\n=== {tag} : top pairs (results[2]) ===")
    for c in res.get(2, [])[:10]:
        print(f"   {c.label:20} rdt {c.total_return_pct:+.0f}% · {c.n_zones} zones · {c.hit_rate:.0f}%")
    # 80+177 est-il présent dans results[2] ?
    def _has(c):
        ps = sorted(c.periods)
        return len(ps) == 2 and abs(ps[0]-80) <= 6 and abs(ps[1]-177) <= 6
    hit = [c for c in res.get(2, []) if _has(c)]
    print(f"   -> 80+177 dans results[2] ? {'OUI: '+hit[0].label if hit else 'NON'}")

res0 = analyze_combinations(prices, cyc, top_n_per_size=5, asym=False)
_show(res0, "SANS --asym (origine)")
res1 = analyze_combinations(prices, cyc, top_n_per_size=5, asym=True)
_show(res1, "AVEC --asym")
