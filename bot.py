#!/usr/bin/env python3
"""
Bot Telegram interactif — Cycles de marché
Répond à tout message (ou /prochains) avec les prochains événements cycliques
pour tous les tickers de watchlist.yml.

Déploiement : Railway (Procfile: worker: python bot.py)
Variables d'environnement requises : TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (optionnel)
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import CycleInfo, _detrend_log, _fit_sine, _phase_state

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
MAX_LOOKAHEAD = 300  # barres max pour chercher le prochain événement (~1 an de trading)


class CycleEvent(NamedTuple):
    ticker: str
    periods_str: str
    event_type: str   # "HAUSSIER_DEBUT" | "HAUSSIER_FIN" | "BAISSIER_DEBUT" | "BAISSIER_FIN"
    bars_away: int
    est_date: Optional[date]


def _osc_at(c: CycleInfo, t: float) -> float:
    return (
        c.coeff_a * math.cos(2 * math.pi * t / c.period)
        + c.coeff_b * math.sin(2 * math.pi * t / c.period)
    )


def _state_at(cycles: List[CycleInfo], t: float) -> Tuple[bool, bool]:
    all_bull = all_bear = True
    for c in cycles:
        rising = _osc_at(c, t) > _osc_at(c, t - 1)
        if not rising:
            all_bull = False
        if rising:
            all_bear = False
    return all_bull, all_bear


def _next_trading_date(from_date: date, bars: int) -> date:
    """Estime la date de trading à +bars barres (saute week-ends, approximation)."""
    d = from_date
    added = 0
    while added < bars:
        d += timedelta(days=1)
        if d.weekday() < 5:  # lundi–vendredi
            added += 1
    return d


def get_events_for_ticker(
    ticker: str,
    periods: List[int],
    period: str,
    interval: str,
) -> List[CycleEvent]:
    """Retourne les 4 prochains événements cycliques pour ce ticker."""
    try:
        data = fetch_data(ticker, period=period, interval=interval)
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
    last_date = dates[-1].date() if hasattr(dates[-1], "date") else date.today()
    periods_str = " + ".join(str(p) for p in periods)

    events: List[CycleEvent] = []
    seen_types: set = set()

    for k in range(1, MAX_LOOKAHEAD + 1):
        bull_before, bear_before = _state_at(cycles, t_last + k - 1)
        bull_after, bear_after = _state_at(cycles, t_last + k)

        est = _next_trading_date(last_date, k)

        if not bull_before and bull_after and "HAUSSIER_DEBUT" not in seen_types:
            events.append(CycleEvent(ticker, periods_str, "HAUSSIER_DEBUT", k, est))
            seen_types.add("HAUSSIER_DEBUT")

        if bull_before and not bull_after and "HAUSSIER_FIN" not in seen_types:
            events.append(CycleEvent(ticker, periods_str, "HAUSSIER_FIN", k, est))
            seen_types.add("HAUSSIER_FIN")

        if not bear_before and bear_after and "BAISSIER_DEBUT" not in seen_types:
            events.append(CycleEvent(ticker, periods_str, "BAISSIER_DEBUT", k, est))
            seen_types.add("BAISSIER_DEBUT")

        if bear_before and not bear_after and "BAISSIER_FIN" not in seen_types:
            events.append(CycleEvent(ticker, periods_str, "BAISSIER_FIN", k, est))
            seen_types.add("BAISSIER_FIN")

        if len(seen_types) == 4:
            break

    events.sort(key=lambda e: e.bars_away)
    return events


def _event_line(e: CycleEvent) -> str:
    icons = {
        "HAUSSIER_DEBUT": "🟢📈",
        "HAUSSIER_FIN":   "🔴📉",
        "BAISSIER_DEBUT": "🔴📉",
        "BAISSIER_FIN":   "🟢📈",
    }
    labels = {
        "HAUSSIER_DEBUT": "Début alignement HAUSSIER",
        "HAUSSIER_FIN":   "Fin alignement HAUSSIER",
        "BAISSIER_DEBUT": "Début alignement BAISSIER",
        "BAISSIER_FIN":   "Fin alignement BAISSIER",
    }
    icon = icons.get(e.event_type, "⚪")
    label = labels.get(e.event_type, e.event_type)
    date_str = e.est_date.strftime("%d/%m/%Y") if e.est_date else "?"
    bar_word = "barre" if e.bars_away == 1 else "barres"
    periods_detail = " | ".join(f"{p}j" for p in e.periods_str.replace("b", "").split(" + "))
    return f"{icon} {label} dans <b>{e.bars_away} {bar_word}</b> (~{date_str}) — cycles : {periods_detail}"


def build_report(config: dict) -> str:
    alerts_list = config.get("alerts", [])
    if not alerts_list:
        return "Aucun ticker dans watchlist.yml."

    lines = ["<b>📊 Prochains événements cycliques</b>\n"]

    for entry in alerts_list:
        ticker = entry["ticker"].upper()
        periods = [int(p.strip()) for p in str(entry["cycles"]).split(",")]
        period = entry.get("period", "5y")
        interval = entry.get("interval", "1d")

        events = get_events_for_ticker(ticker, periods, period, interval)
        periods_str = " + ".join(str(p) for p in periods)
        lines.append(f"<b>{ticker}</b> (cycles {periods_str}b)")

        if not events:
            lines.append("  ⚠ Aucun événement trouvé dans les 60 prochaines barres.")
        else:
            for e in events[:2]:
                lines.append(f"  {_event_line(e)}")
        lines.append("")

    return "\n".join(lines).strip()


async def handle_prochains(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Calcul en cours…")
    config_path = Path("watchlist.yml")
    if not config_path.exists():
        await update.message.reply_text("❌ watchlist.yml introuvable sur le serveur.")
        return
    with config_path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)
    report = build_report(config)
    await update.message.reply_text(report, parse_mode="HTML")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_prochains(update, context)


def main() -> None:
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN non défini — arrêt.")
        sys.exit(1)

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("prochains", handle_prochains))
    app.add_handler(CommandHandler("start", handle_prochains))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot démarré. Envoyez /prochains dans Telegram pour voir les cycles.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
