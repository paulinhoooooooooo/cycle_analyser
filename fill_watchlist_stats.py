#!/usr/bin/env python3
"""Remplit automatiquement rdt / zones / reussite dans watchlist.yml.

Pour CHAQUE combinaison de la watchlist, relance le backtest (exactement les
mêmes calculs que le logiciel) et écrit :
  - rdt      : rendement % total des zones (haussières, ou baissières si short)
  - zones    : nombre de zones touchées
  - reussite : % de zones gagnantes

Ces champs sont purement informatifs (affichés dans les notifs Telegram) et
n'influencent aucun calcul de cycle. Les commentaires et l'ordre du fichier
sont préservés (ruamel.yaml).

⚠️ Nécessite un accès à Yahoo Finance → conçu pour tourner sur GitHub Actions
(workflow « Remplir les stats watchlist ») ou en local.

Usage :  python fill_watchlist_stats.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from ruamel.yaml import YAML

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices
from cycle_analyzer.cycle_detector import (
    CycleInfo, _detrend_log, _fit_sine, _phase_state,
)
from cycle_analyzer.combination_analyzer import _build_combo


def compute_stats(ticker, periods, period, interval, start, direction):
    """Retourne dict(rdt, zones, reussite) pour la combinaison, ou None si la
    combinaison est dégénérée (aucune zone exploitable)."""
    data = fetch_data(ticker, period=period, interval=interval, start=start)
    prices = get_close_prices(data)
    N = len(prices)
    detrended, _ = _detrend_log(prices)

    cycles = []
    for p in periods:
        A, B, amp = _fit_sine(detrended, float(p))
        state, osc_val, cur_dir = _phase_state(A, B, float(p), N - 1)
        cycles.append(CycleInfo(
            period=p, period_exact=float(p),
            amplitude=round(amp * prices[-1], 2), strength=1.0, stability=0.0,
            phase_state=state, current_value=osc_val, current_direction=cur_dir,
            oscillator=np.array([]), r_squared=0.0, amplitude_log=amp,
            coeff_a=A, coeff_b=B,
        ))

    cr = _build_combo(prices, cycles)
    if cr is None:
        return None

    if (direction or "both").lower() == "short":
        # Pour un short, la baisse du marché = gain → on affiche le gain du short
        # en positif (même convention que le score du logiciel : -rdt baissier).
        return dict(rdt=round(-float(cr.bearish_total_return_pct), 1),
                    zones=int(len(cr.bearish_zones)),
                    reussite=int(round(float(cr.bearish_hit_rate))))
    return dict(rdt=round(float(cr.total_return_pct), 1),
                zones=int(cr.n_zones),
                reussite=int(round(float(cr.hit_rate))))


def main() -> None:
    path = Path("watchlist.yml")
    if not path.exists():
        print("❌ watchlist.yml introuvable.")
        sys.exit(1)

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)   # respecte le style « - ticker: »
    cfg = yaml.load(path.read_text(encoding="utf-8"))

    alerts = cfg.get("alerts", []) or []
    print(f"Calcul pour {len(alerts)} combinaison(s)…\n")

    ok = 0
    for e in alerts:
        tk = str(e["ticker"]).upper()
        periods = [int(p.strip()) for p in str(e["cycles"]).split(",")]
        label = f"{tk} ({'+'.join(map(str, periods))}b)"
        try:
            s = compute_stats(tk, periods, e.get("period", "5y"),
                              e.get("interval", "1d"), e.get("start"),
                              e.get("direction", "both"))
        except Exception as exc:
            print(f"  ⚠ {label} -> ERREUR : {exc}")
            continue
        if s is None:
            print(f"  ⚪ {label} -> combinaison dégénérée (ignorée)")
            continue
        e["rdt"] = s["rdt"]
        e["zones"] = s["zones"]
        e["reussite"] = s["reussite"]
        ok += 1
        print(f"  ✓ {label} -> rdt={s['rdt']}  zones={s['zones']}  reussite={s['reussite']}")

    with path.open("w", encoding="utf-8") as f:
        yaml.dump(cfg, f)
    print(f"\nTerminé — {ok}/{len(alerts)} combinaison(s) mises à jour dans watchlist.yml")


if __name__ == "__main__":
    main()
