#!/usr/bin/env python3
"""Envoie une notification Telegram À LA DEMANDE (workflow « Notif Telegram »).

Permet de recevoir sur Telegram, en cliquant « Run workflow » sur GitHub, sans
serveur qui tourne en continu :
  • MODE=futurs      → TOUS les futurs cycles (début / fin estimés)
  • MODE=historique  → les cycles passés DÉJÀ ANNONCÉS (journal cycle_ledger.json)
  • MODE=prochains   → les prochains événements (comme le bot /prochains)

Secrets utilisés : TELEGRAM_TOKEN et TELEGRAM_CHAT_ID (déjà configurés pour les
alertes). Sans secrets → mode DRY RUN (affiche le message dans les logs).
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

from check_alerts import send_telegram
from bot import build_future_report, build_history_report, build_report

MODE = (os.environ.get("MODE") or "futurs").strip().lower()


def _parse_depuis(s: str):
    """Date « depuis » (JJ/MM/AAAA ou AAAA-MM-JJ), ou None si vide/non parsable."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    print(f"⚠ Date « depuis » non reconnue : {s!r} — ignorée.")
    return None


with open("watchlist.yml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

if MODE == "historique":
    message = build_history_report(config, since=_parse_depuis(os.environ.get("DEPUIS", "")))
elif MODE == "prochains":
    message = build_report(config)
else:
    MODE = "futurs"
    message = build_future_report(config)


def _chunks(text: str, limit: int = 3500):
    """Découpe en messages ≤ limite Telegram (~4096) sans couper une ligne."""
    buf = ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > limit and buf:
            yield buf
            buf = ""
        buf += line + "\n"
    if buf.strip():
        yield buf


print(f"MODE={MODE} — envoi de {len(message)} caractères sur Telegram…")
for chunk in _chunks(message):
    send_telegram(chunk)
print("Terminé.")
