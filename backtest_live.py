#!/usr/bin/env python3
"""Backtest « en direct » ne comptant que les zones TERMINÉES.

Sert à rafraîchir les stats (rdt / zones / réussite) au moment d'une alerte,
SANS rien réécrire dans watchlist.yml. La différence avec
``fill_watchlist_stats.compute_stats`` : ici on EXCLUT la zone encore ouverte
(celle qui touche la dernière barre). Résultat : le nombre de zones et le
rendement ne changent QU'À LA FIN d'un cycle — jamais pendant qu'une zone est en
cours. C'est ce qui permet de détecter proprement « un cycle vient de se
terminer » (le nombre de zones terminées augmente de 1).

Aucune dépendance à ruamel : ce module peut être importé par check_alerts.py
dans le workflow d'alertes (qui n'installe que requirements.txt).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices
from cycle_analyzer.cycle_detector import (
    CycleInfo, _detrend_log, _fit_sine, _phase_state,
)
from cycle_analyzer.combination_analyzer import (
    _combined_bullish_mask, _combined_bearish_mask, _compute_zones,
)


def _build_cycles(prices: np.ndarray, periods: List[int]) -> List[CycleInfo]:
    detrended, _ = _detrend_log(prices)
    N = len(prices)
    cycles: List[CycleInfo] = []
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
    return cycles


def compute_completed_stats(ticker, periods, period, interval, start,
                            direction) -> Optional[dict]:
    """dict(rdt, zones, reussite) en ne comptant QUE les zones terminées, ou None
    si aucune zone terminée exploitable. Lève en cas d'erreur réseau/données."""
    data = fetch_data(ticker, period=period, interval=interval, start=start)
    prices = get_close_prices(data)
    if prices is None or len(prices) < 30:
        return None
    cycles = _build_cycles(prices, periods)

    short = (direction or "both").lower() == "short"
    mask = (_combined_bearish_mask(prices, cycles) if short
            else _combined_bullish_mask(prices, cycles))
    zones = _compute_zones(prices, mask)

    # Exclure la zone ENCORE OUVERTE : si le masque est vrai sur la dernière barre
    # et que la dernière zone finit sur cette barre, le cycle n'est pas terminé.
    if zones and bool(mask[-1]) and zones[-1].end == len(prices) - 1:
        zones = zones[:-1]
    if not zones:
        return None

    rets = [float(z.return_pct) for z in zones]
    total = sum(rets)
    if short:
        total = -total                              # baisse = gain pour un short
        wins = sum(1 for r in rets if r < 0)
    else:
        wins = sum(1 for r in rets if r > 0)
    return dict(rdt=round(total, 1),
                zones=len(zones),
                reussite=int(round(wins / len(zones) * 100)))
