#!/usr/bin/env python3
"""
Récapitulatif cyclique quotidien — équivalent GRATUIT de la commande /prochains.

Pour CHAQUE ticker de watchlist.yml, calcule les 2 prochains événements cycliques
(début/fin d'alignement haussier/baissier) et envoie UN message récapitulatif sur
Telegram. Conçu pour tourner sur GitHub Actions (gratuit) — aucun serveur 24/7.

Usage :
  python send_digest.py                        # utilise watchlist.yml
  TELEGRAM_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python send_digest.py

Sans les secrets Telegram, le récap est affiché dans la console (dry-run).
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

import numpy as np
import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import CycleInfo, _detrend_log, _fit_sine, _phase_state


TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
MAX_LOOKAHEAD    = 300   # barres max explorées (~1 an de trading)


_TG_LIMIT = 3800   # marge sous la limite Telegram (4096 caractères / message)


def _chunks(text: str, limit: int = _TG_LIMIT) -> list:
    """Découpe un texte long en morceaux <= limit, sur les sauts de ligne."""
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                parts.append(cur); cur = ""
            parts.append(line[:limit]); line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            if cur:
                parts.append(cur)
            cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        parts.append(cur)
    return parts


def send_telegram(message: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[DRY RUN — pas de secrets Telegram]\n{message}\n")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Découpe si > limite Telegram, sinon le message long est rejeté (erreur 400).
    for part in _chunks(message):
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": part,
            "parse_mode": "HTML",
        }, timeout=15)
        if not resp.ok:
            print(f"Erreur Telegram : {resp.status_code} {resp.text}")


# ── Événements cycliques (mêmes calculs que le bot /prochains) ─────────────────

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


def _transitions_at(bull_before, bull_after, bear_before, bear_after) -> List[str]:
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


def _event_in_direction(event_type: str, direction: str) -> bool:
    d = (direction or "both").lower()
    if d == "long":
        return event_type.startswith("HAUSSIER")
    if d == "short":
        return event_type.startswith("BAISSIER")
    return True


def _est_future_date(dates_idx, bars_ahead: int) -> date:
    """Date estimée à +bars_ahead barres, par extrapolation de l'espacement
    calendaire RÉEL (s'adapte aux marchés 5j/7 actions et 7j/7 crypto)."""
    last = dates_idx[-1]
    if len(dates_idx) < 2:
        return last.date() if hasattr(last, "date") else last
    avg_days = (dates_idx[-1] - dates_idx[0]).days / max(len(dates_idx) - 1, 1)
    future = last + timedelta(days=int(round(bars_ahead * avg_days)))
    return future.date() if hasattr(future, "date") else future


def _build_cycles(prices: np.ndarray, periods: List[int]) -> List[CycleInfo]:
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
    return cycles


def get_next_events(
    ticker: str,
    periods: List[int],
    period: str,
    interval: str,
    start: Optional[str] = None,
    direction: str = "both",
    max_events: int = 2,
) -> List[CycleEvent]:
    """Les `max_events` prochains événements cycliques pour ce ticker.
    TOUT est protégé : un ticker fautif (données vides, calcul qui échoue…)
    renvoie [] au lieu de casser le récap complet."""
    try:
        data = fetch_data(ticker, period=period, interval=interval, start=start)
        prices    = get_close_prices(data)
        dates_idx = get_dates(data)
        if prices is None or len(prices) < 30:
            print(f"  ⚠ {ticker} : pas assez de données ({0 if prices is None else len(prices)} barres)")
            return []
        cycles = _build_cycles(prices, periods)
        t_last = float(len(prices) - 1)
        periods_str = " + ".join(str(p) for p in periods)
        events: List[CycleEvent] = []

        for k in range(1, MAX_LOOKAHEAD + 1):
            bull_before, bear_before = _state_at(cycles, t_last + k - 1)
            bull_after,  bear_after  = _state_at(cycles, t_last + k)
            # L'événement (pic/creux) est à la barre k-1, comme sur le graphe.
            bar = max(1, k - 1)
            est = _est_future_date(dates_idx, bar)
            for et in _transitions_at(bull_before, bull_after, bear_before, bear_after):
                if _event_in_direction(et, direction):
                    events.append(CycleEvent(ticker, periods_str, et, bar, est))
            if len(events) >= max_events:
                break

        events.sort(key=lambda e: e.bars_away)
        return events[:max_events]
    except Exception as exc:
        print(f"  ⚠ Erreur {ticker} : {exc}")
        return []


# ── Mise en forme du message ──────────────────────────────────────────────────

_RANK_ICONS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _rank_tag(rank: int, total: int) -> str:
    if total <= 1:
        return ""
    icon = _RANK_ICONS.get(rank, "▫️")
    return f" {icon} <b>#{rank}</b>"


def _event_line(e: CycleEvent) -> str:
    icons = {
        "HAUSSIER_DEBUT": "🟢📈", "HAUSSIER_FIN": "🟢📉",
        "BAISSIER_DEBUT": "🔴📉", "BAISSIER_FIN": "🔴📈",
    }
    labels = {
        "HAUSSIER_DEBUT": "Début alignement HAUSSIER",
        "HAUSSIER_FIN":   "Fin alignement HAUSSIER",
        "BAISSIER_DEBUT": "Début alignement BAISSIER",
        "BAISSIER_FIN":   "Fin alignement BAISSIER",
    }
    icon  = icons.get(e.event_type, "⚪")
    label = labels.get(e.event_type, e.event_type)
    date_str = e.est_date.strftime("%d/%m/%Y") if e.est_date else "?"
    bar_word = "barre" if e.bars_away == 1 else "barres"
    periods_detail = " | ".join(f"{p}j" for p in e.periods_str.split(" + "))
    return (
        f"{icon} {label} dans <b>{e.bars_away} {bar_word}</b> "
        f"(~{date_str}) — cycles : {periods_detail}"
    )


def _idx_to_date(dates_idx, i):
    d = dates_idx[int(i)]
    return d.date() if hasattr(d, "date") else d


def get_bull_status(ticker, periods, period, interval, start=None):
    """État du cycle HAUSSIER (tous les cycles alignés à la hausse) pour ce ticker.
    Renvoie un dict :
      bull_now : bool
      bars     : int|None  — barres jusqu'à la prochaine transition (restantes si en
                             hausse ; avant le début sinon). None si hors horizon.
      est      : date|None — date de cette transition
      start    : date|None — (si en hausse) date de début du cycle haussier en cours
      ret      : float|None — (si en hausse) rendement % depuis le début du cycle
    Renvoie None si le calcul échoue (données indispo, etc.)."""
    try:
        data = fetch_data(ticker, period=period, interval=interval, start=start)
        prices = get_close_prices(data)
        dates_idx = get_dates(data)
        if prices is None or len(prices) < 30:
            print(f"  ⚠ {ticker} : pas assez de données")
            return None
        cycles = _build_cycles(prices, periods)
        N = len(prices)
        t_last = float(N - 1)
        bull_now = _state_at(cycles, t_last)[0]      # tous les cycles montent-ils ?

        # Prochaine transition (fin de hausse si en hausse ; début sinon)
        bars = None
        for k in range(1, MAX_LOOKAHEAD + 1):
            if _state_at(cycles, t_last + k)[0] != bull_now:
                bars = max(1, k - 1)                 # barre du pic/creux (comme le graphe)
                break
        est = _est_future_date(dates_idx, bars) if bars else None

        # Si EN hausse : remonter pour trouver le DÉBUT du cycle haussier en cours
        start_date = ret = None
        if bull_now:
            j = N - 1
            while j - 1 >= 1 and _state_at(cycles, float(j - 1))[0]:
                j -= 1
            start_bar = j                             # première barre haussière du run
            start_date = _idx_to_date(dates_idx, start_bar)
            p0 = float(prices[start_bar]); p1 = float(prices[N - 1])
            ret = ((p1 - p0) / p0 * 100.0) if p0 else 0.0

        return {"bull_now": bull_now, "bars": bars, "est": est,
                "start": start_date, "ret": ret}
    except Exception as exc:
        print(f"  ⚠ Erreur {ticker} : {exc}")
        return None


def build_digest(config: dict) -> str:
    """Récap trié par cycle HAUSSIER :
      1) d'abord les tickers EN cycle haussier, du plus PROCHE DE LA FIN au plus
         loin (le moins de barres restantes d'abord) ;
      2) puis ceux les plus PROCHES d'un début de cycle haussier (le plus proche
         d'abord) ;
      3) enfin les données indisponibles."""
    alerts_list = config.get("alerts", [])
    if not alerts_list:
        return "Aucun ticker dans watchlist.yml."

    # Rang par ticker (l'ordre dans le fichier fait le classement).
    counts: dict = {}
    for entry in alerts_list:
        tk = entry["ticker"].upper()
        counts[tk] = counts.get(tk, 0) + 1
    seen: dict = {}

    BIG = MAX_LOOKAHEAD + 1
    rows = []   # (clé_de_tri, en-tête, ligne d'état)
    for i, entry in enumerate(alerts_list):
        ticker   = entry["ticker"].upper()
        periods  = [int(p.strip()) for p in str(entry["cycles"]).split(",")]
        period   = entry.get("period", "5y")
        interval = entry.get("interval", "1d")
        start    = entry.get("start")
        direction = entry.get("direction", "both")

        seen[ticker] = seen.get(ticker, 0) + 1
        rank, total = seen[ticker], counts[ticker]
        dir_tag = {"long": " ↑ LONG", "short": " ↓ SHORT"}.get((direction or "both").lower(), "")
        periods_str = " + ".join(str(p) for p in periods)
        header = f"<b>{ticker}</b>{_rank_tag(rank, total)}{dir_tag} (cycles {periods_str}b)"

        st = get_bull_status(ticker, periods, period, interval, start)
        if st is None:
            key = (3, 0, i)
            line = "⚠ Données indisponibles."
        else:
            bull_now, bars, est = st["bull_now"], st["bars"], st["est"]
            date_str = est.strftime("%d/%m/%Y") if est else "?"
            b = bars if bars is not None else BIG
            if bull_now:
                key = (0, b, i)    # EN hausse : le plus PROCHE DE LA FIN d'abord (moins de barres restantes)
                line = (f"🟢 <b>EN cycle HAUSSIER</b> — encore <b>{bars} barres</b> (fin ~{date_str})"
                        if bars is not None
                        else "🟢 <b>EN cycle HAUSSIER</b> (fin au-delà de l'horizon)")
                # Sous-ligne : depuis quand le cycle dure + rendement depuis le début
                if st["start"] is not None:
                    start_str = st["start"].strftime("%d/%m/%Y")
                    ret = st["ret"] if st["ret"] is not None else 0.0
                    line += f"\n  ▸ Début le {start_str} · <b>{ret:+.1f}%</b> depuis le début"
            else:
                key = (1, b, i)    # pré-hausse : le plus proche du début d'abord
                line = (f"🔜 Début HAUSSIER dans <b>{bars} barres</b> (~{date_str})"
                        if bars is not None
                        else f"⚪ Pas de début haussier dans les {MAX_LOOKAHEAD} prochaines barres")
        rows.append((key, header, line))

    rows.sort(key=lambda r: r[0])

    out = ["<b>📊 Cycles haussiers — en cours d'abord, puis les plus proches</b>\n"]
    for _, header, line in rows:
        out.append(header)
        out.append(f"  {line}")
        out.append("")
    return "\n".join(out).strip()


def main() -> None:
    config_path = Path("watchlist.yml")
    if not config_path.exists():
        print("Fichier watchlist.yml introuvable.")
        sys.exit(1)

    with config_path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)

    alerts_list = config.get("alerts", [])
    print(f"Récap de {len(alerts_list)} ticker(s)…")
    digest = build_digest(config)
    send_telegram(digest)
    print("Terminé — récap envoyé.")


if __name__ == "__main__":
    main()
