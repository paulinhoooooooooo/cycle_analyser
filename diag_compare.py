#!/usr/bin/env python3
"""Compare plusieurs combinaisons de cycles pour un ticker (backtest réel).
Env : TICKER, START, DIRECTION, COMBOS (combos séparées par ';', cycles par ',').
Ex : TICKER=RS START=01/02/2016 COMBOS='178;80,180' python diag_compare.py
"""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from fill_watchlist_stats import compute_stats

ticker = os.environ.get("TICKER", "RS").upper()
start = os.environ.get("START") or None
direction = os.environ.get("DIRECTION", "long")
combos = [c for c in os.environ.get("COMBOS", "178;80,180").split(";") if c.strip()]

print(f"{ticker} | start {start} | direction {direction}")
print(f"{'combo':>12} | rendement | zones | réussite")
print("-" * 44)
for c in combos:
    periods = [int(x) for x in c.replace(" ", "").split(",")]
    try:
        s = compute_stats(ticker, periods, "5y", "1d", start, direction)
    except Exception as exc:
        print(f"{c:>12} | ERREUR : {exc}")
        continue
    if s is None:
        print(f"{c:>12} | combinaison dégénérée")
    else:
        print(f"{c:>12} | {s['rdt']:+7}% | {s['zones']:>4} | {s['reussite']:>5}%")
