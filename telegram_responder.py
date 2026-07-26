#!/usr/bin/env python3
"""
Répondeur /prochains — SANS serveur allumé en permanence.

Conçu pour tourner par à-coups sur GitHub Actions (toutes les 5 min). À chaque
réveil : il regarde les nouveaux messages du bot, et si quelqu'un a envoyé
/prochains, il calcule et répond le récap des prochains événements cycliques.

Astuce : Telegram mémorise lui-même la position (offset) des updates. En
confirmant les updates traités (getUpdates avec offset = dernier_id + 1), le
prochain réveil ne verra QUE les nouveaux messages → aucun état à stocker.

Un seul consommateur getUpdates à la fois (les alertes/récap n'utilisent que
sendMessage) → pas de conflit. Ne PAS lancer en parallèle d'un webhook/bot.

Variable d'environnement requise : TELEGRAM_TOKEN
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))

from send_digest import build_digest   # réutilise le générateur de récap /prochains


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Mots qui déclenchent une réponse
_TRIGGERS = ("/prochains", "/start", "prochains")


def get_updates(offset: int = None) -> list:
    params = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(f"{API}/getUpdates", params=params, timeout=30)
        data = r.json()
    except Exception as exc:
        print(f"[getUpdates] erreur : {exc}")
        return []
    if not data.get("ok"):
        print(f"[getUpdates] réponse Telegram : {data}")
        return []
    return data.get("result", [])


def send(chat_id, text: str) -> None:
    try:
        requests.post(f"{API}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        }, timeout=20)
    except Exception as exc:
        print(f"[sendMessage] erreur : {exc}")


def main() -> None:
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN non défini — arrêt.")
        sys.exit(1)

    updates = get_updates()
    if not updates:
        print("Aucun nouveau message.")
        return

    max_id = max(u["update_id"] for u in updates)

    # Chats ayant demandé /prochains à ce réveil (déduplique si envoyé plusieurs fois)
    asked = []
    for u in updates:
        msg = u.get("message") or u.get("edited_message")
        if not msg:
            continue
        text = (msg.get("text") or "").strip().lower()
        chat_id = msg.get("chat", {}).get("id")
        if chat_id is not None and any(text.startswith(t) for t in _TRIGGERS):
            if chat_id not in asked:
                asked.append(chat_id)

    if asked:
        # Accusé de réception immédiat (le calcul prend ~30-60 s)
        for chat_id in asked:
            send(chat_id, "⏳ Je calcule tes prochains événements cycliques…")

        config_path = Path("watchlist.yml")
        if config_path.exists():
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            digest = build_digest(config)
        else:
            digest = "❌ watchlist.yml introuvable sur le serveur."

        for chat_id in asked:
            send(chat_id, digest)
            print(f"✓ Répondu à /prochains pour le chat {chat_id}")
    else:
        print(f"{len(updates)} update(s), aucun /prochains.")

    # Confirmer les updates traités → Telegram les oublie, le prochain réveil
    # ne verra que les messages suivants.
    get_updates(offset=max_id + 1)


if __name__ == "__main__":
    main()
