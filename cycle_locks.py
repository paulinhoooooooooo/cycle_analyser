#!/usr/bin/env python3
"""Verrouillage des dates de cycle à J-15 (idée 2).

Principe : les notifications calculent EN LIVE la plupart du temps. Dès qu'un
DÉBUT (ou une FIN) de cycle passe à 15 jours calendaires ou moins, sa date se
VERROUILLE dans cycle_locks.json et ne bouge plus — même si le live change —
jusqu'à ce que le cycle soit terminé. Ainsi les alertes J-3/J-2/J-1 sont stables.

État : cycle_locks.json = { "TICKER|cycles|direction": {"start": "JJ/MM/AAAA",
"end": "JJ/MM/AAAA"} }. Le début reste figé tant que la fin n'est pas passée
(cycle complet stable). Écrit UNIQUEMENT par l'alerte du soir ; lu par tout le
monde (alerte, récap, répondeur).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

LOCK_FILE = Path("cycle_locks.json")
WINDOW_DAYS = 15          # verrouille quand l'événement est à <= 15 jours calendaires
_MAX_ORPHAN_DAYS = 500    # sécurité : purge un verrou 'start' orphelin très vieux


def load() -> dict:
    if LOCK_FILE.exists():
        try:
            return json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(locks: dict) -> None:
    LOCK_FILE.write_text(json.dumps(locks, indent=2, ensure_ascii=False), encoding="utf-8")


def key_of(ticker: str, cycles_str: str, direction: str) -> str:
    return f"{str(ticker).upper()}|{cycles_str}|{(direction or 'both').lower()}"


def _to_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, date):
        return v
    if hasattr(v, "date"):
        return v.date()
    try:
        return pd.to_datetime(str(v), dayfirst=True).date()
    except Exception:
        return None


def _fmt(d) -> str:
    d = _to_date(d)
    return d.strftime("%d/%m/%Y")


def manage(locks: dict, key: str, today: date,
           start_date, days_to_start: Optional[int],
           end_date, days_to_end: Optional[int]) -> dict:
    """Met à jour les verrous start/end d'une clé, en LIVE, pour la date du jour.

    start_date/end_date : dates estimées EN LIVE (ou None). days_to_* : jours
    calendaires jusqu'à l'événement (ou None). Verrouille à <= WINDOW_DAYS.
    Le début reste verrouillé jusqu'à ce que la fin soit passée."""
    ent = dict(locks.get(key, {}))

    end_lock = _to_date(ent.get("end"))
    start_lock = _to_date(ent.get("start"))

    # 1) Fin verrouillée passée -> cycle terminé -> on ré-arme tout.
    if end_lock is not None and today > end_lock:
        ent = {}
        start_lock = end_lock = None
    # 2) Début verrouillé orphelin très vieux (pas de fin) -> purge sécurité.
    elif start_lock is not None and end_lock is None and today > start_lock + timedelta(days=_MAX_ORPHAN_DAYS):
        ent.pop("start", None)
        start_lock = None

    # 3) Verrouillage du DÉBUT : à <= 15 j et pas déjà verrouillé.
    if "start" not in ent and days_to_start is not None and 0 <= days_to_start <= WINDOW_DAYS \
            and start_date is not None:
        ent["start"] = _fmt(start_date)

    # 4) Verrouillage de la FIN : à <= 15 j et pas déjà verrouillée.
    if "end" not in ent and days_to_end is not None and 0 <= days_to_end <= WINDOW_DAYS \
            and end_date is not None:
        ent["end"] = _fmt(end_date)

    if ent:
        locks[key] = ent
    elif key in locks:
        del locks[key]
    return locks


def locked_start(locks: dict, key: str) -> Optional[str]:
    return locks.get(key, {}).get("start")


def locked_end(locks: dict, key: str) -> Optional[str]:
    return locks.get(key, {}).get("end")


def apply_to_status(st: dict, locks: dict, key: str) -> dict:
    """Remplace dans un dict get_bull_status les dates par leur version
    VERROUILLÉE si elle existe (le compte à rebours 'bars' reste live)."""
    if not st:
        return st
    ls, le = locked_start(locks, key), locked_end(locks, key)
    def _ts(s):
        return pd.to_datetime(s, dayfirst=True)
    if st.get("bull_now"):
        if le:
            st["est"] = _ts(le)          # est = prochaine transition = FIN
        if ls:
            st["start"] = _ts(ls)        # début (passé) figé
    else:
        if ls:
            st["est"] = _ts(ls)          # est = DÉBUT
        if le:
            st["end_est"] = _ts(le)      # fin du cycle à venir
    return st
