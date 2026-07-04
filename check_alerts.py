#!/usr/bin/env python3
"""
Vérificateur d'alertes cycliques J-N
Envoie une notification Telegram quand un alignement haussier/baissier
est prévu exactement dans N barres de trading.

Usage :
  python check_alerts.py                   # utilise watchlist.yml
  TELEGRAM_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python check_alerts.py
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np
import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import CycleInfo, _detrend_log, _fit_sine, _phase_state


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram(message: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[DRY RUN — pas de secrets Telegram]\n{message}\n")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }, timeout=10)
    if not resp.ok:
        print(f"Erreur Telegram : {resp.status_code} {resp.text}")


def _osc_at(c: CycleInfo, t: float) -> float:
    return (
        c.coeff_a * math.cos(2 * math.pi * t / c.period)
        + c.coeff_b * math.sin(2 * math.pi * t / c.period)
    )


def _state_at(cycles: List[CycleInfo], t: float) -> Tuple[bool, bool]:
    """Retourne (tous_haussiers, tous_baissiers) à la barre t (extrapolée)."""
    all_bull = all_bear = True
    for c in cycles:
        rising = _osc_at(c, t) > _osc_at(c, t - 1)
        if not rising:
            all_bull = False
        if rising:
            all_bear = False
    return all_bull, all_bear


def check_ticker(
    ticker: str,
    periods: List[int],
    period: str,
    interval: str,
    lookahead: int,
    start: str = None,
) -> List[str]:
    """Retourne la liste des messages d'alerte pour ce ticker."""
    try:
        data = fetch_data(ticker, period=period, interval=interval, start=start)
    except Exception as exc:
        print(f"  ⚠ Erreur fetch {ticker} : {exc}")
        return []

    prices = get_close_prices(data)
    dates = get_dates(data)
    N = len(prices)
    detrended, _ = _detrend_log(prices)

    cycles: List[CycleInfo] = []
    for p in periods:
        A, B, amp = _fit_sine(detrended, float(p))
        state, osc_val, direction = _phase_state(A, B, float(p), N - 1)
        cycles.append(CycleInfo(
            period=p, period_exact=float(p),
            amplitude=round(amp * prices[-1], 2), strength=1.0, stability=0.0,
            phase_state=state, current_value=osc_val, current_direction=direction,
            oscillator=np.array([]), r_squared=0.0, amplitude_log=amp,
            coeff_a=A, coeff_b=B,
        ))

    t_last = float(N - 1)
    last_date = dates[-1].strftime("%d/%m/%Y")
    periods_str = " + ".join(str(p) for p in periods)

    messages: List[str] = []

    # Vérifie les transitions pour chaque k de 1 à lookahead (J-1, J-2, J-3…)
    for k in range(1, lookahead + 1):
        bull_before, bear_before = _state_at(cycles, t_last + k - 1)
        bull_after, bear_after = _state_at(cycles, t_last + k)

        barre_word = "barre" if k == 1 else "barres"
        periods_detail = " | ".join(f"{p}j" for p in periods)

        if not bull_before and bull_after:
            messages.append(
                f"🟢 <b>{ticker}</b> — Cycles {periods_str}b ({periods_detail})\n"
                f"📈 Alignement <b>HAUSSIER</b> dans <b>{k} {barre_word}</b>\n"
                f"📅 Données au {last_date}"
            )

        if bull_before and not bull_after:
            messages.append(
                f"🔴 <b>{ticker}</b> — Cycles {periods_str}b ({periods_detail})\n"
                f"📉 Fin de l'alignement <b>HAUSSIER</b> dans <b>{k} {barre_word}</b>\n"
                f"📅 Données au {last_date}"
            )

        if not bear_before and bear_after:
            messages.append(
                f"🔴 <b>{ticker}</b> — Cycles {periods_str}b ({periods_detail})\n"
                f"📉 Alignement <b>BAISSIER</b> dans <b>{k} {barre_word}</b>\n"
                f"📅 Données au {last_date}"
            )

        if bear_before and not bear_after:
            messages.append(
                f"🔴 <b>{ticker}</b> — Cycles {periods_str}b ({periods_detail})\n"
                f"📈 Fin de l'alignement <b>BAISSIER</b> dans <b>{k} {barre_word}</b>\n"
                f"📅 Données au {last_date}"
            )

    return messages


def main() -> None:
    config_path = Path("watchlist.yml")
    if not config_path.exists():
        print("Fichier watchlist.yml introuvable.")
        sys.exit(1)

    with config_path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)

    lookahead = int(config.get("lookaheadBars", 3))
    alerts_list = config.get("alerts", [])

    print(f"Vérification de {len(alerts_list)} ticker(s) — J-{lookahead}…")

    total_sent = 0
    for entry in alerts_list:
        ticker = entry["ticker"].upper()
        periods = [int(p.strip()) for p in str(entry["cycles"]).split(",")]
        period = entry.get("period", "5y")
        interval = entry.get("interval", "1d")
        start = entry.get("start")  # date de début fixe optionnelle (AAAA-MM-JJ)

        print(f"  {ticker} ({' + '.join(str(p) for p in periods)}b)… ", end="", flush=True)
        messages = check_ticker(ticker, periods, period, interval, lookahead, start=start)

        if messages:
            for msg in messages:
                send_telegram(msg)
                total_sent += 1
            print(f"{len(messages)} alerte(s) envoyée(s)")
        else:
            print("aucune alerte aujourd'hui")

    print(f"\nTerminé — {total_sent} alerte(s) au total.")


if __name__ == "__main__":
    main()
