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

# ── Seuils de « fiabilité » (réglables via variables d'environnement) ─────────
MIN_ZONES_FIABLE = int(os.environ.get("MIN_ZONES", "10"))    # répétitions minimum du cycle
MIN_HIT_FIABLE   = float(os.environ.get("MIN_HIT", "75"))    # % de zones gagnantes minimum
SEUIL_TRES       = 150.0  # rdt d'une combo fiable ≥ 150 % → ⭐⭐
SEUIL_INTER      = 80.0   # rdt d'une combo fiable ≥ 80 %  → ⭐


MAX_PAR_TICKER = 4        # nombre max de combos affichées par entreprise


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


def _too_similar(a_periods, b_periods, tol=0.06):
    """Deux combos quasi identiques (mêmes cycles à ~6% près) → on n'en garde qu'une."""
    if len(a_periods) != len(b_periods):
        return False
    for pa, pb in zip(sorted(a_periods), sorted(b_periods)):
        if abs(pa - pb) > max(3, tol * max(pa, pb)):
            return False
    return True


def _dedup(combos):
    """Garde les combos distinctes (écarte les quasi-doublons), en gardant la 1re vue."""
    kept = []
    for c in combos:
        if not any(_too_similar(c[0], k[0]) for k in kept):
            kept.append(c)
    return kept


def screen_ticker(ticker, period, start=None):
    """Retourne dict(rank, verdict, combos=[combos intéressantes triées]) ou data KO.
    Si ``start`` est fourni (date fixe), le passé est FIGÉ → stats reproductibles."""
    data = fetch_data(ticker, period=period, interval="1d", start=start)
    prices = get_close_prices(data)
    if len(prices) < 200:
        return dict(rank=4, verdict="✗ HISTORIQUE TROP COURT", combos=[])

    combos = _best_combos(prices)
    if not combos:
        return dict(rank=4, verdict="✗ PEU CYCLIQUE", combos=[])

    # FILTRE STRICT : on ne garde QUE les combos qui respectent les seuils.
    fiables = [c for c in combos if c[2] >= MIN_ZONES_FIABLE and c[3] >= MIN_HIT_FIABLE and c[1] > 0]
    if not fiables:
        return dict(rank=4,
                    verdict=f"✗ AUCUN CYCLE (≥{MIN_ZONES_FIABLE} zones & ≥{MIN_HIT_FIABLE:.0f}% non atteint)",
                    combos=[])

    keep = _dedup(sorted(fiables, key=lambda c: -c[1]))[:MAX_PAR_TICKER]
    best_rdt = keep[0][1]
    n = len(keep)
    if best_rdt >= SEUIL_TRES:
        v = "⭐⭐ TRÈS INTÉRESSANT"; rank = 0
    elif best_rdt >= SEUIL_INTER:
        v = "⭐ INTÉRESSANT"; rank = 1
    else:
        v = "➖ MOYEN"; rank = 2
    if n > 1:
        v += f" ({n} cycles)"
    return dict(rank=rank, verdict=v, combos=keep)


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
    start = os.environ.get("SCREEN_START", "").strip() or None   # date FIXE → stats figées
    if not tickers:
        print("❌ Aucun ticker. Renseigne TICKERS (ex: \"XLE XME GDX EWZ\").")
        sys.exit(1)

    fenetre = f"début figé {start}" if start else f"fenêtre {period}"
    print(f"Screening de {len(tickers)} ticker(s) — {fenetre}…\n")
    rows = []
    for tk in tickers:
        try:
            r = screen_ticker(tk, period, start=start)
        except Exception as exc:
            print(f"  ⚠ {tk} -> erreur : {exc}")
            rows.append((5, tk, "⚠ DONNÉES INDISPONIBLES", []))
            continue
        rows.append((r["rank"], tk, r["verdict"], r["combos"]))
        print(f"  {r['verdict']:34} {tk}")
        for b in r["combos"]:
            print(f"       {'+'.join(map(str,b[0]))}b · Rdt {b[1]:+.0f}% · {b[2]} zones · {b[3]:.0f}%")

    # Classement : meilleur verdict d'abord, puis meilleur rdt de la 1re combo
    rows.sort(key=lambda x: (x[0], -(x[3][0][1] if x[3] else -1e9)))

    # TOP 5 GLOBAL : les meilleurs cycles (par rendement) toutes entreprises confondues,
    # parmi ceux qui passent le filtre (≥ MIN_ZONES zones & ≥ MIN_HIT %).
    tous = []
    for rank, tk, verdict, combos in rows:
        for b in combos:
            tous.append((b[1], tk, b[0], b[2], b[3]))   # (rdt, ticker, periods, zones, hit)
    tous.sort(key=lambda x: -x[0])
    top5 = tous[:5]

    print("\n" + "=" * 60)
    print("🏆 TOP 5 DES MEILLEURS CYCLES (toutes entreprises)")
    for i, (rdt, tk, periods, zones, hit) in enumerate(top5, 1):
        print(f"  {i}. {tk:12} {'+'.join(map(str,periods))}b · Rdt {rdt:+.0f}% · {zones} zones · {hit:.0f}%")

    lines = [f"<b>🔎 Screener de cycles</b> — {len(tickers)} valeur(s) · {fenetre}",
             f"Critère « fiable » : ≥ {MIN_ZONES_FIABLE} zones et ≥ {MIN_HIT_FIABLE:.0f}% réussite\n"]
    cur_rank = None
    for rank, tk, verdict, combos in rows:
        if rank != cur_rank:
            cur_rank = rank
            lines.append("")  # séparation entre groupes
        lines.append(f"{verdict} <b>{tk}</b>")
        for b in combos:
            periods = "+".join(map(str, b[0]))
            lines.append(f"   ▸ {periods}b · Rdt {b[1]:+.0f}% · {b[2]} zones · réussite {b[3]:.0f}%")

    if top5:
        lines.append("\n<b>🏆 TOP 5 des meilleurs cycles</b>")
        for i, (rdt, tk, periods, zones, hit) in enumerate(top5, 1):
            lines.append(f"   {i}. <b>{tk}</b> {'+'.join(map(str,periods))}b · "
                         f"Rdt {rdt:+.0f}% · {zones} zones · {hit:.0f}%")

    lines.append(f"\n<i>Plusieurs ▸ = plusieurs cycles intéressants pour la valeur. "
                 f"« Fiable » = ≥{MIN_ZONES_FIABLE} zones et ≥{MIN_HIT_FIABLE:.0f}% réussite.</i>")
    report = "\n".join(lines)

    print("\n" + "=" * 60)
    print("Classement (du plus intéressant au moins intéressant) envoyé sur Telegram.")
    _send_telegram(report)
    print("Terminé.")


if __name__ == "__main__":
    main()
