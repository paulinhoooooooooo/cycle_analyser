#!/usr/bin/env python3
"""PRÉVISUALISATION du calage des cycles — ne modifie PAS le logiciel.

Génère un graphique comparatif à 3 volets pour UN cycle asymétrique :
  1. ACTUEL              : le cycle démarre au jour J (date de départ) ;
  2. ROGNAGE DU DÉBUT    : rien avant le 1er vrai début de cycle haussier ;
  3. ROGNAGE + CALAGE    : en plus, chaque frontière est recalée sur le vrai
                           plus-bas / plus-haut du prix (régimes plus nets).

Sert uniquement à COMPARER visuellement les options avant de choisir.
Env : TICKER, START (JJ/MM/AAAA ou AAAA-MM-JJ), PERIOD (période du cycle).
Tourne sur GitHub Actions (accès Yahoo + matplotlib).
"""
import os
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

sys.path.insert(0, str(Path(__file__).parent))

from cycle_analyzer.data_fetcher import fetch_data, get_close_prices, get_dates
from cycle_analyzer.cycle_detector import detect_cycles, detect_asym_cycle, build_asym_pool

GREEN = "#238636"
RED = "#da3633"
BG = "#0d1117"
FG = "#c9d1d9"


def _asym_mask(N, P, U, phi):
    return ((np.arange(N) - phi) % P) < U


def _runs(mask):
    """Liste des segments contigus True : [(start, end_inclus), ...]."""
    out = []
    N = len(mask)
    i = 0
    while i < N:
        if mask[i]:
            s = i
            while i < N and mask[i]:
                i += 1
            out.append((s, i - 1))
        else:
            i += 1
    return out


def variant_actuel(mask):
    """Masque haussier tel quel + zone active dès l'indice 0."""
    return mask.copy(), 0


def variant_trim(mask):
    """Rogne le début : zone active seulement à partir du 1er front montant
    (1er passage baissier→haussier). Avant : rien n'est affiché."""
    m = mask.astype(bool)
    rising = np.where((~m[:-1]) & (m[1:]))[0]
    active = int(rising[0] + 1) if len(rising) else 0
    out = m.copy()
    out[:active] = False
    return out, active


def _troughs(prices, min_sep):
    """Indices des vrais plus-bas locaux (creux), espacés d'au moins `min_sep`
    barres. Sert de points d'ancrage candidats pour démarrer un cycle."""
    from scipy.signal import find_peaks
    idx, _ = find_peaks(-np.asarray(prices, float), distance=max(3, int(min_sep)))
    cand = list(idx)
    # On ajoute aussi le tout premier creux global de la fenêtre initiale.
    head = int(np.argmin(prices[:max(2, min_sep)])) if len(prices) else 0
    if head not in cand:
        cand = [head] + cand
    return sorted(set(cand))


def detect_anchored(prices, P, u_frac_lo=0.20, u_frac_hi=0.85):
    """CYCLE RÉGULIER ANCRÉ. Période FIXE P (=U+D). On cherche conjointement :
      - le découpage U (hausse) / D (baisse), et
      - l'ANCRAGE `a` = un vrai plus-bas d'où on projette le cycle vers l'avant,
    qui MAXIMISE le rendement haussier capturé sur la zone active [a, fin].
    Rien n'est compté avant `a`. Le cycle reste régulier (U/D fixes, période P)
    donc prévisible : prochain début = dernier début + P.
    Retourne (mask, active_start, U, D, score, hit, n_zones) ou None."""
    N = len(prices)
    anchors = _troughs(prices, min_sep=max(5, P // 4))
    u_lo, u_hi = int(P * u_frac_lo), int(P * u_frac_hi)
    step = max(1, P // 60)
    best = None
    for U in range(u_lo, u_hi + 1, step):
        D = P - U
        for a in anchors:
            mask = np.zeros(N, dtype=bool)
            k = 0
            while a + k * P < N:
                s = a + k * P
                mask[s:min(N, s + U)] = True
                k += 1
            runs = [(s, e) for s, e in _runs(mask) if s >= a and e > s]
            full = [(s, e) for s, e in runs if (e - s + 1) >= U - 1]
            if len(full) < 2:            # il faut au moins 2 répétitions complètes
                continue
            score = sum(_pct(prices, s, e) for s, e in runs)
            hits = sum(1 for s, e in runs if prices[e] > prices[s])
            hit = 100.0 * hits / len(runs)
            val = score * (hit / 100.0)   # rendement pondéré par la réussite
            if best is None or val > best[0]:
                best = (val, mask, a, U, D, score, hit, len(runs))
    if best is None:
        return None
    _, mask, a, U, D, score, hit, nz = best
    return mask, a, U, D, score, hit, nz


def _pct(prices, s, e):
    return (prices[e] - prices[s]) / prices[s] * 100.0


def _draw(ax, dates, prices, mask, active, title):
    ax.set_facecolor(BG)
    ax.plot(dates, prices, color="#58a6ff", lw=0.9)
    # Zone grisée « inactive » avant le 1er cycle (rien n'y est calculé).
    if active > 0:
        ax.axvspan(dates[0], dates[active], color="#8b949e", alpha=0.10)
        ax.axvline(dates[active], color="#8b949e", ls=":", lw=0.8)
    bull = mask.copy()
    bull[:active] = False
    bear = (~mask)
    bear[:active] = False
    for s, e in _runs(bull):
        ax.axvspan(dates[s], dates[e], color=GREEN, alpha=0.16)
        ax.text(dates[(s + e) // 2], prices.max() * 0.97, f"↑{_pct(prices, s, e):+.0f}%",
                color=GREEN, fontsize=6, ha="center", va="top")
    for s, e in _runs(bear):
        ax.axvspan(dates[s], dates[e], color=RED, alpha=0.14)
    n_bull = len(_runs(bull))
    ax.set_title(title + f"   ({n_bull} zones haussières affichées)",
                 color=FG, fontsize=9, loc="left")
    ax.tick_params(colors=FG, labelsize=7)
    for sp in ax.spines.values():
        sp.set_color("#30363d")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def main():
    ticker = os.environ.get("TICKER", "BTC-USD").upper()
    start = os.environ.get("START") or None
    period_env = os.environ.get("PERIOD", "").strip()

    data = fetch_data(ticker, period="15y", interval="1d", start=start)
    prices = get_close_prices(data)
    dates = get_dates(data)
    N = len(prices)
    print(f"{ticker} | {N} barres | start {start}")

    # Période : imposée (PERIOD) sinon meilleur cycle asym auto-détecté.
    if period_env:
        period = int(period_env)
        r = detect_asym_cycle(prices, period)
        if r is None:
            print("Pas de cycle asym exploitable pour cette période."); sys.exit(1)
        U, D, phi, mask, _ = r
    else:
        cyc = detect_cycles(prices, min_period=15, max_period=N // 2)
        pool = build_asym_pool(prices, [c.period for c in cyc], max_add=14)
        if not pool:
            print("Aucun cycle asym trouvé."); sys.exit(1)
        # Meilleur par rendement haussier capturé (somme des zones).
        best = None
        for ci in pool:
            m = ci.bull_mask
            tot = sum(_pct(prices, s, e) for s, e in _runs(m))
            if best is None or tot > best[0]:
                best = (tot, ci)
        ci = best[1]
        U, D, phi = ci.asym
        period = ci.period
        mask = ci.bull_mask
    print(f"Cycle {period}b  ↑{U}/↓{D}  phi={phi}")

    # NOUVEAU : cycle RÉGULIER ANCRÉ (période fixe, ancré sur un vrai creux,
    # tronqué avant sa 1re répétition qui marche, U/D ré-optimisés).
    anc = detect_anchored(prices, period)
    if anc is None:
        print("Pas d'ancrage régulier exploitable (moins de 2 répétitions)."); sys.exit(1)
    a_mask, a_active, aU, aD, a_score, a_hit, a_nz = anc
    a_date = dates[a_active].strftime("%d/%m/%Y")
    print(f"ANCRÉ : début {a_date} · ↑{aU}/↓{aD} (période {aU + aD}b) · "
          f"rdt {a_score:+.0f}% · {a_nz} zones · réussite {a_hit:.0f}%")

    variants = [
        (f"1. ACTUEL — cycle {period}b ↑{U}/↓{D}, démarre au jour J",
         *variant_actuel(mask)),
        (f"2. CYCLE RÉGULIER ANCRÉ — ↑{aU}/↓{aD} (période {aU + aD}b) fixe, "
         f"débute le {a_date} (rien avant)", a_mask, a_active),
    ]

    fig, axes = plt.subplots(2, 1, figsize=(16, 8.2), sharex=True)
    fig.patch.set_facecolor(BG)
    for ax, (title, m, active) in zip(axes, variants):
        _draw(ax, dates, prices, m, active, title)
    fig.suptitle(f"{ticker} — cycle régulier ancré vs démarrage au jour J",
                 color="#fff", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    outdir = Path("graphs")
    outdir.mkdir(exist_ok=True)
    out = outdir / f"{ticker}_align_compare.png"
    fig.savefig(out, dpi=130, bbox_inches="tight", facecolor=BG)
    print(f"Graphique comparatif sauvegardé : {out.resolve()}")


if __name__ == "__main__":
    main()
