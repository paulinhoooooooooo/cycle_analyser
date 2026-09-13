#!/usr/bin/env python3
"""SCAN d'UNIVERS (S&P 500 auto, indices, ou liste), par LOTS, avec SECTEUR.

Pour chaque valeur : détecte les cycles (FFT), teste les combinaisons en --asym
+ --bilateral (code À JOUR : zone en cours exclue, grille fine de périodes),
retient la MEILLEURE combinaison qui atteint les seuils (réussite LONG et SHORT
>= MIN_HIT sur >= MIN_ZONES zones de chaque côté), et l'affiche avec son SECTEUR.

Env :
  UNIVERSE   : sp500 | indices | list
  TICKERS    : (si UNIVERSE=list) symboles Yahoo séparés par espaces/virgules
  BATCH_INDEX / NUM_BATCHES : découpe l'univers en lots parallèles (défaut 0/1)
  MIN_HIT    : réussite mini L ET S (défaut 90)
  MIN_ZONES  : zones mini de chaque côté (défaut 5)
  MAX_PERIOD : période max en barres (défaut 1600)
"""
from __future__ import annotations
import os, re, sys
from io import StringIO
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import requests
from cycle_analyzer.data_fetcher import fetch_data, get_close_prices
from cycle_analyzer.cycle_detector import detect_cycles
from cycle_analyzer.combination_analyzer import analyze_combinations

UNIVERSE = os.environ.get("UNIVERSE", "list").strip().lower()
MIN_HIT = float(os.environ.get("MIN_HIT", "90"))
MIN_ZONES = int(os.environ.get("MIN_ZONES", "5"))
MAX_PERIOD = int(os.environ.get("MAX_PERIOD", "1600"))
BATCH_INDEX = int(os.environ.get("BATCH_INDEX", "0"))
NUM_BATCHES = int(os.environ.get("NUM_BATCHES", "1"))
PERIOD = os.environ.get("SCREEN_PERIOD", "15y").strip() or "15y"
START = os.environ.get("SCREEN_START", "").strip() or None

_UA = {"User-Agent": "Mozilla/5.0 (compatible; cycle-scan/1.0)"}


def sp500_universe():
    """(ticker Yahoo, nom, secteur) depuis la table Wikipedia du S&P 500."""
    import pandas as pd
    html = requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers=_UA, timeout=40).text
    tbl = pd.read_html(StringIO(html))[0]
    out = []
    for _, r in tbl.iterrows():
        sym = str(r["Symbol"]).strip().replace(".", "-")       # BRK.B -> BRK-B
        out.append((sym, str(r["Security"]).strip(), str(r["GICS Sector"]).strip()))
    return out


def indices_universe():
    idx = [
        ("^GSPC", "S&P 500", "Indice"), ("^IXIC", "Nasdaq Composite", "Indice"),
        ("^NDX", "Nasdaq 100", "Indice"), ("^DJI", "Dow Jones", "Indice"),
        ("^RUT", "Russell 2000", "Indice"), ("^FCHI", "CAC 40", "Indice"),
        ("^GDAXI", "DAX", "Indice"), ("^STOXX50E", "Euro Stoxx 50", "Indice"),
        ("^STOXX", "STOXX 600", "Indice"), ("^FTSE", "FTSE 100", "Indice"),
        ("^N225", "Nikkei 225", "Indice"), ("^HSI", "Hang Seng", "Indice"),
        ("^KS11", "KOSPI", "Indice"), ("^BSESN", "BSE Sensex", "Indice"),
        ("^AXJO", "ASX 200", "Indice"), ("^FTSEMIB.MI", "FTSE MIB", "Indice"),
        ("^IBEX", "IBEX 35", "Indice"), ("^SSMI", "SMI Suisse", "Indice"),
        ("^AEX", "AEX Amsterdam", "Indice"), ("^BVSP", "Bovespa", "Indice"),
        ("^GSPTSE", "TSX Canada", "Indice"), ("^HSCE", "Hang Seng China", "Indice"),
        ("000001.SS", "Shanghai Composite", "Indice"), ("^TWII", "Taiwan Weighted", "Indice"),
    ]
    return idx


def build_universe():
    if UNIVERSE == "sp500":
        return sp500_universe()
    if UNIVERSE == "indices":
        return indices_universe()
    raw = os.environ.get("TICKERS", "")
    toks = [t for t in re.split(r"[\s,;]+", raw.strip()) if t]
    return [(t.upper(), t.upper(), "") for t in toks]


def _label(cr):
    parts = []
    for c in cr.cycles:
        a = getattr(c, "asym", None)
        parts.append(f"{c.period}↑{a[0]}/↓{a[1]}" if a else str(c.period))
    return "+".join(parts)


def best_combo(prices):
    cycles = detect_cycles(prices, min_period=15, max_period=min(MAX_PERIOD, len(prices) // 2))
    if not cycles:
        return None
    res = analyze_combinations(prices, cycles, top_n_per_size=5, asym=True, both_sides=True)
    best = None
    for size in (1, 2, 3):
        for cr in res.get(size, []) or []:
            if cr is None:
                continue
            l_hit, s_hit = float(cr.hit_rate), float(cr.bearish_hit_rate)
            l_ret, s_gain = float(cr.total_return_pct), -float(cr.bearish_total_return_pct)
            l_n, s_n = int(cr.n_zones), len(cr.bearish_zones)
            if (l_hit >= MIN_HIT and s_hit >= MIN_HIT and l_n >= MIN_ZONES
                    and s_n >= MIN_ZONES and l_ret > 0 and s_gain > 0):
                score = l_ret + s_gain
                if best is None or score > best[0]:
                    best = (score, dict(label=_label(cr), l_ret=l_ret, s_gain=s_gain,
                                        l_hit=l_hit, s_hit=s_hit, l_n=l_n, s_n=s_n))
    return best[1] if best else None


def main():
    uni = build_universe()
    uni = [uni[i] for i in range(len(uni)) if i % NUM_BATCHES == BATCH_INDEX]
    print(f"UNIVERS={UNIVERSE} lot {BATCH_INDEX+1}/{NUM_BATCHES} : {len(uni)} valeur(s) · "
          f"seuils L&S>={MIN_HIT:.0f}% >={MIN_ZONES} zones · {START or PERIOD}\n", flush=True)
    hits = 0
    for tk, name, sector in uni:
        try:
            data = fetch_data(tk, period=PERIOD, interval="1d", start=START)
            prices = get_close_prices(data)
            if len(prices) < 200:
                continue
            b = best_combo(prices)
        except Exception as exc:
            print(f"  x {tk:12} erreur {str(exc)[:50]}", flush=True)
            continue
        if b is None:
            continue
        sec = sector or ""
        if not sec:
            try:
                import yfinance as yf
                sec = (yf.Ticker(tk).info or {}).get("sector", "") or ""
            except Exception:
                sec = ""
        hits += 1
        print(f"  ⭐ [{sec or '?':22}] {tk:12} {name[:26]:26} {b['label']}b · "
              f"Long +{b['l_ret']:.0f}% ({b['l_hit']:.0f}%,{b['l_n']}z) · "
              f"Short +{b['s_gain']:.0f}% ({b['s_hit']:.0f}%,{b['s_n']}z)", flush=True)
    print(f"\n== lot {BATCH_INDEX+1}/{NUM_BATCHES} terminé : {hits} valeur(s) retenue(s) ==", flush=True)


if __name__ == "__main__":
    main()
