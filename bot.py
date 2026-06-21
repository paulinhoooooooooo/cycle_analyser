#!/usr/bin/env python3
"""
Bot Telegram interactif — Cycles de marché

Fonctions :
  • Répond à /prochains (ou tout message) avec les prochains événements cycliques
  • Envoie automatiquement une alerte quotidienne (07h30 UTC) quand un événement
    cyclique tombe dans la fenêtre lookaheadBars définie dans watchlist.yml

Déploiement : Railway (Procfile: worker: python bot.py)
Variables d'environnement requises :
  TELEGRAM_TOKEN   — token du bot BotFather

Le chat ID cible pour les alertes proactives est mémorisé automatiquement
dans chat_id.txt dès le premier /prochains — aucune variable supplémentaire.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, NamedTuple, Optional, Set, Tuple

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import CycleInfo, _detrend_log, _fit_sine, _phase_state

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
MAX_LOOKAHEAD    = 300   # barres max pour /prochains (~1 an de trading)

_SENT_FILE    = Path("alerts_sent.json")
_CHAT_ID_FILE = Path("chat_id.txt")


def _get_chat_id() -> str:
    """Retourne le chat ID cible : variable d'env TELEGRAM_CHAT_ID en priorité,
    sinon le fichier chat_id.txt écrit automatiquement au premier /prochains."""
    env = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if env:
        return env
    if _CHAT_ID_FILE.exists():
        return _CHAT_ID_FILE.read_text().strip()
    return ""


def _save_chat_id(chat_id: str) -> None:
    try:
        _CHAT_ID_FILE.write_text(str(chat_id))
    except Exception as exc:
        print(f"[chat_id] Impossible de sauvegarder : {exc}")


# ── Helpers partagés ──────────────────────────────────────────────────────────

class CycleEvent(NamedTuple):
    ticker: str
    periods_str: str
    event_type: str   # HAUSSIER_DEBUT | HAUSSIER_FIN | BAISSIER_DEBUT | BAISSIER_FIN
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
        if d.weekday() < 5:
            added += 1
    return d


def _build_cycles_from_data(
    prices: np.ndarray,
    dates_idx,
    periods: List[int],
) -> Tuple[List[CycleInfo], float, date]:
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
    last_date = dates_idx[-1].date() if hasattr(dates_idx[-1], "date") else date.today()
    return cycles, t_last, last_date


def _event_line(e: CycleEvent) -> str:
    icons = {
        "HAUSSIER_DEBUT": "🟢📈",
        "HAUSSIER_FIN":   "🟢📉",
        "BAISSIER_DEBUT": "🔴📉",
        "BAISSIER_FIN":   "🔴📈",
    }
    labels = {
        "HAUSSIER_DEBUT": "Début alignement HAUSSIER",
        "HAUSSIER_FIN":   "Fin alignement HAUSSIER",
        "BAISSIER_DEBUT": "Début alignement BAISSIER",
        "BAISSIER_FIN":   "Fin alignement BAISSIER",
    }
    icon  = icons.get(e.event_type, "⚪")
    label = labels.get(e.event_type, e.event_type)
    date_str   = e.est_date.strftime("%d/%m/%Y") if e.est_date else "?"
    bar_word   = "barre" if e.bars_away == 1 else "barres"
    periods_detail = " | ".join(f"{p}j" for p in e.periods_str.replace("b", "").split(" + "))
    return (
        f"{icon} {label} dans <b>{e.bars_away} {bar_word}</b> "
        f"(~{date_str}) — cycles : {periods_detail}"
    )


# ── Recherche d'événements ────────────────────────────────────────────────────

def get_events_for_ticker(
    ticker: str,
    periods: List[int],
    period: str,
    interval: str,
) -> List[CycleEvent]:
    """Retourne les 2 prochains événements cycliques pour ce ticker (commande /prochains)."""
    try:
        data = fetch_data(ticker, period=period, interval=interval)
    except Exception as exc:
        print(f"  ⚠ Erreur fetch {ticker} : {exc}")
        return []

    prices    = get_close_prices(data)
    dates_idx = get_dates(data)
    cycles, t_last, last_date = _build_cycles_from_data(prices, dates_idx, periods)
    periods_str = " + ".join(str(p) for p in periods)
    events: List[CycleEvent] = []

    for k in range(1, MAX_LOOKAHEAD + 1):
        bull_before, bear_before = _state_at(cycles, t_last + k - 1)
        bull_after,  bear_after  = _state_at(cycles, t_last + k)
        est = _next_trading_date(last_date, k)

        if not bull_before and bull_after:
            events.append(CycleEvent(ticker, periods_str, "HAUSSIER_DEBUT", k, est))
        if bull_before and not bull_after:
            events.append(CycleEvent(ticker, periods_str, "HAUSSIER_FIN",   k, est))
        if not bear_before and bear_after:
            events.append(CycleEvent(ticker, periods_str, "BAISSIER_DEBUT", k, est))
        if bear_before and not bear_after:
            events.append(CycleEvent(ticker, periods_str, "BAISSIER_FIN",   k, est))

        if len(events) >= 2:
            break

    events.sort(key=lambda e: e.bars_away)
    return events


def get_imminent_events(
    ticker: str,
    periods: List[int],
    period: str,
    interval: str,
    lookahead: int,
) -> List[CycleEvent]:
    """Retourne tous les événements dans les `lookahead` prochaines barres (pour les alertes auto)."""
    try:
        data = fetch_data(ticker, period=period, interval=interval)
    except Exception as exc:
        print(f"  ⚠ Erreur fetch {ticker} : {exc}")
        return []

    prices    = get_close_prices(data)
    dates_idx = get_dates(data)
    cycles, t_last, last_date = _build_cycles_from_data(prices, dates_idx, periods)
    periods_str = " + ".join(str(p) for p in periods)
    events: List[CycleEvent] = []

    for k in range(1, lookahead + 1):
        bull_before, bear_before = _state_at(cycles, t_last + k - 1)
        bull_after,  bear_after  = _state_at(cycles, t_last + k)
        est = _next_trading_date(last_date, k)

        if not bull_before and bull_after:
            events.append(CycleEvent(ticker, periods_str, "HAUSSIER_DEBUT", k, est))
        if bull_before and not bull_after:
            events.append(CycleEvent(ticker, periods_str, "HAUSSIER_FIN",   k, est))
        if not bear_before and bear_after:
            events.append(CycleEvent(ticker, periods_str, "BAISSIER_DEBUT", k, est))
        if bear_before and not bear_after:
            events.append(CycleEvent(ticker, periods_str, "BAISSIER_FIN",   k, est))

    return events


# ── Déduplication des alertes ─────────────────────────────────────────────────

def _load_sent() -> Set[Tuple]:
    if not _SENT_FILE.exists():
        return set()
    try:
        return {tuple(x) for x in json.loads(_SENT_FILE.read_text())}
    except Exception:
        return set()


def _save_sent(sent: Set[Tuple]) -> None:
    try:
        _SENT_FILE.write_text(json.dumps(list(sent)))
    except Exception as exc:
        print(f"[alertes] Impossible de sauvegarder alerts_sent.json : {exc}")


# ── Commande /prochains ───────────────────────────────────────────────────────

def build_report(config: dict) -> str:
    alerts_list = config.get("alerts", [])
    if not alerts_list:
        return "Aucun ticker dans watchlist.yml."

    lines = ["<b>📊 Prochains événements cycliques</b>\n"]
    for entry in alerts_list:
        ticker  = entry["ticker"].upper()
        periods = [int(p.strip()) for p in str(entry["cycles"]).split(",")]
        period  = entry.get("period", "5y")
        interval = entry.get("interval", "1d")

        events      = get_events_for_ticker(ticker, periods, period, interval)
        periods_str = " + ".join(str(p) for p in periods)
        lines.append(f"<b>{ticker}</b> (cycles {periods_str}b)")

        if not events:
            lines.append("  ⚠ Aucun événement trouvé dans les 300 prochaines barres.")
        else:
            for e in events[:2]:
                lines.append(f"  {_event_line(e)}")
        lines.append("")

    return "\n".join(lines).strip()


async def handle_prochains(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Mémorise le chat ID pour les alertes proactives
    _save_chat_id(str(update.effective_chat.id))
    await update.message.reply_text("⏳ Calcul en cours…")
    config_path = Path("watchlist.yml")
    if not config_path.exists():
        await update.message.reply_text("❌ watchlist.yml introuvable sur le serveur.")
        return
    try:
        with config_path.open(encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as exc:
        await update.message.reply_text(f"❌ Erreur YAML dans watchlist.yml : {exc}")
        return
    try:
        report = build_report(config)
    except Exception as exc:
        await update.message.reply_text(f"❌ Erreur lors du calcul : {exc}")
        return
    await update.message.reply_text(report, parse_mode="HTML")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_prochains(update, context)


# ── Alertes proactives quotidiennes ───────────────────────────────────────────

async def check_and_send_alerts(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Job quotidien (07h30 UTC). Pour chaque ticker de watchlist.yml, si un événement
    cyclique tombe dans les lookaheadBars prochaines barres, envoie une alerte Telegram.
    Un même événement (ticker + type + date estimée) n'est jamais notifié deux fois.
    """
    chat_id = _get_chat_id()
    if not chat_id:
        print("[alertes] Chat ID inconnu — envoie /prochains une fois pour l'enregistrer.")
        return

    config_path = Path("watchlist.yml")
    if not config_path.exists():
        print("[alertes] watchlist.yml introuvable.")
        return

    try:
        with config_path.open(encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as exc:
        print(f"[alertes] Erreur lecture watchlist.yml : {exc}")
        return

    alerts_list = config.get("alerts", [])
    lookahead   = int(config.get("lookaheadBars", 3))
    sent        = _load_sent()
    seen_now: Set[Tuple] = set()
    alert_lines: List[str] = []

    for entry in alerts_list:
        ticker   = entry["ticker"].upper()
        periods  = [int(p.strip()) for p in str(entry["cycles"]).split(",")]
        period   = entry.get("period", "5y")
        interval = entry.get("interval", "1d")

        events = get_imminent_events(ticker, periods, period, interval, lookahead)
        for e in events:
            key = (ticker, e.event_type, str(e.est_date))
            seen_now.add(key)
            if key in sent:
                continue  # déjà notifié

            periods_str = " + ".join(str(p) for p in periods)
            if not alert_lines:
                alert_lines.append(
                    f"<b>🔔 Alerte cyclique — événement(s) dans ≤ {lookahead} barres</b>\n"
                )
            alert_lines.append(f"<b>{ticker}</b> (cycles {periods_str}b)")
            alert_lines.append(f"  {_event_line(e)}")
            alert_lines.append("")

    # Mettre à jour le fichier de déduplication
    # On garde seulement les clés encore «visibles» + les nouvelles
    _save_sent(sent | seen_now)

    if alert_lines:
        message = "\n".join(alert_lines).strip()
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
            )
            print(f"[alertes] ✓ Alerte envoyée ({len(alert_lines)//3} événement(s))")
        except Exception as exc:
            print(f"[alertes] ✗ Erreur envoi Telegram : {exc}")
    else:
        print(f"[alertes] Aucun nouvel événement dans les {lookahead} prochaines barres.")


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main() -> None:
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN non défini — arrêt.")
        sys.exit(1)

    stored = _get_chat_id()
    if stored:
        print(f"✓  Alertes proactives activées → chat_id={stored} (19h00 UTC)")
    else:
        print("⚠  Chat ID non encore connu — envoie /prochains une fois pour l'enregistrer.")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Commandes interactives
    app.add_handler(CommandHandler("prochains", handle_prochains))
    app.add_handler(CommandHandler("start",     handle_prochains))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Job quotidien d'alerte proactive — 19h00 UTC (21h00 Paris été / 20h00 hiver)
    app.job_queue.run_daily(
        check_and_send_alerts,
        time=_dt.time(19, 0, 0, tzinfo=_dt.timezone.utc),
    )

    print("Bot démarré. Envoyez /prochains dans Telegram pour voir les cycles.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
