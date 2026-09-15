#!/usr/bin/env python3
"""DIAGNOSTIC : dump des combinaisons d'un ticker (code ACTUEL) pour comprendre
pourquoi une combo attendue (ex. 164+1171) n'apparaît plus.
Env : TICKER (déf REP.MC), START (vide=15y), TARGET (périodes cibles séparées
par des virgules, déf '164,1171')."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cycle_analyzer.data_fetcher import fetch_data, get_close_prices
from cycle_analyzer.cycle_detector import detect_cycles
from cycle_analyzer.combination_analyzer import analyze_combinations

ticker = os.environ.get("TICKER", "REP.MC").upper()
start = os.environ.get("START") or None
target = [int(x) for x in os.environ.get("TARGET", "164,1171").split(",") if x.strip()]

data = fetch_data(ticker, period="15y", interval="1d", start=start)
prices = get_close_prices(data)
N = len(prices)
cycles = detect_cycles(prices, min_period=15, max_period=min(1600, N // 2))
print(f"{ticker} | {N} barres | start={start} | cible ~{target}\n")


def _lab(cr):
    parts = []
    for c in cr.cycles:
        a = getattr(c, "asym", None)
        parts.append(f"{c.period}↑{a[0]}/↓{a[1]}" if a else str(c.period))
    return "+".join(parts)


def _near(cr):
    ps = sorted(c.period for c in cr.cycles)
    return len(ps) == len(target) and all(abs(p - t) <= 40 for p, t in zip(ps, sorted(target)))


for mode, kw in [("BILATERAL (scan)", dict(both_sides=True)),
                 ("DEFAUT (--asym)", dict(both_sides=False))]:
    res = analyze_combinations(prices, cycles, top_n_per_size=5, asym=True, **kw)
    print(f"===== {mode} =====")
    hits = []
    for size in (1, 2, 3):
        for cr in res.get(size, []) or []:
            if cr is None:
                continue
            line = (f"  {_lab(cr):26} Long {cr.total_return_pct:+6.0f}% "
                    f"({cr.hit_rate:3.0f}%, {cr.n_zones}z) · "
                    f"Short {-cr.bearish_total_return_pct:+6.0f}% "
                    f"({cr.bearish_hit_rate:3.0f}%, {len(cr.bearish_zones)}z)")
            if _near(cr):
                hits.append(line)
            # n'imprimer que les size-2 pour rester lisible + la cible
            if size == 2:
                print(line)
    print(f"  --> combo cible ~{target} : "
          + ("\n".join(hits) if hits else "ABSENTE des résultats") + "\n")

# --- Détail : variantes ancrées brutes pour chaque période cible ---
from cycle_analyzer.cycle_detector import detect_anchored_cycle
print("===== VARIANTES ANCRÉES par période cible (detect_anchored_cycle) =====")
for p in target:
    for bs in (False, True):
        vs = detect_anchored_cycle(prices, p, both_sides=bs, return_variants=True)
        tag = "bilat" if bs else "long "
        if not vs:
            print(f"  P={p} [{tag}] : aucune")
            continue
        for i, v in enumerate(vs):
            print(f"  P={p} [{tag}] var{i}: U={v['U']}/D={v['D']} anchor={v['anchor']} "
                  f"Long +{v['up_ret']:.0f}% ({v['up_hit']:.0f}%) · "
                  f"Short +{v['dn_gain']:.0f}% ({v['dn_hit']:.0f}%)")
print()

# --- Cycles SIMPLES effectivement retenus dans le récap (results[1]) ---
print("===== CYCLES SIMPLES retenus (results[1]) =====")
for mode, kw in [("DEFAUT (--asym)", dict(both_sides=False)),
                 ("BILATERAL", dict(both_sides=True))]:
    res = analyze_combinations(prices, cycles, top_n_per_size=20, asym=True, **kw)
    print(f"  --- {mode} ---")
    for cr in res.get(1, []) or []:
        print(f"    {_lab(cr):22} Long {cr.total_return_pct:+6.0f}% "
              f"({cr.hit_rate:3.0f}%, {cr.n_zones}z) · "
              f"Short {-cr.bearish_total_return_pct:+6.0f}% "
              f"({cr.bearish_hit_rate:3.0f}%, {len(cr.bearish_zones)}z)")
print("Terminé.")
