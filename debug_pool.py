#!/usr/bin/env python3
"""DIAGNOSTIC phase : compare la phase du cycle (notif vs rapport) pour un ticker.
Env : TICKER, START, PERIOD (défaut 147). Ne modifie rien."""
import os, sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import (
    _detrend_log, _fit_sine, get_bullish_mask, detect_cycles,
)

ticker = os.environ.get("TICKER", "UI").upper()
start = os.environ.get("START") or None
P = int(os.environ.get("PERIOD", "147"))

data = fetch_data(ticker, period="15y", interval="1d", start=start)
prices = get_close_prices(data)
dates = get_dates(data)
N = len(prices)
print(f"{ticker} | {N} barres | {dates[0].date()} -> {dates[-1].date()} | période {P}\n")

# ── NOTIF : load_frozen → _osc_at avec la période ENTIÈRE P ──────────────────
detr, _ = _detrend_log(prices)
A, B, amp = _fit_sine(detr, float(P))

def osc_int(t):  # comme _osc_at dans check_alerts (période entière)
    return A * math.cos(2*math.pi*t/P) + B * math.sin(2*math.pi*t/P)

rise_now = osc_int(N-1) > osc_int(N-2)
print(f"NOTIF (147 ENTIER, ajusté depuis {start}) : "
      f"{'HAUSSIER' if rise_now else 'BAISSIER'} aujourd'hui")
j = N-1
while j-1 >= 1 and (osc_int(j-1) > osc_int(j-2)) == rise_now:
    j -= 1
print(f"   début de la phase actuelle : {dates[max(0,j)].date()}")

# ── RAPPORT : masque haussier get_bullish_mask (même période P) ──────────────
bm = get_bullish_mask(prices, P)
print(f"\nRAPPORT get_bullish_mask({P}) : "
      f"{'HAUSSIER' if bool(bm[-1]) else 'BAISSIER'} aujourd'hui")
k = N-1
while k-1 >= 0 and bool(bm[k-1]) == bool(bm[-1]):
    k -= 1
print(f"   début de la phase actuelle : {dates[max(0,k)].date()}")

# ── RAPPORT AUTO-DÉTECTÉ : période AFFINÉE proche de P ───────────────────────
cyc = detect_cycles(prices, min_period=max(10, P-40), max_period=P+60)
near = [c for c in cyc if abs(c.period - P) <= 8]
print(f"\nRAPPORT détecté (FFT) — cycles proches de {P} :")
if not near:
    print("   (aucun cycle détecté proche — le rapport montre alors un AUTRE cycle)")
for c in near:
    dir_txt = "HAUSSIER" if c.current_direction > 0 else "BAISSIER"
    print(f"   période {c.period} (exacte {c.period_exact:.2f}) → {dir_txt} "
          f"(phase_state={c.phase_state}, dir={c.current_direction:+.3f})")
