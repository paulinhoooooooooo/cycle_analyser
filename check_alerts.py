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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import CycleInfo, _detrend_log, _fit_sine, _phase_state
from cycle_freeze import load_frozen
import cycle_locks as _cl


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Anti-doublon ────────────────────────────────────────────────────────────
# On mémorise, par combinaison (ticker|cycles|direction), le dernier JOUR
# calendaire où on a notifié. Objectif : au plus une notification par jour et
# par combinaison, pour éviter un double envoi si le workflow tourne deux fois
# le même jour (cron + déclenchement manuel). Le compte à rebours étant
# calendaire (J-3 → J-2 → J-1), il change chaque jour : les week-ends restent
# donc bien notifiés. Fichier recommité par le workflow (comme cycle_locks.json).
import json

ALERT_STATE_FILE = Path("alert_state.json")


def _load_alert_state() -> dict:
    try:
        return json.loads(ALERT_STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_alert_state(state: dict) -> None:
    ALERT_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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


def _est_future_date(dates, bars_ahead: int):
    """Date estimée à +bars_ahead barres, par extrapolation de l'espacement
    calendaire RÉEL (s'adapte aux marchés 5j/7 actions et 7j/7 crypto)."""
    last = dates[-1]
    if len(dates) < 2:
        return last
    avg_days = (dates[-1] - dates[0]).days / max(len(dates) - 1, 1)
    return last + timedelta(days=int(round(bars_ahead * avg_days)))


def _parse_ddmmyyyy(s: str) -> Optional[date]:
    """Parse une date affichée 'JJ/MM/AAAA' en date. None si non parsable
    (ex. 'au-delà de l'horizon')."""
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").date()
    except (ValueError, AttributeError):
        return None


def _countdown_days(event: date, today: date) -> int:
    """Nombre de JOURS CALENDAIRES d'aujourd'hui jusqu'à l'événement.
    Compté en calendaire (et non en barres de trading) pour que le compte à
    rebours descende chaque jour, week-ends et jours fériés compris."""
    return (event - today).days


def _cd_label(n: int) -> str:
    """'dans 2 jours (J-2)' — libellé calendaire du compte à rebours."""
    jour = "jour" if n == 1 else "jours"
    return f"dans <b>{n} {jour}</b> (J-{n})"


def _current_zone_stats(cycles, prices, N: int, t_today: float, want_bull: bool):
    """Pour un cycle EN COURS (haussier si want_bull, sinon baissier), remonte les
    barres jusqu'à la 1re barre du run pour trouver la DATE DE DÉBUT et le
    RENDEMENT depuis ce début (même méthode que send_digest.get_bull_status).
    Retourne (start_bar, ret_pct). Pour un cycle baissier, le rendement est
    inversé (une baisse du prix = gain pour une position short)."""
    idx = 0 if want_bull else 1                     # 0 = haussier, 1 = baissier
    j = int(round(t_today))
    while j - 1 >= 1 and _state_at(cycles, float(j - 1))[idx]:
        j -= 1
    start_bar = max(0, j)
    p0 = float(prices[start_bar])
    p1 = float(prices[N - 1])
    change = ((p1 - p0) / p0 * 100.0) if p0 else 0.0
    ret = change if want_bull else -change
    return start_bar, ret


def _zone_end_offset(cycles: List[CycleInfo], t_last: float, start_off: int,
                     want_bull: bool, max_ahead: int = 1500):
    """À partir de la 1re barre de la zone (start_off barres après la dernière
    donnée), avance jusqu'à ce que l'alignement s'arrête. Retourne le décalage
    (en barres) de la fin de zone, ou None si elle dépasse l'horizon."""
    j = start_off
    while j < start_off + max_ahead:
        bull, bear = _state_at(cycles, t_last + j)
        if not (bull if want_bull else bear):
            return j
        j += 1
    return None


def check_ticker(
    ticker: str,
    periods: List[int],
    period: str,
    interval: str,
    lookahead: int,
    start: str = None,
    rank_tag: str = "",
    direction: str = "both",
    stats: str = "",
    fige: str = None,
    locked_start: str = None,
    locked_end: str = None,
    today: Optional[date] = None,
) -> Tuple[List[str], Optional[str]]:
    """Retourne (messages, date_des_données) pour ce ticker.
    ``stats`` : ligne de backtest optionnelle (rendement/zones/réussite) ajoutée
    en pied de chaque alerte — purement informative.
    ``fige`` : date de référence (JJ/MM/AAAA). Si présente, les dates de début/fin
    du cycle sont FIGÉES (ne bougent plus jour après jour) ; seul le compte à
    rebours J-3/J-2/J-1 décroît. Voir cycle_freeze.load_frozen.

    Le compte à rebours est en JOURS CALENDAIRES d'aujourd'hui (``today``) jusqu'à
    la date estimée de l'événement — pas en barres de trading. Il descend donc
    chaque jour, week-ends et jours fériés compris (la date de l'événement est
    stable même quand la bourse est fermée : aucune nouvelle donnée)."""
    if today is None:
        today = date.today()
    try:
        cycles, dates, prices, N, t_today, date_of, n_ref = load_frozen(
            ticker, periods, period, interval, start=start, fige=fige)
    except Exception as exc:
        print(f"  ⚠ Erreur fetch {ticker} : {exc}")
        return [], None

    last_date = dates[-1].strftime("%d/%m/%Y")
    periods_str = " + ".join(str(p) for p in periods)

    messages: List[str] = []

    # On balaie un horizon de barres un peu plus large que lookahead : l'événement
    # est daté (date_of), puis le compte à rebours est calculé en JOURS
    # CALENDAIRES jusqu'à cette date, et filtré sur 1..lookahead jours. L'horizon
    # élargi garantit qu'un événement « à J-lookahead » (jours) reste capté même
    # quand une barre de trading couvre >1 jour calendaire (actions : ~1,4 j/barre).
    periods_detail = " | ".join(f"{p}j" for p in periods)
    d = (direction or "both").lower()
    want_long = d in ("long", "both")
    want_short = d in ("short", "both")

    for k in range(1, lookahead + 6):
        bull_before, bear_before = _state_at(cycles, t_today + k - 1)
        bull_after, bear_after = _state_at(cycles, t_today + k)
        bars = max(1, k - 1)

        if want_long and not bull_before and bull_after:
            start_str = locked_start or date_of(t_today + bars).strftime("%d/%m/%Y")
            ev = _parse_ddmmyyyy(start_str)
            n = _countdown_days(ev, today) if ev else None
            if n is not None and 1 <= n <= lookahead:
                end_off = _zone_end_offset(cycles, t_today, k, want_bull=True)
                end_str = locked_end or (date_of(t_today + end_off).strftime("%d/%m/%Y")
                                         if end_off is not None else "au-delà de l'horizon")
                messages.append(
                    f"🟢 <b>{ticker}</b>{rank_tag} — Cycles {periods_str}b ({periods_detail})\n"
                    f"📈 Début alignement <b>HAUSSIER</b> {_cd_label(n)}\n"
                    f"🚀 Début du cycle : <b>{start_str}</b>\n"
                    f"🏁 Fin du cycle : <b>{end_str}</b>\n"
                    f"📅 Données au {last_date}"
                )

        if want_long and bull_before and not bull_after:
            end_ev_str = locked_end or date_of(t_today + bars).strftime("%d/%m/%Y")
            ev = _parse_ddmmyyyy(end_ev_str)
            n = _countdown_days(ev, today) if ev else None
            if n is not None and 1 <= n <= lookahead:
                start_bar, ret = _current_zone_stats(cycles, prices, N, t_today, want_bull=True)
                cyc_start = locked_start or date_of(start_bar).strftime("%d/%m/%Y")
                messages.append(
                    f"🔴 <b>{ticker}</b>{rank_tag} — Cycles {periods_str}b ({periods_detail})\n"
                    f"📉 Fin de l'alignement <b>HAUSSIER</b> {_cd_label(n)}\n"
                    f"🚀 Début du cycle : <b>{cyc_start}</b>\n"
                    f"📈 <b>{ret:+.1f}%</b> depuis le début\n"
                    f"🏁 Sommet du cycle : <b>{end_ev_str}</b>\n"
                    f"📅 Données au {last_date}"
                )

        if want_short and not bear_before and bear_after:
            start_str = locked_start or date_of(t_today + bars).strftime("%d/%m/%Y")
            ev = _parse_ddmmyyyy(start_str)
            n = _countdown_days(ev, today) if ev else None
            if n is not None and 1 <= n <= lookahead:
                end_off = _zone_end_offset(cycles, t_today, k, want_bull=False)
                end_str = locked_end or (date_of(t_today + end_off).strftime("%d/%m/%Y")
                                         if end_off is not None else "au-delà de l'horizon")
                messages.append(
                    f"🔴 <b>{ticker}</b>{rank_tag} — Cycles {periods_str}b ({periods_detail})\n"
                    f"📉 Début alignement <b>BAISSIER</b> {_cd_label(n)}\n"
                    f"🚀 Début du cycle : <b>{start_str}</b>\n"
                    f"🏁 Fin du cycle : <b>{end_str}</b>\n"
                    f"📅 Données au {last_date}"
                )

        if want_short and bear_before and not bear_after:
            end_ev_str = locked_end or date_of(t_today + bars).strftime("%d/%m/%Y")
            ev = _parse_ddmmyyyy(end_ev_str)
            n = _countdown_days(ev, today) if ev else None
            if n is not None and 1 <= n <= lookahead:
                start_bar, ret = _current_zone_stats(cycles, prices, N, t_today, want_bull=False)
                cyc_start = locked_start or date_of(start_bar).strftime("%d/%m/%Y")
                messages.append(
                    f"🔴 <b>{ticker}</b>{rank_tag} — Cycles {periods_str}b ({periods_detail})\n"
                    f"📈 Fin de l'alignement <b>BAISSIER</b> {_cd_label(n)}\n"
                    f"🚀 Début du cycle : <b>{cyc_start}</b>\n"
                    f"📊 <b>{ret:+.1f}%</b> depuis le début (short)\n"
                    f"🏁 Creux du cycle : <b>{end_ev_str}</b>\n"
                    f"📅 Données au {last_date}"
                )

    if stats:
        messages = [f"{m}\n{stats}" for m in messages]
    return messages, last_date


def _backtest_note(entry: dict) -> str:
    """Ligne d'info optionnelle (rendement / zones / réussite) saisie À LA MAIN
    dans watchlist.yml. Purement informatif : n'influence AUCUN calcul de cycle.
    Champs acceptés : rdt|rendement, zones, reussite|réussite|success."""
    rdt = entry.get("rdt", entry.get("rendement"))
    zones = entry.get("zones")
    reuss = entry.get("reussite", entry.get("réussite", entry.get("success")))
    bits = []
    if rdt is not None:
        try:
            v = float(str(rdt).replace(",", "."))   # tolère la virgule française
            bits.append(f"Rdt {v:+g}%".replace(".", ","))
        except (TypeError, ValueError):
            bits.append(f"Rdt {rdt}")
    if zones is not None:
        bits.append(f"{zones} zones")
    if reuss is not None:
        try:
            v = float(str(reuss).replace(",", "."))
            bits.append(f"réussite {v:g}%".replace(".", ","))
        except (TypeError, ValueError):
            bits.append(f"réussite {reuss}")
    return ("📊 Backtest : " + " · ".join(bits)) if bits else ""


def main() -> None:
    config_path = Path("watchlist.yml")
    if not config_path.exists():
        print("Fichier watchlist.yml introuvable.")
        sys.exit(1)

    with config_path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)

    lookahead = int(config.get("lookaheadBars", 3))
    alerts_list = config.get("alerts", [])
    _locks = _cl.load()   # verrous J-15 (lecture seule)
    _state = _load_alert_state()   # anti-doublon (dernier JOUR déjà notifié / combinaison)
    _today = date.today()
    _today_iso = _today.isoformat()

    print(f"Vérification de {len(alerts_list)} ticker(s) — J-{lookahead}…")

    # Rang par ticker : l'ordre dans watchlist.yml fait le classement
    # (1re entrée d'un ticker = #1 = combinaison la plus puissante).
    counts: dict = {}
    for entry in alerts_list:
        tk = entry["ticker"].upper()
        counts[tk] = counts.get(tk, 0) + 1
    seen: dict = {}
    rank_icons = {1: "🥇", 2: "🥈", 3: "🥉"}

    total_sent = 0
    for entry in alerts_list:
        ticker = entry["ticker"].upper()
        periods = [int(p.strip()) for p in str(entry["cycles"]).split(",")]
        period = entry.get("period", "5y")
        interval = entry.get("interval", "1d")
        start = entry.get("start")  # date de début fixe optionnelle (AAAA-MM-JJ)
        direction = entry.get("direction", "both")  # long / short / both
        fige = entry.get("fige")  # date de figeage optionnelle (dates de cycle figées)

        seen[ticker] = seen.get(ticker, 0) + 1
        rank_tag = ""
        if counts[ticker] > 1:
            rank_tag = f" {rank_icons.get(seen[ticker], '▫️')} <b>#{seen[ticker]}</b>"
        rank_tag += {"long": " ↑ LONG", "short": " ↓ SHORT"}.get((direction or "both").lower(), "")

        stats = _backtest_note(entry)
        _k = _cl.key_of(ticker, str(entry["cycles"]), direction)
        print(f"  {ticker} ({' + '.join(str(p) for p in periods)}b)… ", end="", flush=True)
        messages, data_date = check_ticker(ticker, periods, period, interval, lookahead,
                                start=start, rank_tag=rank_tag, direction=direction,
                                stats=stats, fige=fige,
                                locked_start=_cl.locked_start(_locks, _k),
                                locked_end=_cl.locked_end(_locks, _k),
                                today=_today)

        if messages:
            # Anti-doublon : au plus UNE notification par jour et par combinaison.
            # Le compte à rebours étant calendaire (J-3 → J-2 → J-1), il change de
            # toute façon chaque jour ; ce garde-fou évite seulement un double envoi
            # si le workflow tourne deux fois le même jour (cron + déclenchement
            # manuel). Les week-ends restent notifiés (le J-N descend quand même).
            if _state.get(_k) == _today_iso:
                print(f"déjà notifié aujourd'hui ({_today_iso}) — ignoré")
            else:
                for msg in messages:
                    send_telegram(msg)
                    total_sent += 1
                _state[_k] = _today_iso
                print(f"{len(messages)} alerte(s) envoyée(s)")
        else:
            print("aucune alerte aujourd'hui")

    _save_alert_state(_state)
    print(f"\nTerminé — {total_sent} alerte(s) au total.")


if __name__ == "__main__":
    main()
