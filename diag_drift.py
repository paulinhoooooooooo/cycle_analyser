#!/usr/bin/env python3
"""Diagnostic de DÉRIVE : suit la date prédite du prochain début haussier au fil
du temps (fige à des dates de référence successives) pour voir de combien elle
bouge en approchant de l'événement. Sert à choisir J-15 / J-30.

Env : TICKER, CYCLES, START, ASOF_START, ASOF_END, STEP (jours ouvrés).
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from send_digest import get_bull_status

ticker = os.environ.get("TICKER", "IYT").upper()
cycles = [int(x) for x in os.environ.get("CYCLES", "175").replace(" ", "").split(",")]
start = os.environ.get("START") or None
asof_start = os.environ.get("ASOF_START", "01/01/2025")
asof_end = os.environ.get("ASOF_END", "01/12/2025")
step = int(os.environ.get("STEP", "10"))

d0 = pd.to_datetime(asof_start, dayfirst=True)
d1 = pd.to_datetime(asof_end, dayfirst=True)
asofs = list(pd.bdate_range(d0, d1)[::step])

print(f"{ticker} | cycles {cycles} | start {start}")
print("Suivi de la date prédite du prochain DÉBUT HAUSSIER, fige à chaque 'as-of' :")
print(f"{'as-of':>12} | bull_now | prochain début haussier | dans (barres)")
print("-" * 64)
for a in asofs:
    af = a.strftime("%d/%m/%Y")
    try:
        st = get_bull_status(ticker, cycles, "5y", "1d", start=start, fige=af)
    except Exception as exc:
        print(f"{af:>12} | ERREUR : {exc}")
        continue
    if not st:
        print(f"{af:>12} | (données insuffisantes)")
        continue
    if st["bull_now"]:
        deb = st["start"].strftime("%d/%m/%Y") if st.get("start") else "-"
        print(f"{af:>12} |   OUI    | (déjà commencé le {deb})")
    else:
        est = st["est"].strftime("%d/%m/%Y") if st.get("est") else "-"
        print(f"{af:>12} |   non    | {est:>11}            | {st.get('bars')}")
