#!/usr/bin/env python3
"""
Bot Telegram interactif — Cycles de marché

Fonctions :
  • Répond à /prochains (ou tout message) avec les prochains événements cycliques
  • Répond à /historique avec l'historique des cycles passés (début, fin, rendement)
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


def _est_future_date(dates_idx, bars_ahead: int) -> date:
    """Date estimée à +bars_ahead barres, calculée exactement comme le graphique :
    on extrapole l'espacement calendaire RÉEL des barres. S'adapte automatiquement
    aux marchés 5j/7 (actions) et 7j/7 (crypto) — pas de saut de week-end en dur."""
    last = dates_idx[-1]
    if len(dates_idx) < 2:
        return last.date() if hasattr(last, "date") else last
    avg_days = (dates_idx[-1] - dates_idx[0]).days / max(len(dates_idx) - 1, 1)
    future = last + timedelta(days=int(round(bars_ahead * avg_days)))
    return future.date() if hasattr(future, "date") else future


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

def _event_in_direction(event_type: str, direction: str) -> bool:
    """Filtre les événements selon la direction voulue pour une combinaison :
    'long' → alignements HAUSSIERS uniquement, 'short' → BAISSIERS uniquement,
    'both' (ou absent) → tout."""
    d = (direction or "both").lower()
    if d == "long":
        return event_type.startswith("HAUSSIER")
    if d == "short":
        return event_type.startswith("BAISSIER")
    return True


def _transitions_at(bull_before, bull_after, bear_before, bear_after):
    """Retourne la liste des types d'événements survenant à cette barre."""
    out = []
    if not bull_before and bull_after:
        out.append("HAUSSIER_DEBUT")
    if bull_before and not bull_after:
        out.append("HAUSSIER_FIN")
    if not bear_before and bear_after:
        out.append("BAISSIER_DEBUT")
    if bear_before and not bear_after:
        out.append("BAISSIER_FIN")
    return out


def get_events_for_ticker(
    ticker: str,
    periods: List[int],
    period: str,
    interval: str,
    start: Optional[str] = None,
    direction: str = "both",
) -> List[CycleEvent]:
    """Retourne les 2 prochains événements cycliques pour ce ticker (commande /prochains)."""
    try:
        data = fetch_data(ticker, period=period, interval=interval, start=start)
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
        # Use k-1: report the peak/trough bar (last bar of previous state),
        # which matches the oscillator annotation on the chart.
        bar = max(1, k - 1)
        est = _est_future_date(dates_idx, bar)

        for et in _transitions_at(bull_before, bull_after, bear_before, bear_after):
            if _event_in_direction(et, direction):
                events.append(CycleEvent(ticker, periods_str, et, bar, est))

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
    start: Optional[str] = None,
    direction: str = "both",
) -> List[CycleEvent]:
    """Retourne tous les événements dans les `lookahead` prochaines barres (pour les alertes auto)."""
    try:
        data = fetch_data(ticker, period=period, interval=interval, start=start)
    except Exception as exc:
        print(f"  ⚠ Erreur fetch {ticker} : {exc}")
        return []

    prices    = get_close_prices(data)
    dates_idx = get_dates(data)
    cycles, t_last, last_date = _build_cycles_from_data(prices, dates_idx, periods)
    periods_str = " + ".join(str(p) for p in periods)
    events: List[CycleEvent] = []

    # k va jusqu'à lookahead+1 : l'événement (pic/creux) est à la barre k-1, donc
    # pour capter un événement « dans lookahead barres » il faut atteindre k=lookahead+1.
    for k in range(1, lookahead + 2):
        bull_before, bear_before = _state_at(cycles, t_last + k - 1)
        bull_after,  bear_after  = _state_at(cycles, t_last + k)
        bar = max(1, k - 1)
        if bar > lookahead:
            continue
        est = _est_future_date(dates_idx, bar)

        for et in _transitions_at(bull_before, bull_after, bear_before, bear_after):
            if _event_in_direction(et, direction):
                events.append(CycleEvent(ticker, periods_str, et, bar, est))

    return events


# ── Tous les futurs cycles (workflow « Futurs cycles ») ───────────────────────
# Liste, par ticker, TOUS les cycles À VENIR (zones d'alignement futures) avec
# leur début et leur fin ESTIMÉS — pas seulement le prochain événement.

class FutureCycle(NamedTuple):
    ticker: str
    periods_str: str
    kind: str                 # HAUSSIER | BAISSIER
    debut: date
    fin: Optional[date]       # None si la fin dépasse l'horizon


def _dir_kinds(direction: str):
    """(nom, index) des sens à lister : long → haussier, short → baissier,
    both → les deux. L'index 0/1 correspond à _state_at (bull, bear)."""
    d = (direction or "both").lower()
    if d == "long":
        return [("HAUSSIER", 0)]
    if d == "short":
        return [("BAISSIER", 1)]
    return [("HAUSSIER", 0), ("BAISSIER", 1)]


def get_future_cycles_for_ticker(
    ticker: str,
    periods: List[int],
    period: str,
    interval: str,
    start: Optional[str] = None,
    direction: str = "both",
    max_cycles: int = 8,
) -> List[FutureCycle]:
    """Tous les cycles À VENIR d'un ticker : chaque future zone d'alignement
    (début → fin estimés), jusqu'à `max_cycles` par sens, dans un horizon adapté
    à la longueur des cycles."""
    try:
        data = fetch_data(ticker, period=period, interval=interval, start=start)
    except Exception as exc:
        print(f"  ⚠ Erreur fetch {ticker} : {exc}")
        return []

    prices    = get_close_prices(data)
    dates_idx = get_dates(data)
    cycles, t_last, _last = _build_cycles_from_data(prices, dates_idx, periods)
    periods_str = " + ".join(str(p) for p in periods)
    horizon = min(2000, max(600, 4 * max(periods)))    # assez pour plusieurs cycles

    out: List[FutureCycle] = []
    for kind, idx in _dir_kinds(direction):
        count = 0
        open_debut: Optional[date] = None
        for k in range(1, horizon + 1):
            before = _state_at(cycles, t_last + k - 1)[idx]
            after  = _state_at(cycles, t_last + k)[idx]
            bar = max(1, k - 1)                          # le pic/creux est à la barre k-1
            if after and not before:                     # début d'une future zone
                open_debut = _est_future_date(dates_idx, bar)
            elif before and not after and open_debut is not None:
                out.append(FutureCycle(ticker, periods_str, kind,
                                       open_debut, _est_future_date(dates_idx, bar)))
                open_debut = None
                count += 1
                if count >= max_cycles:
                    break
        if open_debut is not None and count < max_cycles:  # dernière zone sans fin visible
            out.append(FutureCycle(ticker, periods_str, kind, open_debut, None))
    out.sort(key=lambda c: c.debut)
    return out


def _future_line(c: FutureCycle) -> str:
    icon = "🟢📈" if c.kind == "HAUSSIER" else "🔴📉"
    sens = "haussier (long)" if c.kind == "HAUSSIER" else "baissier (short)"
    d0 = c.debut.strftime("%d/%m/%Y")
    d1 = c.fin.strftime("%d/%m/%Y") if c.fin else "au-delà de l'horizon"
    return f"{icon} <b>{d0} → {d1}</b> <i>({sens})</i>"


def build_future_report(config: dict) -> str:
    alerts_list = config.get("alerts", [])
    if not alerts_list:
        return "Aucun ticker dans watchlist.yml."

    ranks = _ticker_ranks(alerts_list)
    lines = ["<b>🔮 Tous les futurs cycles (dates estimées)</b>\n"]
    for i, entry in enumerate(alerts_list):
        ticker    = entry["ticker"].upper()
        periods   = [int(p.strip()) for p in str(entry["cycles"]).split(",")]
        period    = entry.get("period", "5y")
        interval  = entry.get("interval", "1d")
        start     = entry.get("start")
        direction = entry.get("direction", "both")

        periods_str = " + ".join(str(p) for p in periods)
        rank, total = ranks[i]
        dir_tag = {"long": " ↑ LONG", "short": " ↓ SHORT"}.get((direction or "both").lower(), "")
        lines.append(f"<b>{ticker}</b>{_rank_tag(rank, total)}{dir_tag} (cycles {periods_str}b)")

        fut = get_future_cycles_for_ticker(ticker, periods, period, interval,
                                           start=start, direction=direction)
        if not fut:
            lines.append("  ⚠ Aucun futur cycle détecté dans l'horizon.")
        else:
            for c in fut:
                lines.append(f"  {_future_line(c)}")
        lines.append("")

    return "\n".join(lines).strip()


# ── Historique des cycles passés (commande /historique) ───────────────────────
# On NE recalcule PAS tout l'historique détecté : on rejoue UNIQUEMENT les cycles
# ── Historique des cycles passés (workflow « historique ») ────────────────────
# Calcule les VRAIS cycles passés depuis les données (zones d'alignement révolues,
# avec début / fin / rendement). Un paramètre « depuis » (date) permet d'exclure
# les cycles trop anciens — au choix de l'utilisateur.

class PastCycle(NamedTuple):
    ticker: str
    periods_str: str
    kind: str                 # HAUSSIER | BAISSIER
    debut: date
    fin: date
    return_pct: float


def _to_date(x) -> date:
    return x.date() if hasattr(x, "date") else x


def get_past_cycles_for_ticker(
    ticker: str,
    periods: List[int],
    period: str,
    interval: str,
    start: Optional[str] = None,
    direction: str = "both",
    since: Optional[date] = None,
    max_cycles: int = 40,
) -> List[PastCycle]:
    """Vrais cycles PASSÉS d'un ticker : chaque zone d'alignement révolue
    (début → fin + rendement). `since` (optionnel) ne garde que les cycles dont le
    début est postérieur ou égal à cette date."""
    try:
        data = fetch_data(ticker, period=period, interval=interval, start=start)
    except Exception as exc:
        print(f"  ⚠ Erreur fetch {ticker} : {exc}")
        return []

    prices    = get_close_prices(data)
    dates_idx = get_dates(data)
    cycles, _t_last, _last = _build_cycles_from_data(prices, dates_idx, periods)
    periods_str = " + ".join(str(p) for p in periods)
    N = len(prices)

    out: List[PastCycle] = []
    for kind, idx in _dir_kinds(direction):
        t = 1
        while t < N:
            if not _state_at(cycles, float(t))[idx]:
                t += 1
                continue
            s = t
            while t < N and _state_at(cycles, float(t))[idx]:
                t += 1
            e = t - 1
            if e <= s:
                continue                          # zone d'une seule barre : ignorée
            p0, p1 = float(prices[s]), float(prices[e])
            if p0 <= 0:
                continue
            chg = (p1 / p0 - 1.0) * 100.0
            ret = chg if kind == "HAUSSIER" else -chg   # short : gain quand ça baisse
            d0, d1 = _to_date(dates_idx[s]), _to_date(dates_idx[e])
            if since and d0 < since:
                continue                          # cycle antérieur à « depuis » → exclu
            out.append(PastCycle(ticker, periods_str, kind, d0, d1, ret))
    out.sort(key=lambda c: c.debut, reverse=True)     # plus récents d'abord
    return out[:max_cycles]


def _past_line(c: PastCycle) -> str:
    icon = "🟢📈" if c.kind == "HAUSSIER" else "🔴📉"
    sens = "haussier (long)" if c.kind == "HAUSSIER" else "baissier (short)"
    sign = "+" if c.return_pct >= 0 else ""
    d0 = c.debut.strftime("%d/%m/%Y")
    d1 = c.fin.strftime("%d/%m/%Y")
    return f"{icon} <b>{d0} → {d1}</b> : {sign}{c.return_pct:.1f}% <i>({sens})</i>"


def build_history_report(config: dict, since: Optional[date] = None) -> str:
    alerts_list = config.get("alerts", [])
    if not alerts_list:
        return "Aucun ticker dans watchlist.yml."

    ranks = _ticker_ranks(alerts_list)
    titre = "<b>🕓 Historique des cycles passés</b>"
    if since:
        titre += f" <i>(depuis le {since.strftime('%d/%m/%Y')})</i>"
    lines = [titre + "\n"]
    for i, entry in enumerate(alerts_list):
        ticker    = entry["ticker"].upper()
        periods   = [int(p.strip()) for p in str(entry["cycles"]).split(",")]
        period    = entry.get("period", "5y")
        interval  = entry.get("interval", "1d")
        start     = entry.get("start")
        direction = entry.get("direction", "both")

        periods_str = " + ".join(str(p) for p in periods)
        rank, total = ranks[i]
        dir_tag = {"long": " ↑ LONG", "short": " ↓ SHORT"}.get((direction or "both").lower(), "")
        lines.append(f"<b>{ticker}</b>{_rank_tag(rank, total)}{dir_tag} (cycles {periods_str}b)")

        past = get_past_cycles_for_ticker(ticker, periods, period, interval,
                                          start=start, direction=direction, since=since)
        if not past:
            lines.append("  ⚠ Aucun cycle passé sur la période.")
        else:
            for c in past:
                lines.append(f"  {_past_line(c)}")
        lines.append("")

    return "\n".join(lines).strip()


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

def _ticker_ranks(alerts_list: list) -> dict:
    """Rang de chaque entrée pour les tickers présents plusieurs fois dans la
    watchlist : l'ORDRE DANS LE FICHIER fait le classement (1re entrée = #1 =
    combinaison la plus puissante). Retourne {index_entrée: (rang, total)}."""
    counts: dict = {}
    for entry in alerts_list:
        tk = entry["ticker"].upper()
        counts[tk] = counts.get(tk, 0) + 1
    seen: dict = {}
    ranks: dict = {}
    for i, entry in enumerate(alerts_list):
        tk = entry["ticker"].upper()
        seen[tk] = seen.get(tk, 0) + 1
        ranks[i] = (seen[tk], counts[tk])
    return ranks


_RANK_ICONS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _rank_tag(rank: int, total: int) -> str:
    """Étiquette de classement affichée quand un ticker a plusieurs combinaisons."""
    if total <= 1:
        return ""
    icon = _RANK_ICONS.get(rank, "▫️")
    return f" {icon} <b>#{rank}</b>"


def build_report(config: dict) -> str:
    alerts_list = config.get("alerts", [])
    if not alerts_list:
        return "Aucun ticker dans watchlist.yml."

    ranks = _ticker_ranks(alerts_list)
    lines = ["<b>📊 Prochains événements cycliques</b>\n"]
    for i, entry in enumerate(alerts_list):
        ticker  = entry["ticker"].upper()
        periods = [int(p.strip()) for p in str(entry["cycles"]).split(",")]
        period  = entry.get("period", "5y")
        interval = entry.get("interval", "1d")
        start   = entry.get("start")  # date de début fixe optionnelle (AAAA-MM-JJ)
        direction = entry.get("direction", "both")  # long / short / both

        events      = get_events_for_ticker(ticker, periods, period, interval,
                                            start=start, direction=direction)
        periods_str = " + ".join(str(p) for p in periods)
        rank, total = ranks[i]
        dir_tag = {"long": " ↑ LONG", "short": " ↓ SHORT"}.get((direction or "both").lower(), "")
        lines.append(f"<b>{ticker}</b>{_rank_tag(rank, total)}{dir_tag} (cycles {periods_str}b)")

        if not events:
            what = {
                "long":  "alignement HAUSSIER (filtre direction: long)",
                "short": "alignement BAISSIER (filtre direction: short)",
            }.get((direction or "both").lower(), "événement")
            lines.append(
                f"  ⚠ Aucun {what} dans les {MAX_LOOKAHEAD} prochaines barres."
            )
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


# ── Commande /historique ──────────────────────────────────────────────────────

async def _reply_chunks(update: Update, text: str) -> None:
    """Envoie un message en le découpant si nécessaire (limite Telegram ~4096
    caractères), sans jamais couper au milieu d'une ligne."""
    LIMIT = 3500
    buf = ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > LIMIT and buf:
            await update.message.reply_text(buf, parse_mode="HTML")
            buf = ""
        buf += (line + "\n")
    if buf.strip():
        await update.message.reply_text(buf, parse_mode="HTML")


async def handle_historique(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Mémorise le chat ID (comme /prochains) pour les envois proactifs.
    _save_chat_id(str(update.effective_chat.id))
    await update.message.reply_text("⏳ Calcul de l'historique des cycles…")
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
        report = build_history_report(config)
    except Exception as exc:
        await update.message.reply_text(f"❌ Erreur lors du calcul : {exc}")
        return
    await _reply_chunks(update, report)


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

    ranks = _ticker_ranks(alerts_list)
    for i, entry in enumerate(alerts_list):
        ticker   = entry["ticker"].upper()
        periods  = [int(p.strip()) for p in str(entry["cycles"]).split(",")]
        period   = entry.get("period", "5y")
        interval = entry.get("interval", "1d")
        start    = entry.get("start")  # date de début fixe optionnelle (AAAA-MM-JJ)
        direction = entry.get("direction", "both")  # long / short / both

        periods_str = " + ".join(str(p) for p in periods)
        rank, total = ranks[i]
        dir_tag = {"long": " ↑ LONG", "short": " ↓ SHORT"}.get((direction or "both").lower(), "")
        events = get_imminent_events(ticker, periods, period, interval, lookahead,
                                     start=start, direction=direction)
        for e in events:
            # La clé inclut les cycles : deux combinaisons du même ticker ne
            # s'étouffent plus mutuellement quand leurs événements coïncident.
            key = (ticker, periods_str, e.event_type, str(e.est_date))
            seen_now.add(key)
            if key in sent:
                continue  # déjà notifié

            if not alert_lines:
                alert_lines.append(
                    f"<b>🔔 Alerte cyclique — événement(s) dans ≤ {lookahead} barres</b>\n"
                )
            alert_lines.append(f"<b>{ticker}</b>{_rank_tag(rank, total)}{dir_tag} (cycles {periods_str}b)")
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
    app.add_handler(CommandHandler("historique", handle_historique))
    app.add_handler(CommandHandler("history",    handle_historique))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Job quotidien d'alerte proactive — 19h00 UTC (21h00 Paris été / 20h00 hiver).
    # DÉSACTIVABLE : si les alertes sont déjà envoyées par GitHub Actions
    # (check_alerts.py), mettre DISABLE_DAILY_ALERTS=1 pour éviter les doublons.
    # Le bot ne fait alors QUE répondre à /prochains.
    _disable_daily = os.environ.get("DISABLE_DAILY_ALERTS", "").strip().lower() in ("1", "true", "yes", "oui")
    if _disable_daily:
        print("ℹ️  Alertes quotidiennes désactivées (DISABLE_DAILY_ALERTS) — /prochains seulement.")
    else:
        app.job_queue.run_daily(
            check_and_send_alerts,
            time=_dt.time(19, 0, 0, tzinfo=_dt.timezone.utc),
        )

    print("Bot démarré. Envoyez /prochains (prochains événements) ou /historique "
          "(cycles passés) dans Telegram.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
