#!/usr/bin/env python3
"""Pré-remplit le journal des cycles (cycle_ledger.json) avec les cycles DÉJÀ
TERMINÉS dont la FIN est postérieure à une date de suivi (DEPUIS), pour chaque
combinaison de watchlist.yml.

À lancer une fois (workflow « Backfill journal ») pour que /historique montre
tout de suite les cycles terminés depuis que tu suis tes tickers. Ensuite
check_alerts.py continue à enregistrer les nouveaux cycles au fil des alertes.

Ré-exécutable sans risque : les doublons (même sens + même début) sont fusionnés.
Variable : DEPUIS (JJ/MM/AAAA ou AAAA-MM-JJ ; défaut 01/01/2026).
"""
import os
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
import cycle_ledger as L
from bot import _build_cycles_from_data, _state_at, _dir_kinds


def _parse(s: str):
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


SINCE = _parse(os.environ.get("DEPUIS", "")) or date(2026, 1, 1)
since_iso = SINCE.isoformat()
today_iso = date.today().isoformat()


def _to_date(x):
    return x.date() if hasattr(x, "date") else x


def main() -> None:
    with open("watchlist.yml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    led = L.load()
    total = 0
    print(f"Pré-remplissage depuis {since_iso}…\n")

    for entry in config.get("alerts", []):
        ticker    = entry["ticker"].upper()
        periods   = [int(p.strip()) for p in str(entry["cycles"]).split(",")]
        period    = entry.get("period", "5y")
        interval  = entry.get("interval", "1d")
        start     = entry.get("start")
        direction = entry.get("direction", "both")

        key = L.key_of(ticker, entry["cycles"], direction)
        L._entry(led, key)["since"] = since_iso      # fixe la date de suivi

        try:
            data = fetch_data(ticker, period=period, interval=interval, start=start)
        except Exception as exc:
            print(f"  ⚠ {ticker} {entry['cycles']}b : fetch KO ({exc})")
            continue

        prices    = get_close_prices(data)
        dates_idx = get_dates(data)
        cycles, _t, _l = _build_cycles_from_data(prices, dates_idx, periods)
        N = len(prices)

        n = 0
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
                if e <= s or e >= N - 1:
                    continue                         # zone d'1 barre, ou non terminée
                p0, p1 = float(prices[s]), float(prices[e])
                if p0 <= 0:
                    continue
                chg = (p1 / p0 - 1.0) * 100.0
                ret = chg if kind == "HAUSSIER" else -chg
                d0, d1 = _to_date(dates_idx[s]), _to_date(dates_idx[e])
                if d1 < SINCE:                        # terminé avant le suivi → ignoré
                    continue
                if L.record_finished(led, key, kind,
                                     d0.isoformat(), d1.isoformat(), ret, today_iso):
                    n += 1
        total += n
        tag = f"{ticker} {entry['cycles']}b {direction}"
        print(f"  {tag:32} : {n} cycle(s) terminé(s)")

    L.save(led)
    print(f"\nTerminé — {total} cycle(s) enregistré(s) depuis {since_iso}.")


if __name__ == "__main__":
    main()
