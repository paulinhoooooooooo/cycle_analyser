#!/usr/bin/env python3
"""Figeage des dates de cycle sur une date de référence (`fige` dans watchlist.yml).

Idée : quand tu ajoutes une action, tu indiques une date de référence. Les cycles
sont alors ajustés sur la fenêtre de données FIGÉE (du début jusqu'à cette date),
exactement comme le logiciel les voyait ce jour-là. Résultat : les dates de début
et de fin de cycle ne bougent plus jamais toutes seules — seul le compte à rebours
(J-3, J-2, J-1) décroît vers ces dates fixes. Elles ne changent que si tu modifies
l'entrée sur GitHub (date de référence, cycles ou start).

Sans `fige`, comportement d'origine : la fenêtre glisse (dates recalculées chaque
jour).
"""

from __future__ import annotations

from datetime import timedelta
from typing import List, Optional, Tuple, Callable

import numpy as np
import pandas as pd

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import (
    CycleInfo, _detrend_log, _fit_sine, _phase_state,
)


def parse_ref_date(value) -> Optional[pd.Timestamp]:
    """Accepte 10/08/2026 (FR), 2026-08-10 (ISO) ou 2026. Renvoie None si vide/invalide."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit() and len(s) == 4:                 # année seule
        return pd.Timestamp(int(s), 1, 1)
    dayfirst = "/" in s                             # JJ/MM/AAAA → jour d'abord
    try:
        return pd.Timestamp(pd.to_datetime(s, dayfirst=dayfirst))
    except Exception:
        return None


def load_frozen(
    ticker: str,
    periods: List[int],
    period: str,
    interval: str,
    start: Optional[str] = None,
    fige: Optional[str] = None,
) -> Tuple[List[CycleInfo], pd.DatetimeIndex, np.ndarray, int, float, Callable[[float], pd.Timestamp], int]:
    """Charge les données et ajuste les cycles sur la fenêtre FIGÉE (jusqu'à `fige`).

    Retourne :
      cycles    : sinusoïdes ajustées sur la fenêtre figée (ou tout l'historique si pas de `fige`)
      dates     : DatetimeIndex COMPLET (jusqu'à aujourd'hui)
      prices    : prix COMPLETS (jusqu'à aujourd'hui)
      n_full    : nombre de barres complètes
      t_today   : position d'aujourd'hui sur la timeline (= n_full - 1)
      date_of   : fonction barre_absolue -> date calendaire FIGÉE
      n_ref     : nombre de barres de la fenêtre figée

    La position d'aujourd'hui avance chaque jour (t_today), mais les barres de
    transition de la sinusoïde figée sont FIXES → leurs dates ne bougent pas ;
    seul l'écart (compte à rebours) diminue.
    """
    data = fetch_data(ticker, period=period, interval=interval, start=start)
    prices = get_close_prices(data)
    dates = get_dates(data)
    n_full = len(prices)

    cutoff = parse_ref_date(fige)
    if cutoff is not None:
        keep = np.asarray(dates <= cutoff)
        n_ref = int(keep.sum())
        if n_ref < 30:            # date de référence trop tôt → pas assez de données : on n'ige pas
            n_ref = n_full
    else:
        n_ref = n_full

    prices_ref = prices[:n_ref]
    dates_ref = dates[:n_ref]

    detrended, _ = _detrend_log(prices_ref)
    cycles: List[CycleInfo] = []
    for p in periods:
        A, B, amp = _fit_sine(detrended, float(p))
        state, osc_val, cur_dir = _phase_state(A, B, float(p), n_ref - 1)
        cycles.append(CycleInfo(
            period=p, period_exact=float(p),
            amplitude=round(amp * prices_ref[-1], 2), strength=1.0, stability=0.0,
            phase_state=state, current_value=osc_val, current_direction=cur_dir,
            oscillator=np.array([]), r_squared=0.0, amplitude_log=amp,
            coeff_a=A, coeff_b=B,
        ))

    ref_last = dates_ref[-1]
    avg_days = ((dates_ref[-1] - dates_ref[0]).days / max(n_ref - 1, 1)) if n_ref >= 2 else 1.0

    def date_of(bar_abs: float) -> pd.Timestamp:
        """Date calendaire d'une barre absolue (timeline figée). FIXE : ne dépend
        que de la fenêtre de référence, pas d'aujourd'hui."""
        off = float(bar_abs) - (n_ref - 1)
        return ref_last + timedelta(days=int(round(off * avg_days)))

    t_today = float(n_full - 1)
    return cycles, dates, prices, n_full, t_today, date_of, n_ref
