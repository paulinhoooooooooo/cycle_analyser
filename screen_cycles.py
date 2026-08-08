#!/usr/bin/env python3
"""Screener de cycles — dis-moi quelles entreprises ont un cycle intéressant.

Pour chaque ticker fourni : détecte les cycles (FFT, comme le logiciel), teste
les combinaisons, retient la MEILLEURE combinaison FIABLE, et attribue un
verdict :
  ⭐⭐ TRÈS INTÉRESSANT · ⭐ INTÉRESSANT · ➖ MOYEN · ✗ PEU CYCLIQUE

« Fiable » = assez de zones (répétitions) + bonne réussite. Un rendement énorme
sur 4 zones (cycle trop long qui suit la tendance) n'est PAS retenu comme fiable.

Entrées (variables d'environnement) :
  TICKERS        : liste de symboles Yahoo, séparés par espace/virgule/retour ligne
  SCREEN_PERIOD  : fenêtre d'historique (défaut « 10y »)
  TELEGRAM_TOKEN / TELEGRAM_CHAT_ID : si présents, envoie aussi le résultat sur Telegram

Usage local :  TICKERS="XLE XME GDX EWZ" python screen_cycles.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices
from cycle_analyzer.cycle_detector import detect_cycles
from cycle_analyzer.combination_analyzer import analyze_combinations

# ── Seuils de « fiabilité » ───────────────────────────────────────────────────
MIN_ZONES_FIABLE = 10     # au moins 10 répétitions du cycle
MIN_HIT_FIABLE   = 75.0   # au moins 75 % de zones gagnantes
SEUIL_TRES       = 150.0  # rdt d'une combo fiable ≥ 150 % → ⭐⭐
SEUIL_INTER      = 80.0   # rdt d'une combo fiable ≥ 80 %  → ⭐


def _best_combos(prices):
    """Retourne la liste des combos LONG (tailles 1,2,3) avec (periods, rdt, zones, hit)."""
    cycles = detect_cycles(prices, min_period=15, max_period=min(300, len(prices) // 3))
    if not cycles:
        return []
    res = analyze_combinations(prices, cycles, top_n_per_size=5)
    out = []
    for size in (1, 2, 3):
        for cr in res.get(size, []) or []:
            if cr is None:
                continue
            out.append((list(cr.periods), float(cr.total_return_pct),
                        int(cr.n_zones), float(cr.hit_rate)))
    return out


def screen_ticker(ticker, period):
    """Retourne dict(verdict_rank, verdict, best=(periods,rdt,zones,hit)) ou None si data KO."""
    data = fetch_data(ticker, period=period, interval="1d")
    prices = get_close_prices(data)
    if len(prices) < 200:
        return dict(rank=4, verdict="✗ HISTORIQUE TROP COURT", best=None)

    combos = _best_combos(prices)
    if not combos:
        return dict(rank=4, verdict="✗ PEU CYCLIQUE", best=None)

    fiables = [c for c in combos if c[2] >= MIN_ZONES_FIABLE and c[3] >= MIN_HIT_FIABLE and c[1] > 0]
    if fiables:
        best = max(fiables, key=lambda c: c[1])           # meilleure combo fiable par rdt
        if best[1] >= SEUIL_TRES:
            return dict(rank=0, verdict="⭐⭐ TRÈS INTÉRESSANT", best=best)
        if best[1] >= SEUIL_INTER:
            return dict(rank=1, verdict="⭐ INTÉRESSANT", best=best)
        return dict(rank=2, verdict="➖ MOYEN", best=best)

    # Pas de combo fiable → on montre quand même la meilleure « brute » comme repère
    moyen = [c for c in combos if c[2] >= 6 and c[1] > 0]
    if moyen:
        best = max(moyen, key=lambda c: c[1])
        return dict(rank=3, verdict="➖ MOYEN (peu de répétitions)", best=best)
    return dict(rank=4, verdict="✗ PEU CYCLIQUE", best=None)


def _parse_tickers(raw: str):
    return [t for t in re.split(r"[\s,;]+", (raw or "").strip().upper()) if t]


def _send_telegram(text: str):
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("(Pas de secrets Telegram → envoi ignoré, résultat dans le log seulement.)")
        return
    # Découpe sous la limite Telegram (4096) sur les sauts de ligne
    limit, parts, cur = 3800, [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur); cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        parts.append(cur)
    for part in parts:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": part, "parse_mode": "HTML"}, timeout=20)
        except Exception as exc:
            print(f"[telegram] {exc}")


def main():
    tickers = _parse_tickers(os.environ.get("TICKERS", ""))
    period = os.environ.get("SCREEN_PERIOD", "10y").strip() or "10y"
    if not tickers:
        print("❌ Aucun ticker. Renseigne TICKERS (ex: \"XLE XME GDX EWZ\").")
        sys.exit(1)

    print(f"Screening de {len(tickers)} ticker(s) sur {period}…\n")
    rows = []
    for tk in tickers:
        try:
            r = screen_ticker(tk, period)
        except Exception as exc:
            print(f"  ⚠ {tk} -> erreur : {exc}")
            rows.append((5, tk, "⚠ DONNÉES INDISPONIBLES", None))
            continue
        rows.append((r["rank"], tk, r["verdict"], r["best"]))
        b = r["best"]
        detail = (f" | {'+'.join(map(str,b[0]))}b · Rdt {b[1]:+.0f}% · {b[2]} zones · {b[3]:.0f}%"
                  if b else "")
        print(f"  {r['verdict']:32} {tk}{detail}")

    # Classement : meilleur verdict d'abord, puis meilleur rdt fiable
    rows.sort(key=lambda x: (x[0], -(x[3][1] if x[3] else -1e9)))

    lines = [f"<b>🔎 Screener de cycles</b> — {len(tickers)} valeur(s) · fenêtre {period}\n"]
    cur_rank = None
    for rank, tk, verdict, best in rows:
        if rank != cur_rank:
            cur_rank = rank
            lines.append("")  # séparation entre groupes
        if best:
            periods = "+".join(map(str, best[0]))
            lines.append(f"{verdict} <b>{tk}</b>")
            lines.append(f"   ▸ {periods}b · Rdt {best[1]:+.0f}% · {best[2]} zones · réussite {best[3]:.0f}%")
        else:
            lines.append(f"{verdict} <b>{tk}</b>")
    lines.append("\n<i>« Fiable » = ≥10 zones et ≥75% réussite. Beaucoup de zones = "
                 "cycle qui se répète vraiment (plus fiable qu'un gros rdt sur peu de zones).</i>")
    report = "\n".join(lines)

    print("\n" + "=" * 60)
    print("Classement (du plus intéressant au moins intéressant) envoyé sur Telegram.")
    _send_telegram(report)
    print("Terminé.")


if __name__ == "__main__":
    main()
