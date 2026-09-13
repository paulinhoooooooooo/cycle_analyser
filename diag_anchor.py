#!/usr/bin/env python3
"""DIAGNOSTIC : un cycle ANCRÉ est-il indépendant du --start ?
Pour un ticker, compare detect_anchored_cycle sur DEUX fenêtres (15y≈2011 et
start 2010) pour les MÊMES périodes : date d'ancrage, réussite, zones.
Si l'ancrage tombe à la même date et donne la même réussite → --asym est bien
indépendant du start (le pré-ancrage ne compte pas). Sinon, on voit où ça bouge.
Env : TICKER (déf REP.MC), PERIODS (déf '167,1027,1020,164,1171')."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import detect_anchored_cycle

ticker = os.environ.get("TICKER", "REP.MC").upper()
periods = [int(x) for x in os.environ.get("PERIODS", "167,1027,1020,164,1171").split(",") if x.strip()]


def run(label, start):
    data = fetch_data(ticker, period="15y", interval="1d", start=start)
    prices = get_close_prices(data); dates = get_dates(data)
    N = len(prices)
    print(f"\n=== fenêtre {label} : {N} barres, {dates[0].date()} -> {dates[-1].date()} ===")
    for P in periods:
        b = detect_anchored_cycle(prices, P, both_sides=True)
        if b is None:
            print(f"  P={P:5}: None (rejeté : < 3 répétitions terminées)")
            continue
        a, U = b["anchor"], b["U"]
        nz = 0; k = 0
        while a + k * P < N:
            e = a + k * P + U - 1
            if a + k * P < e < N:
                nz += 1
            k += 1
        print(f"  P={P:5}: U={U}/D={b['D']} · ancrage barre {a} = {dates[a].date()} · "
              f"LONG {b['up_ret']:+.0f}% hit {b['up_hit']:.0f}% ({nz}z terminées) · "
              f"SHORT {b['dn_gain']:+.0f}% hit {b['dn_hit']:.0f}%")


print(f"{ticker} — le cycle ancré dépend-il du start ? périodes {periods}")
run("15y (~2011)", None)
run("start 2010", "01/01/2010")
print("\nTerminé.")
