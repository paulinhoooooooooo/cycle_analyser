#!/usr/bin/env python3
"""DIAGNOSTIC RÉCAP : reproduit EXACTEMENT le pipeline du rapport (mêmes
paramètres que cycle_analyser.py) et imprime les lignes du RÉCAPITULATIF telles
qu'elles apparaîtront dans le HTML — pour vérifier qu'un cycle donné (ex. 930 j)
est bien présent, sans avoir à ouvrir le rapport.

Env : TICKER (déf URI), START (JJ/MM/AAAA, vide=période), PERIOD (déf 3y),
      BILATERAL (oui/non), REUSSITE (%), COURT (jours).
"""
import os, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cycle_analyzer.data_fetcher import fetch_data, get_close_prices
from cycle_analyzer.cycle_detector import detect_cycles
from cycle_analyzer.combination_analyzer import analyze_combinations
from cycle_analyzer.report_generator import generate_report

ticker = os.environ.get("TICKER", "URI").upper()
start = os.environ.get("START") or None
period = os.environ.get("PERIOD", "3y").strip() or "3y"
bilat = os.environ.get("BILATERAL", "non").strip().lower() == "oui"
reussite = os.environ.get("REUSSITE", "").strip()
court = os.environ.get("COURT", "").strip()
min_hit = float(reussite) if reussite else None
max_period = int(court) if court else None

data = fetch_data(ticker, period=period, interval="1d", start=start)
prices = get_close_prices(data)
dates = data.index
cycles = detect_cycles(prices, min_period=15, max_period=len(prices) // 2)

note = "--asym" + (" --bilateral" if bilat else "")
if reussite:
    note += f" --reussite {reussite}"
if court:
    note += f" --court {court}"

combos = analyze_combinations(
    prices, cycles, top_n_per_size=12, asym=True, both_sides=bilat,
    min_hit=min_hit, max_period=max_period,
)
html = generate_report(ticker, {}, prices, dates, cycles, combos,
                       period, "1d", options_note=note)

print(f"{ticker} | {len(prices)} barres | start={start} period={period} | "
      f"options: {note}\n")

# Extrait les lignes du récap : label du cycle + rendement long + réussite long.
row_re = re.compile(
    r'⠿</span>(.*?)</td>\s*'
    r'<td[^>]*>([+\-][\d.]+)%</td>\s*'      # long
    r'<td[^>]*>([+\-][\d.]+)%</td>\s*'      # short
    r'<td[^>]*>(\d+)%</td>\s*'              # réussite long
    r'<td[^>]*>(\d+)%</td>',               # réussite short
    re.S)
rows = row_re.findall(html)
print(f"RÉCAPITULATIF — {len(rows)} lignes (dans l'ordre affiché) :")
for lab, lret, sret, lhit, shit in rows:
    lab = re.sub(r"<[^>]+>", "", lab).strip()
    print(f"  {lab:26} Long {lret:>8}%  ({lhit}%)   Short {sret:>7}%  ({shit}%)")

has930 = any("930" in re.sub(r"<[^>]+>", "", r[0]) for r in rows)
print(f"\n=> un cycle « 930 » est-il présent dans le récap ? {'OUI' if has930 else 'NON'}")

# Détail des CYCLES SIMPLES retenus, avec leur ANCRAGE (barre + date) → pour voir
# les variantes d'une même période ancrées à des DÉBUTS différents.
print("\nCYCLES SIMPLES retenus (results[1]) — période, découpage, ANCRAGE :")
for cr in combos.get(1, []):
    cy = cr.cycles[0]
    a = getattr(cy, "asym", None)
    if a:
        U, D, anchor = a
        anchor = int(anchor)
        d = dates[anchor].strftime("%d/%m/%Y") if 0 <= anchor < len(dates) else "?"
        info = f"↑{U}/↓{D} ancre=barre {anchor} ({d})"
    else:
        info = "symétrique"
    print(f"  {cy.period:5} b  {info:38}  Long {cr.total_return_pct:+7.0f}% "
          f"({cr.hit_rate:.0f}%)  Short {-cr.bearish_total_return_pct:+6.0f}% "
          f"({cr.bearish_hit_rate:.0f}%)")
