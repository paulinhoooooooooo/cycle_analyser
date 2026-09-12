#!/usr/bin/env python3
"""SCAN « cycles parfaits » — comme le BTC : 100 % de réussite en LONG **et** en
SHORT, avec un gros rendement des deux côtés.

Pour chaque ticker : détecte les cycles (FFT), teste les combinaisons en --asym
(cycles asymétriques + ancrés, comme pour le BTC), puis retient les combos dont
la réussite LONG **et** SHORT est très élevée sur un nombre suffisant de zones
(vrai cycle répété, pas un coup de chance).

Entrées (variables d'environnement) :
  TICKERS      : symboles Yahoo séparés par espace/virgule/retour ligne
  SCREEN_START : date de début FIXE (JJ/MM/AAAA ou AAAA-MM-JJ). Vide = 15 ans
  MIN_HIT      : réussite minimale (défaut 100 → parfait des deux côtés)
  MIN_ZONES    : zones minimales de CHAQUE côté (défaut 3 = ≥ 3 répétitions)
  MAX_PERIOD   : période max en barres (défaut 1600 ≈ cycle 4 ans type BTC)

Usage local :  TICKERS="ETH-USD LTC-USD" python scan_perfect.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices
from cycle_analyzer.cycle_detector import detect_cycles
from cycle_analyzer.combination_analyzer import analyze_combinations

MIN_HIT   = float(os.environ.get("MIN_HIT", "100"))    # réussite mini L ET S
MIN_ZONES = int(os.environ.get("MIN_ZONES", "3"))      # zones mini de chaque côté
MAX_PERIOD = int(os.environ.get("MAX_PERIOD", "1600"))
START = os.environ.get("SCREEN_START", "").strip() or None
PERIOD = os.environ.get("SCREEN_PERIOD", "15y").strip() or "15y"


def _label(cr):
    parts = []
    for c in cr.cycles:
        a = getattr(c, "asym", None)
        parts.append(f"{c.period}↑{a[0]}/↓{a[1]}" if a else str(c.period))
    return "+".join(parts)


def scan_ticker(ticker):
    data = fetch_data(ticker, period=PERIOD, interval="1d", start=START)
    prices = get_close_prices(data)
    if len(prices) < 200:
        return None, "historique trop court"
    cycles = detect_cycles(prices, min_period=15,
                           max_period=min(MAX_PERIOD, len(prices) // 2))
    if not cycles:
        return None, "aucun cycle"
    # --asym : combos ancrés/asymétriques + --bilateral pour que le SHORT compte
    # aussi dans la sélection (on veut des cycles fiables des DEUX côtés).
    res = analyze_combinations(prices, cycles, top_n_per_size=5,
                               asym=True, both_sides=True)
    found = []
    for size in (1, 2, 3):
        for cr in res.get(size, []) or []:
            if cr is None:
                continue
            l_hit = float(cr.hit_rate)
            s_hit = float(cr.bearish_hit_rate)
            l_ret = float(cr.total_return_pct)
            s_gain = -float(cr.bearish_total_return_pct)   # gain d'un short
            l_n = int(cr.n_zones)
            s_n = len(cr.bearish_zones)
            if (l_hit >= MIN_HIT and s_hit >= MIN_HIT
                    and l_n >= MIN_ZONES and s_n >= MIN_ZONES
                    and l_ret > 0 and s_gain > 0):
                found.append(dict(label=_label(cr), l_ret=l_ret, s_gain=s_gain,
                                  l_hit=l_hit, s_hit=s_hit, l_n=l_n, s_n=s_n,
                                  score=l_ret + s_gain))
    # dédup grossière par libellé, tri par score (rdt long + gain short)
    seen, uniq = set(), []
    for f in sorted(found, key=lambda x: -x["score"]):
        if f["label"] in seen:
            continue
        seen.add(f["label"]); uniq.append(f)
    return uniq, None


def main():
    raw = os.environ.get("TICKERS", "")
    tickers = [t for t in re.split(r"[\s,;]+", raw.strip().upper()) if t]
    if not tickers:
        print("Aucun ticker (variable TICKERS).")
        sys.exit(1)
    fen = f"début figé {START}" if START else f"fenêtre {PERIOD}"
    print(f"Scan « cycles parfaits » — {len(tickers)} ticker(s) — {fen}")
    print(f"Critère : réussite LONG et SHORT >= {MIN_HIT:.0f}% · "
          f">= {MIN_ZONES} zones de chaque côté · rendement positif des deux côtés\n")

    all_perfect = []
    for tk in tickers:
        try:
            combos, err = scan_ticker(tk)
        except Exception as exc:
            print(f"  ⚠ {tk:12} erreur : {exc}")
            continue
        if err:
            print(f"  ✗ {tk:12} {err}")
            continue
        if not combos:
            print(f"  ✗ {tk:12} aucun cycle 100/100 fiable")
            continue
        print(f"  ⭐ {tk:12} {len(combos)} cycle(s) PARFAIT(S) :")
        for f in combos[:4]:
            print(f"       {f['label']}b · Long {f['l_ret']:+.0f}% ({f['l_hit']:.0f}%, "
                  f"{f['l_n']} z) · Short {f['s_gain']:+.0f}% ({f['s_hit']:.0f}%, {f['s_n']} z)")
            all_perfect.append((f["score"], tk, f))

    print("\n" + "=" * 66)
    print("\U0001f3c6 TOP DES CYCLES PARFAITS (Long+Short 100%, toutes valeurs)")
    all_perfect.sort(key=lambda x: -x[0])
    if not all_perfect:
        print("  (aucun cycle 100/100 trouvé dans cette liste avec ces seuils)")
    for i, (score, tk, f) in enumerate(all_perfect[:12], 1):
        print(f"  {i:2}. {tk:12} {f['label']}b · Long {f['l_ret']:+.0f}% / "
              f"Short {f['s_gain']:+.0f}% · {f['l_n']}+{f['s_n']} zones")
    print("Terminé.")


if __name__ == "__main__":
    main()
