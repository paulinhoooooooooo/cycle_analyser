#!/usr/bin/env python3
"""Diagnostic : pour un ticker, montre la date de cycle calculée selon la date `fige`.

Usage (via workflow) : TICKER=UI CYCLES=147 START=14/10/2011 python diag_cycle.py
Affiche, pour plusieurs dates de référence, ce que le logiciel calcule (bull_now,
début, prochaine transition). Sert à choisir la bonne date `fige`.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from send_digest import get_bull_status

ticker = os.environ.get("TICKER", "UI").upper()
cycles = [int(x) for x in os.environ.get("CYCLES", "147").replace(" ", "").split(",")]
start = os.environ.get("START") or None
figes = os.environ.get("FIGES", ",05/08/2026,08/08/2026,10/08/2026,12/08/2026,15/08/2026,18/08/2026").split(",")

print(f"Ticker {ticker} | cycles {cycles} | start {start}")
print(f"{'fige':>12} | bull_now | début_cycle | prochaine_transition (dans Nb) | fin")
for f in figes:
    f = f.strip() or None
    st = get_bull_status(ticker, cycles, "5y", "1d", start=start, fige=f)
    if not st:
        print(f"{str(f):>12} | (échec)")
        continue
    bn = st["bull_now"]
    deb = st["start"].strftime("%d/%m/%Y") if st.get("start") else "-"
    est = st["est"].strftime("%d/%m/%Y") if st.get("est") else "-"
    fin = st["end_est"].strftime("%d/%m/%Y") if st.get("end_est") else "-"
    print(f"{str(f):>12} | {str(bn):>7} | {deb:>11} | {est} (dans {st.get('bars')}b) | {fin}")
