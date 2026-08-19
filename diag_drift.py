#!/usr/bin/env python3
"""Diagnostic de DÉRIVE (corrigé) : simule qu'on est réellement à chaque 'as-of'
(données tronquées ET 'aujourd'hui' = cette date) et affiche le prochain début
haussier prédit alors. On voit ainsi de combien la date bouge en approchant.

Env : TICKER, CYCLES, START, ASOF_START, ASOF_END, STEP (jours ouvrés).
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from send_digest import _build_cycles, _state_at, _est_future_date

ticker = os.environ.get("TICKER", "IYT").upper()
cycles_list = [int(x) for x in os.environ.get("CYCLES", "175").replace(" ", "").split(",")]
start = os.environ.get("START") or None
asof_start = pd.to_datetime(os.environ.get("ASOF_START", "01/01/2025"), dayfirst=True)
asof_end = pd.to_datetime(os.environ.get("ASOF_END", "01/03/2026"), dayfirst=True)
step = int(os.environ.get("STEP", "7"))

data = fetch_data(ticker, period="10y", interval="1d", start=start)
prices_full = get_close_prices(data)
dates_full = get_dates(data)

# Mode auto : détecte le cycle LONG le plus fiable (>= 300 barres).
if os.environ.get("CYCLES", "").strip().lower() == "auto":
    from cycle_analyzer.cycle_detector import detect_cycles
    cands = detect_cycles(prices_full, min_period=250, max_period=1500, n_cycles=30)
    longs = [c for c in cands if c.period >= 300] or [c for c in cands if c.period >= 250]
    chosen = longs[0] if longs else cands[0]      # detect_cycles trie par stabilité desc
    cycles_list = [int(chosen.period)]
    print(f"Cycle long auto-détecté : {chosen.period} barres "
          f"(stabilité {chosen.stability:.2f}, force {chosen.strength:.2f})")

asofs = list(pd.bdate_range(asof_start, asof_end)[::step])

print(f"{ticker} | cycles {cycles_list} | start {start}")
print("Simule 'on est à cette date' → prochain début haussier prédit alors :")
print(f"{'as-of':>12} | état      | prochain début haussier | dans (barres)")
print("-" * 66)
for a in asofs:
    keep = np.asarray(dates_full <= a)
    n = int(keep.sum())
    if n < 200:
        print(f"{a.strftime('%d/%m/%Y'):>12} | (pas assez de données)")
        continue
    p = prices_full[:n]
    d = dates_full[:n]
    cyc = _build_cycles(p, cycles_list)
    t_last = float(n - 1)
    bull_now = _state_at(cyc, t_last)[0]
    af = a.strftime("%d/%m/%Y")
    if bull_now:
        j = n - 1
        while j - 1 >= 1 and _state_at(cyc, float(j - 1))[0]:
            j -= 1
        print(f"{af:>12} | EN CYCLE  | (commencé le {d[j].strftime('%d/%m/%Y')})")
    else:
        trans = []
        prev = bull_now
        for k in range(1, 400):
            s = _state_at(cyc, t_last + k)[0]
            if s != prev:
                trans.append(max(1, k - 1)); prev = s
                break
        if trans:
            est = _est_future_date(d, trans[0]).strftime("%d/%m/%Y")
            print(f"{af:>12} | pré-hausse| {est:>11}            | {trans[0]}")
        else:
            print(f"{af:>12} | pré-hausse| (aucun dans l'horizon)")
