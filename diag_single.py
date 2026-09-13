#!/usr/bin/env python3
"""DIAGNOSTIC : pourquoi un cycle SEUL (taille 1) apparaît ou non pour un ticker.
Compare les cycles simples (results[1]) selon les options (--bilateral, --reussite).
Env : TICKER (déf ANTO.L), START (JJ/MM/AAAA ou vide=15y), NEAR (période cible, déf 540)."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cycle_analyzer.data_fetcher import fetch_data, get_close_prices
from cycle_analyzer.cycle_detector import detect_cycles
from cycle_analyzer.combination_analyzer import analyze_combinations

ticker = os.environ.get("TICKER", "ANTO.L").upper()
start = os.environ.get("START") or None
target = float(os.environ.get("NEAR", "540"))

data = fetch_data(ticker, period="15y", interval="1d", start=start)
prices = get_close_prices(data)
n = len(prices)
cycles = detect_cycles(prices, min_period=15, max_period=min(1600, n // 2))
print(f"{ticker} | {n} barres | start={start} | {len(cycles)} cycles FFT détectés")


def show(mode, **kw):
    res = analyze_combinations(prices, cycles, top_n_per_size=5, asym=True, **kw)
    singles = res.get(1) or []
    print(f"\n=== {mode} — {len(singles)} cycles SIMPLES (results[1]) ===")
    for cr in singles:
        c = cr.cycles[0]
        a = getattr(c, "asym", None)
        lab = f"{c.period}b ↑{a[0]}/↓{a[1]}" if a else f"{c.period}b"
        print(f"  {lab:18} Long {cr.total_return_pct:+6.0f}% ({cr.hit_rate:3.0f}%, {cr.n_zones}z)"
              f"  Short {-cr.bearish_total_return_pct:+6.0f}% ({cr.bearish_hit_rate:3.0f}%, {len(cr.bearish_zones)}z)")
    near = [cr for cr in singles if any(abs(c.period - target) <= 30 for c in cr.cycles)]
    print(f"  --> cycle ~{target:.0f} SEUL présent ? {'OUI' if near else 'NON'}")


show("SCAN (--asym --bilateral, aucun filtre)", both_sides=True)
show("RAPPORT DEFAUT (--asym seul)", both_sides=False)
show("RAPPORT (--asym --bilateral --reussite 90)", both_sides=True, min_hit=90.0)
show("RAPPORT (--asym --reussite 90)", both_sides=False, min_hit=90.0)
print("\nTerminé.")
