#!/usr/bin/env python3
"""Journal des cycles ANNONCÉS sur Telegram.

But : /historique (bot.py) ne doit montrer QUE les cycles déjà affichés sur
Telegram — pas tout l'historique détecté. On tient donc un journal persistant
(`cycle_ledger.json`) : chaque fois que check_alerts.py annonce la FIN d'un
cycle (message « Fin de l'alignement… » qui porte déjà début + fin + rendement),
on enregistre ce cycle. Un cycle dont le DÉBUT est antérieur au suivi Telegram
(avant la 1re fois où la combinaison a été vue) est ignoré.

Le fichier est commité par le workflow GitHub Actions (comme alert_state.json),
puis lu par le bot pour /historique.

Structure du fichier :
{
  "AAPL|100,60|long": {
     "since": "2026-09-19",              # début du suivi de cette combinaison
     "cycles": [
        {"kind": "HAUSSIER", "debut": "2026-10-02", "fin": "2026-12-11",
         "return_pct": 18.4, "shown": "2026-12-10"}
     ]
  }
}
Toutes les dates sont en ISO (AAAA-MM-JJ) → comparables directement.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

LEDGER_FILE = Path("cycle_ledger.json")


def key_of(ticker: str, cycles_str, direction: str = "both") -> str:
    """Clé stable d'une combinaison : 'TICKER|cycles|direction' (mêmes cycles et
    sens que dans watchlist.yml). Identique côté bot et côté alertes."""
    cy = str(cycles_str).replace(" ", "")
    return f"{ticker.upper()}|{cy}|{(direction or 'both').lower()}"


def load() -> dict:
    if LEDGER_FILE.exists():
        try:
            return json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(ledger: dict) -> None:
    try:
        LEDGER_FILE.write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"[journal] Impossible d'écrire {LEDGER_FILE} : {exc}")


def _entry(ledger: dict, key: str) -> dict:
    return ledger.setdefault(key, {"since": None, "cycles": []})


def note_seen(ledger: dict, key: str, today_iso: str) -> None:
    """Mémorise la 1re date où cette combinaison est suivie (début du suivi)."""
    e = _entry(ledger, key)
    if not e.get("since"):
        e["since"] = today_iso


def record_finished(ledger: dict, key: str, kind: str,
                    debut_iso: str, fin_iso: str, return_pct: float,
                    today_iso: str) -> bool:
    """Enregistre (ou actualise) un cycle TERMINÉ annoncé : début → fin + rendement.
    Ignore les cycles dont le début est ANTÉRIEUR au suivi Telegram. Retourne True
    si un cycle a été ajouté/mis à jour."""
    if not debut_iso or not fin_iso:
        return False
    e = _entry(ledger, key)
    if not e.get("since"):
        e["since"] = today_iso
    if debut_iso < e["since"]:
        return False                          # cycle antérieur au suivi → ignoré
    for c in e["cycles"]:                      # déjà présent → on rafraîchit
        if c["kind"] == kind and c["debut"] == debut_iso:
            c["fin"] = fin_iso
            c["return_pct"] = round(float(return_pct), 1)
            c["shown"] = today_iso
            return True
    e["cycles"].append({
        "kind": kind, "debut": debut_iso, "fin": fin_iso,
        "return_pct": round(float(return_pct), 1), "shown": today_iso,
    })
    return True


def past_cycles(ledger: dict, key: str) -> List[dict]:
    """Cycles annoncés (terminés) d'une combinaison, plus récents d'abord."""
    e = ledger.get(key)
    if not e:
        return []
    return sorted(e.get("cycles", []), key=lambda c: c.get("debut", ""), reverse=True)
