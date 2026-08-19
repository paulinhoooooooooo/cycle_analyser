#!/usr/bin/env python3
"""Met à jour cycle_locks.json (verrouillage des dates à J-15).

Lancé chaque soir (workflow d'alerte). Pour chaque ticker de watchlist.yml, il
calcule l'état EN LIVE et verrouille les dates de début/fin qui passent à
<= 15 jours. C'est le SEUL écrivain des verrous ; l'alerte, le récap et le
répondeur ne font que les lire.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from send_digest import get_bull_status
import cycle_locks as cl


def _cal_days(d, today):
    if d is None:
        return None
    dd = d.date() if hasattr(d, "date") else d
    return (dd - today).days


def main() -> None:
    path = Path("watchlist.yml")
    if not path.exists():
        print("watchlist.yml introuvable — rien à faire.")
        return
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    locks = cl.load()
    today = datetime.date.today()

    for e in cfg.get("alerts", []) or []:
        tk = str(e["ticker"]).upper()
        periods = [int(p.strip()) for p in str(e["cycles"]).split(",")]
        key = cl.key_of(tk, str(e["cycles"]), e.get("direction", "both"))
        try:
            st = get_bull_status(tk, periods, e.get("period", "5y"),
                                 e.get("interval", "1d"), e.get("start"))  # LIVE (pas de fige)
        except Exception as exc:
            print(f"  ⚠ {tk} : {exc}")
            continue
        if not st:
            continue
        if st["bull_now"]:
            s_date, s_days = None, None                       # début déjà passé
            e_date, e_days = st["est"], _cal_days(st["est"], today)
        else:
            s_date, s_days = st["est"], _cal_days(st["est"], today)
            e_date, e_days = st["end_est"], _cal_days(st["end_est"], today)
        cl.manage(locks, key, today, s_date, s_days, e_date, e_days)

    cl.save(locks)
    print(f"Verrous mis à jour : {len(locks)} clé(s) active(s).")


if __name__ == "__main__":
    main()
