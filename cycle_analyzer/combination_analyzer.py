from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

from .cycle_detector import CycleInfo, get_bullish_mask, _detrend_log, _fit_sine, _phase_state


@dataclass
class ZoneResult:
    start: int
    end: int
    return_pct: float
    duration: int


@dataclass
class SLZoneResult:
    """Result of trailing stop-loss simulation on one bullish zone."""
    zone: ZoneResult
    sl_return_pct: float           # actual return with SL applied
    sl_hit: bool                   # True if SL was triggered before zone end
    sl_exit_bar: int               # absolute bar index where trade was exited
    sl_path: np.ndarray            # SL price level per bar (zone.start → sl_exit_bar)
    original_return_pct: float     # return without SL (= zone.return_pct)


@dataclass
class CombinationResult:
    cycles: List[CycleInfo]
    periods: List[int]
    # Bullish zones (all cycles rising simultaneously)
    zones: List[ZoneResult]
    total_return_pct: float        # simple sum
    compound_return_pct: float     # compounded (reinvestment)
    hit_rate: float
    avg_return_pct: float
    n_zones: int
    bullish_mask: np.ndarray = field(repr=False)
    # Bearish zones (all cycles falling simultaneously)
    bearish_zones: List[ZoneResult] = field(default_factory=list)
    bearish_total_return_pct: float = 0.0
    bearish_compound_return_pct: float = 0.0
    bearish_hit_rate: float = 0.0       # % of bearish zones where market fell (short profit)
    short_compound_return_pct: float = 0.0  # compounded return if shorting every bearish zone
    bearish_mask: np.ndarray = field(default_factory=lambda: np.array([], dtype=bool), repr=False)
    combo_size: int = 2

    @property
    def label(self) -> str:
        return " + ".join(str(c.period) for c in self.cycles)

    @property
    def periods_str(self) -> str:
        return ", ".join(str(p) for p in self.periods)


def _compute_zones(prices: np.ndarray, mask: np.ndarray) -> List[ZoneResult]:
    """Find contiguous True zones in mask and compute their price returns."""
    zones: List[ZoneResult] = []
    N = len(prices)
    i = 0
    while i < N:
        if mask[i]:
            start = i
            while i < N and mask[i]:
                i += 1
            end = i - 1
            if end > start:
                ret = (prices[end] - prices[start]) / prices[start] * 100
                zones.append(ZoneResult(start=start, end=end,
                                        return_pct=round(ret, 2), duration=end - start + 1))
        else:
            i += 1
    return zones


def _bull_mask_for(prices: np.ndarray, c: CycleInfo, masks: dict = None) -> np.ndarray:
    """Masque haussier d'un cycle, avec cache optionnel {period: mask} pour éviter
    de recalculer la sinusoïde du même cycle dans chaque combinaison."""
    if masks is not None:
        m = masks.get(c.period)
        if m is None:
            m = get_bullish_mask(prices, c.period)
            masks[c.period] = m
        return m
    return get_bullish_mask(prices, c.period)


def _combined_bullish_mask(prices: np.ndarray, cycles: List[CycleInfo], masks: dict = None) -> np.ndarray:
    mask = np.ones(len(prices), dtype=bool)
    for c in cycles:
        mask &= _bull_mask_for(prices, c, masks)
    return mask


def _combined_bearish_mask(prices: np.ndarray, cycles: List[CycleInfo], masks: dict = None) -> np.ndarray:
    mask = np.ones(len(prices), dtype=bool)
    for c in cycles:
        mask &= ~_bull_mask_for(prices, c, masks)
    return mask


def _short_compound_return(zones: List[ZoneResult]) -> float:
    """Compounded return when shorting every zone (gain = -price_change)."""
    if not zones:
        return 0.0
    c = 1.0
    for z in zones:
        c *= 1 + (-z.return_pct) / 100
    return round((c - 1) * 100, 2)


def compute_single_cycle_hit_rates(prices: np.ndarray, period: int) -> Tuple[float, float]:
    """Return (hit_rate, short_hit_rate) as percentages for a single cycle."""
    bullish = get_bullish_mask(prices, period)
    N = len(prices)
    bull_hits = bull_total = 0
    bear_hits = bear_total = 0
    i = 0
    while i < N:
        if bullish[i]:
            start = i
            while i < N and bullish[i]:
                i += 1
            last = i - 1
            if last > start:
                ret = (prices[last] - prices[start]) / prices[start]
                bull_total += 1
                if ret > 0:
                    bull_hits += 1
        else:
            start = i
            while i < N and not bullish[i]:
                i += 1
            last = i - 1
            if last > start:
                ret = (prices[last] - prices[start]) / prices[start]
                bear_total += 1
                if ret < 0:
                    bear_hits += 1
    hit_rate = (bull_hits / bull_total * 100) if bull_total > 0 else 0.0
    short_hit_rate = (bear_hits / bear_total * 100) if bear_total > 0 else 0.0
    return hit_rate, short_hit_rate


def _short_hit_rate(zones: List[ZoneResult]) -> float:
    """% of zones where market fell (short was profitable)."""
    if not zones:
        return 0.0
    hits = sum(1 for z in zones if z.return_pct < 0)
    return round(hits / len(zones) * 100, 1)


def _compound_return(zones: List[ZoneResult]) -> float:
    if not zones:
        return 0.0
    c = 1.0
    for z in zones:
        c *= 1 + z.return_pct / 100
    return round((c - 1) * 100, 2)


def _zone_stats(zones: List[ZoneResult]) -> Tuple[float, float, float]:
    if not zones:
        return 0.0, 0.0, 0.0
    total_return = sum(z.return_pct for z in zones)
    hits = sum(1 for z in zones if z.return_pct > 0)
    hit_rate = hits / len(zones) * 100
    avg_return = float(np.mean([z.return_pct for z in zones]))
    return round(total_return, 2), round(hit_rate, 1), round(avg_return, 2)


def _build_combo(prices: np.ndarray, combo: List[CycleInfo], masks: dict = None) -> CombinationResult:
    bull_mask = _combined_bullish_mask(prices, combo, masks)
    bear_mask = _combined_bearish_mask(prices, combo, masks)

    # Skip degenerate combos
    bull_pct = bull_mask.mean()
    if bull_pct < 0.05 or bull_pct > 0.95:
        return None

    bull_zones = _compute_zones(prices, bull_mask)
    bear_zones = _compute_zones(prices, bear_mask)

    if not bull_zones:
        return None

    total_ret, hit_rate, avg_ret = _zone_stats(bull_zones)
    bear_total, _, _ = _zone_stats(bear_zones)

    return CombinationResult(
        cycles=combo,
        periods=[c.period for c in combo],
        zones=bull_zones,
        total_return_pct=total_ret,
        compound_return_pct=_compound_return(bull_zones),
        hit_rate=hit_rate,
        avg_return_pct=avg_ret,
        n_zones=len(bull_zones),
        bullish_mask=bull_mask,
        bearish_zones=bear_zones,
        bearish_total_return_pct=bear_total,
        bearish_compound_return_pct=_compound_return(bear_zones),
        bearish_hit_rate=_short_hit_rate(bear_zones),
        short_compound_return_pct=_short_compound_return(bear_zones),
        bearish_mask=bear_mask,
        combo_size=len(combo),
    )


# ── Catégories de longueur de cycle (en barres) ───────────────────────────────
# Sert à diversifier les combinaisons affichées : sans ça, le classement par
# rendement est monopolisé par les cycles très longs, et les cycles courts/moyens
# (souvent plus exploitables) n'apparaissent jamais.
_LEN_COURT_MAX = 60      # cycles COURTS  : <= 60 barres  (~3 mois en journalier)
_LEN_MOYEN_MAX = 180     # cycles MOYENS  : 61-180 barres (~3-9 mois)
                         # cycles LONGS   : > 180 barres
_LENGTH_ORDER = ("court", "moyen", "long")


def _length_bucket(period: int) -> str:
    if period <= _LEN_COURT_MAX:
        return "court"
    if period <= _LEN_MOYEN_MAX:
        return "moyen"
    return "long"


def _combo_bucket(combo: "CombinationResult") -> str:
    """Catégorie d'une combinaison = celle de son cycle le plus long."""
    return _length_bucket(max(combo.periods))


def combo_length_label(combo: "CombinationResult") -> str:
    """Libellé lisible de la catégorie de longueur d'une combinaison."""
    return {"court": "Court", "moyen": "Moyen", "long": "Long"}[_combo_bucket(combo)]


# ── Paramètres de sélection des combinaisons affichées ────────────────────────
_N_SHOW           = 5      # nombre MAX de combinaisons proposées (moins si peu d'intéressantes)
_MIN_HIT_RATE     = 50.0   # réussite minimale (%) pour qu'une combinaison soit "intéressante"
_COURT_MAX_PERIOD = 200    # catégorie "cycles courts" : tous les cycles < 200 jours


def _weighted_zone_score(zones: List[ZoneResult], N: int, halflife: float,
                         short: bool = False) -> float:
    """Score pondéré par la RÉCENCE : une zone qui s'est terminée il y a `halflife`
    barres compte moitié moins qu'une zone récente. = (somme pondérée des rendements)
    × (taux de réussite pondéré). Sert à privilégier les cycles qui marchent RÉCEMMENT."""
    if not zones:
        return 0.0
    sret = wsum = whit = 0.0
    for z in zones:
        r = -z.return_pct if short else z.return_pct   # gain d'un short = -variation
        w = 0.5 ** ((N - 1 - z.end) / max(halflife, 1.0))
        sret += w * r
        wsum += w
        whit += w * (1.0 if r > 0 else 0.0)
    hit = (whit / wsum) if wsum > 0 else 0.0
    return sret * hit


# ── Méthode de calcul du score de qualité ─────────────────────────────────────
#   0 = rendement % PUR (formule de départ) : on classe uniquement sur le
#       rendement total, sans tenir compte du nombre de zones ni de la réussite
#   1 = bonus doux (rendement TOTAL × réussite × bonus_zones)
#   2 = note pondérée /100 (rendement, réussite, zones normalisés sur le lot)
#   3 = edge par zone × réussite × √(nb zones)  — échelle ABSOLUE, stable
_QUALITY_METHOD = 0

# Méthode 1 : bonus doux lié au nombre de zones
_ZONE_BONUS_FLOOR = 0.80    # score minimal conservé même avec très peu de zones
_ZONE_BONUS_FULL  = 20      # nb de zones à partir duquel le bonus est maximal (1.0)

# Méthode 2 : poids de chaque critère (doivent sommer à 1)
_M2_W_RET, _M2_W_HIT, _M2_W_ZONE = 0.40, 0.40, 0.20


def _m3_score(avg_ret: float, hit: float, n: int) -> float:
    """(Méthode 3) Edge par zone × régularité × confiance statistique.
      score = rendement_moyen_par_zone × (réussite/100) × √(nb_zones)
    - `avg_ret` est le rendement MOYEN d'une zone (pas la somme) : c'est l'edge
      réel par trade, il ne gonfle donc pas avec le nombre de zones.
    - √n est un bonus de confiance à rendement DÉCROISSANT : 20 zones → ×4.5,
      5 zones → ×2.2. Peu de zones n'élimine jamais une combi, ça atténue juste
      le bonus → une combi au rendement/réussite exceptionnels ressort quand même.
    - Échelle ABSOLUE (aucune normalisation sur le lot) → scores stables et
      comparables d'un run à l'autre.
    Rendement moyen <= 0 → score <= 0 (combi écartée par les sélecteurs)."""
    return avg_ret * max(hit, 0.0) / 100.0 * (max(n, 0) ** 0.5)


def _zone_bonus(n: int) -> float:
    """(Méthode 1) Facteur entre `_ZONE_BONUS_FLOOR` (peu de zones) et 1.0
    (>= `_ZONE_BONUS_FULL` zones)."""
    frac = min(max(n, 0), _ZONE_BONUS_FULL) / _ZONE_BONUS_FULL
    return _ZONE_BONUS_FLOOR + (1.0 - _ZONE_BONUS_FLOOR) * frac


def _norm(v: float, lo: float, hi: float) -> float:
    return 0.0 if hi <= lo else (v - lo) / (hi - lo)


def _assign_m2_scores(combos: List["CombinationResult"]) -> None:
    """(Méthode 2) Note chaque combinaison sur ses 3 critères NORMALISÉS sur tout le
    lot (le meilleur rendement du lot = 100, etc.), puis moyenne pondérée 40/40/20.
    Le score (long et short) est stocké sur chaque combinaison. Rendement <= 0 → -1
    (exclu). Ainsi un combo peut ressortir grâce à un rendement/réussite exceptionnels
    même avec peu de zones (les zones ne pèsent que 20%)."""
    if not combos:
        return
    for short in (False, True):
        ret_of = (lambda c: -c.bearish_total_return_pct) if short else (lambda c: c.total_return_pct)
        hit_of = (lambda c: c.bearish_hit_rate) if short else (lambda c: c.hit_rate)
        zon_of = (lambda c: len(c.bearish_zones)) if short else (lambda c: c.n_zones)
        rets = [ret_of(c) for c in combos]
        hits = [hit_of(c) for c in combos]
        zs   = [zon_of(c) for c in combos]
        rmin, rmax = min(rets), max(rets)
        hmin, hmax = min(hits), max(hits)
        zmin, zmax = min(zs), max(zs)
        attr = "_m2_short" if short else "_m2_long"
        for c in combos:
            r = ret_of(c)
            if r <= 0:
                s = -1.0
            else:
                s = (_M2_W_RET * _norm(r, rmin, rmax)
                     + _M2_W_HIT * _norm(hit_of(c), hmin, hmax)
                     + _M2_W_ZONE * _norm(zon_of(c), zmin, zmax))
            setattr(c, attr, s)


def combo_quality(combo: "CombinationResult", short: bool = False,
                  halflife: float = None, n_bars: int = None) -> float:
    """Score de qualité d'une combinaison (méthode selon `_QUALITY_METHOD`).
    Si `halflife`/`n_bars` sont fournis → pondération par la récence (mode --recent)."""
    if halflife and n_bars:
        zones = combo.bearish_zones if short else combo.zones
        return _weighted_zone_score(zones, n_bars, halflife, short=short)
    if short:
        ret = -combo.bearish_total_return_pct        # gain d'un short = -variation
        hit = combo.bearish_hit_rate
        n = len(combo.bearish_zones)
    else:
        ret = combo.total_return_pct
        hit = combo.hit_rate
        n = combo.n_zones
    if _QUALITY_METHOD == 0:
        # Rendement % PUR : ni les zones ni la réussite n'entrent dans le classement.
        return ret
    if _QUALITY_METHOD == 3:
        # rendement MOYEN par zone (edge par trade), pas la somme
        avg_ret = (ret / n) if n > 0 else 0.0
        return _m3_score(avg_ret, hit, n)
    if _QUALITY_METHOD == 2:
        s = getattr(combo, "_m2_short" if short else "_m2_long", None)
        if s is not None:
            return s
        # fallback (score M2 non pré-calculé) : approximation par la méthode 1
    return ret * max(hit, 0.0) / 100.0 * _zone_bonus(n)


def _combo_contains(big: "CombinationResult", small: "CombinationResult") -> bool:
    """True si TOUS les cycles de `small` se retrouvent (à ~18% près) dans `big`.
    Ex: le triple 198+688+330 contient la paire 688+330 → triple redondant."""
    used = list(big.periods)
    for ps in small.periods:
        match = next((u for u in used if _periods_too_close(ps, u)), None)
        if match is None:
            return False
        used.remove(match)
    return True


def _combos_near_duplicate(a: "CombinationResult", b: "CombinationResult") -> bool:
    """True si a et b (même nombre de cycles) partagent tous leurs cycles SAUF au
    plus un — donc quasi-identiques (ex: 124+86+330 et 124+86+204 ne changent que
    d'un cycle). Dans ce cas on ne garde que la meilleure des deux."""
    if len(a.periods) != len(b.periods):
        return False
    shared = 0
    used = list(b.periods)
    for pa in a.periods:
        m = next((u for u in used if _periods_too_close(pa, u)), None)
        if m is not None:
            used.remove(m)
            shared += 1
    return shared >= len(a.periods) - 1


def pick_diverse(
    combos: List["CombinationResult"],
    score,                      # r -> float : score de qualité (rendement × réussite)
    hit,                        # r -> float : % de réussite (garde-fou qualité)
    n: int = _N_SHOW,
    min_hit: float = _MIN_HIT_RATE,
    avoid: List["CombinationResult"] = None,
    cross_dedup: bool = True,
) -> List["CombinationResult"]:
    """Sélectionne jusqu'à `n` combinaisons, LES MEILLEURES D'ABORD (rendement ×
    réussite), en éliminant les combinaisons redondantes.

    Règles (la qualité prime TOUJOURS) :
      - on ne garde que les combinaisons au rendement positif ET à la réussite
        >= min_hit (sinon inintéressantes) ;
      - quasi-identiques (ne diffèrent que d'un cycle) → on garde la meilleure ;
      - `cross_dedup=True` : on écarte aussi une combinaison en relation de contenu
        avec une meilleure déjà gardée (paire ⊂ triple). À False pour les sections
        indépendantes par taille (où ce cas ne se produit pas de toute façon) ;
      - `avoid` : on n'affiche PAS une combinaison qui REPREND entièrement une
        combinaison de `avoid` (ex: un triple = paire + 1 cycle) SANS faire mieux
        qu'elle → un triple qui reprend une paire déjà proposée et est moins bon
        ne sert à rien.
    Peut renvoyer MOINS de `n` éléments s'il y a peu de combinaisons intéressantes."""
    avoid = avoid or []
    ordered = sorted(combos, key=score, reverse=True)
    selected: List["CombinationResult"] = []
    for r in ordered:
        if len(selected) >= n:
            break
        if score(r) <= 0 or hit(r) < min_hit:
            continue                                    # ni rendement ni réussite intéressants
        redundant = False
        for s in selected:
            if _combos_near_duplicate(r, s):
                redundant = True
                break
            if cross_dedup and (_combo_contains(r, s) or _combo_contains(s, r)):
                redundant = True
                break
        if redundant:
            continue
        # Reprise inutile d'une combinaison déjà proposée ailleurs (sans faire mieux)
        if any(_combo_contains(r, a) and score(a) >= score(r) for a in avoid):
            continue
        selected.append(r)
    return selected


def _select_triples(triples, score, hit, base_n, min_hit, pairs_shown, extra_cap=2):
    """Meilleurs triples par équilibre. Si un triple retenu REPREND une paire déjà
    proposée, on laisse le triple MAIS on ajoute une proposition supplémentaire
    (jusqu'à base_n + extra_cap), pour ne pas gâcher un créneau."""
    selected: List["CombinationResult"] = []
    seen: set = set()
    target = base_n
    cap = base_n + extra_cap
    for t in sorted(triples, key=score, reverse=True):
        if len(selected) >= target:
            break
        if score(t) <= 0 or hit(t) < min_hit:
            continue
        key = tuple(sorted(t.periods))
        if key in seen:
            continue
        if any(_combos_near_duplicate(t, s) for s in selected):
            continue
        selected.append(t)
        seen.add(key)
        if any(_combo_contains(t, p) for p in pairs_shown):
            target = min(target + 1, cap)          # triple qui reprend une paire → +1 proposition
    return selected


def _return_scan_pool(prices: np.ndarray, top_n: int = 14,
                      extra_short_medium: int = 12,
                      recency_halflife: float = None) -> List[CycleInfo]:
    """
    Brute-force scan: test every integer period from 10 to N//2,
    rank by single-cycle return. Returns the global best `top_n`
    (les cycles forts ne sont JAMAIS jetés, quelle que soit leur longueur),
    PLUS quelques cycles courts et moyens en plus, pour permettre la diversité
    d'affichage sans évincer les meilleurs cycles (souvent longs).
    Si `recency_halflife` est fourni, le classement privilégie les cycles qui
    performent RÉCEMMENT (mode --recent).
    """
    N = len(prices)
    max_p = N // 2
    detrended, _ = _detrend_log(prices)
    candidates: List[Tuple[float, int]] = []  # (score, period)

    for p in range(10, max_p + 1):
        mask = get_bullish_mask(prices, p)
        bull_pct = mask.mean()
        if bull_pct < 0.05 or bull_pct > 0.95:
            continue
        zones = _compute_zones(prices, mask)
        if not zones:
            continue
        if recency_halflife:
            cr = _weighted_zone_score(zones, N, recency_halflife)
        else:
            cr = _compound_return(zones)
        candidates.append((cr, p))

    candidates.sort(reverse=True)

    # 1) Les meilleurs globalement (comportement d'origine : on ne jette aucun bon cycle)
    chosen: List[Tuple[float, int]] = list(candidates[:top_n])
    chosen_p: set = set(p for _, p in chosen)

    # 2) EN PLUS : quelques cycles courts et moyens pour rendre la diversité possible
    sm_buckets: Dict[str, List[Tuple[float, int]]] = {"court": [], "moyen": []}
    for cr, p in candidates:
        b = _length_bucket(p)
        if b in sm_buckets:
            sm_buckets[b].append((cr, p))
    for b in ("court", "moyen"):
        added = 0
        for cr, p in sm_buckets[b]:
            if added >= extra_short_medium:
                break
            if p not in chosen_p:
                chosen.append((cr, p))
                chosen_p.add(p)
                added += 1

    result = []
    for cr, p in chosen:
        A, B, amp = _fit_sine(detrended, float(p))
        if amp < 1e-10:
            continue
        state, osc_val, direction = _phase_state(A, B, float(p), N - 1)
        result.append(CycleInfo(
            period=p, period_exact=float(p),
            amplitude=round(amp * prices[-1], 2), strength=0.0, stability=0.0,
            phase_state=state, current_value=osc_val, current_direction=direction,
            oscillator=np.array([]), r_squared=0.0, amplitude_log=amp,
            coeff_a=A, coeff_b=B,
        ))
    return result


def analyze_combinations(
    prices: np.ndarray,
    cycles: List[CycleInfo],
    top_n_per_size: int = 3,
    recency_halflife: float = None,
    min_hit: float = None,
    min_zones: int = None,
    min_return: float = None,
    max_period: int = None,
) -> Dict:
    """
    Returns combinations grouped by size, with separate long and short rankings:
      {2: [top N long pairs], 3: [top N long triples],
       "short_2": [top N short pairs], "short_3": [top N short triples]}
    Long  ranked by compound return on bullish zones.
    Short ranked by compound return when shorting bearish zones.
    Both rankings are independent, computed over the full valid combo pool.
    Pool = top 20 FFT cycles + top 20 return-scan cycles (deduplicated).
    """
    # FFT-detected cycles (deduplicated by integer period)
    seen_periods: set = set()
    pool = []
    for c in cycles[:30]:
        if c.period not in seen_periods:
            pool.append(c)
            seen_periods.add(c.period)
        if len(pool) >= 25:
            break

    # Supplement with brute-force return scan so strong periods not caught by FFT
    # (e.g. 86, 26 on MRNA) are always tested. On injecte GÉNÉREUSEMENT des petits
    # cycles (courts/moyens) pour qu'ils soient testés à égalité avec les longs
    # (ils sont souvent sous-représentés par la FFT).
    n_bars = len(prices)
    # Par défaut AUCUN seuil de réussite (classement par rendement pur) ; le seuil
    # ne s'applique QUE si l'utilisateur passe --reussite. Idem pour --zone.
    mh = min_hit if min_hit is not None else 0.0
    for c in _return_scan_pool(prices, recency_halflife=recency_halflife):
        if c.period not in seen_periods:
            pool.append(c)
            seen_periods.add(c.period)

    # Filtre --court : ne garder que les cycles < max_period barres. Toutes les
    # combinaisons construites ensuite n'auront donc QUE des cycles courts.
    if max_period is not None:
        pool = [c for c in pool if c.period < max_period]

    results: Dict = {2: [], 3: [], "short_2": [], "short_3": [], "court": []}

    def _qual(r):
        return combo_quality(r, halflife=recency_halflife, n_bars=n_bars)

    def _qual_short(r):
        return combo_quality(r, short=True, halflife=recency_halflife, n_bars=n_bars)

    # Cache des masques haussiers : chaque cycle du pool n'est calculé qu'UNE fois
    # (au lieu d'une fois par combinaison où il apparaît) → énorme gain de temps.
    mask_cache: dict = {c.period: get_bullish_mask(prices, c.period) for c in pool}

    # Construit toutes les combinaisons valides (paires ET triples ensemble)
    all_valid: List[CombinationResult] = []
    for size in (2, 3):
        for combo in itertools.combinations(pool, size):
            # Skip if any two cycles within the combo are too similar to each other
            periods = [c.period for c in combo]
            if any(
                _periods_too_close(pa, pb)
                for pa, pb in itertools.combinations(periods, 2)
            ):
                continue
            cr = _build_combo(prices, list(combo), mask_cache)
            if cr is not None:
                all_valid.append(cr)

    # Méthode 2 : pré-calcule la note pondérée /100 (rendement/réussite/zones
    # normalisés sur TOUT le lot). Doit être fait ici, sur l'ensemble complet,
    # AVANT tout filtrage/sélection, pour que la normalisation soit cohérente.
    if _QUALITY_METHOD == 2:
        _assign_m2_scores(all_valid)

    # Filtres durs optionnels appliqués séparément en long et en short :
    #   --zone      : nombre MINIMUM de zones (long: haussières ; short: baissières)
    #   --rendement : rendement total MINIMUM en % (long: haussier ; short: gain du short)
    def _keep_long(c):
        if min_zones and c.n_zones < min_zones:
            return False
        if min_return is not None and c.total_return_pct < min_return:
            return False
        return True

    def _keep_short(c):
        if min_zones and len(c.bearish_zones) < min_zones:
            return False
        if min_return is not None and (-c.bearish_total_return_pct) < min_return:
            return False
        return True

    if min_zones or min_return is not None:
        valid_long = [c for c in all_valid if _keep_long(c)]
        valid_short = [c for c in all_valid if _keep_short(c)]
    else:
        valid_long = valid_short = all_valid

    pairs = [c for c in valid_long if len(c.periods) == 2]
    triples = [c for c in valid_long if len(c.periods) == 3]
    short_only = [c for c in valid_long if max(c.periods) < _COURT_MAX_PERIOD]
    pairs_s = [c for c in valid_short if len(c.periods) == 2]
    triples_s = [c for c in valid_short if len(c.periods) == 3]

    _hit_l = lambda c: c.hit_rate
    _hit_s = lambda c: c.bearish_hit_rate

    # ── MODE FILTRE ────────────────────────────────────────────────────────────
    # Quand l'utilisateur restreint EXPLICITEMENT le champ (--rendement / --reussite
    # / --zone), on montre TOUTES les combinaisons qui passent, classées par
    # rendement décroissant, SANS plafond ni curation (ni déduplication des
    # quasi-doublons, ni logique de « reprise »). Un filtre ne doit jamais cacher
    # une combinaison qui remplit pourtant les conditions. Seuls les doublons
    # EXACTS (mêmes cycles) sont retirés.
    filtered_mode = (min_return is not None) or (min_hit is not None) \
        or (min_zones is not None) or (max_period is not None)
    if filtered_mode:
        # AUCUN plafond : toutes les combinaisons qui passent sont retournées.
        # (Les tableaux du rapport sont du texte → pas de problème de taille ;
        # seuls les GRAPHIQUES sont plafonnés, côté report_generator.)
        def _all_passing(seq, score, hit):
            out, seen = [], set()
            for c in sorted(seq, key=score, reverse=True):
                if score(c) <= 0 or hit(c) < mh:
                    continue
                key = tuple(sorted(c.periods))
                if key in seen:
                    continue
                seen.add(key)
                out.append(c)
            return out

        _ret_l = lambda c: c.total_return_pct
        _zon_l = lambda c: c.n_zones
        _ret_s = lambda c: -c.bearish_total_return_pct
        _zon_s = lambda c: len(c.bearish_zones)

        # Cycles UNIQUES (1 cycle) qui passent le filtre : ils doivent apparaître
        # dans la liste au même titre que les paires/triples s'ils remplissent les
        # conditions (--rendement / --reussite / --zone).
        singles_all = []
        for c in pool:
            cr = _build_combo(prices, [c], mask_cache)
            if cr is not None:
                singles_all.append(cr)
        singles_long = [c for c in singles_all if _keep_long(c)]
        singles_short = [c for c in singles_all if _keep_short(c)]

        # Au plus 5 combinaisons par catégorie : les 5 MEILLEURES en rendement.
        # (_all_passing est déjà trié par rendement décroissant, _best_variants
        # conserve cet ordre → [:_FILTER_MAX] = les 5 meilleures.)
        _FILTER_MAX = 5
        results[1] = _best_variants(_all_passing(singles_long, _qual, _hit_l), _ret_l, _hit_l, _zon_l)[:_FILTER_MAX]
        results[2] = _best_variants(_all_passing(pairs, _qual, _hit_l), _ret_l, _hit_l, _zon_l)[:_FILTER_MAX]
        results[3] = _best_variants(_all_passing(triples, _qual, _hit_l), _ret_l, _hit_l, _zon_l)[:_FILTER_MAX]
        # "court" est un simple re-découpage des paires/triples → redondant quand on
        # montre déjà TOUT ; on le vide pour éviter les doublons dans le récap.
        results["court"] = []
        results["short_1"] = _best_variants(_all_passing(singles_short, _qual_short, _hit_s), _ret_s, _hit_s, _zon_s)[:_FILTER_MAX]
        results["short_2"] = _best_variants(_all_passing(pairs_s, _qual_short, _hit_s), _ret_s, _hit_s, _zon_s)[:_FILTER_MAX]
        results["short_3"] = _best_variants(_all_passing(triples_s, _qual_short, _hit_s), _ret_s, _hit_s, _zon_s)[:_FILTER_MAX]
        # Le résumé « TOP 3 MEILLEURES COMBINAISONS » ne montre QUE des combinaisons
        # (2-3 cycles), jamais un cycle unique — results[1] est volontairement exclu.
        results["diverse"] = pick_diverse(results[2] + results[3],
                                          score=_qual, hit=_hit_l, n=3, min_hit=0.0, cross_dedup=True)
        return results

    # Classement PUR par équilibre rendement × réussite : un petit gain de rendement
    # ne compense pas une réussite faible ; un très gros rendement, oui.
    results[2] = pick_diverse(pairs, score=_qual, hit=_hit_l,
                              n=top_n_per_size, min_hit=mh, cross_dedup=False)
    results["short_2"] = pick_diverse(pairs_s, score=_qual_short, hit=_hit_s,
                                      n=top_n_per_size, min_hit=mh, cross_dedup=False)

    # Triples : on garde les deux (paire + triple qui la reprend) mais on ajoute une
    # proposition supplémentaire quand un triple reprend une paire déjà proposée.
    results[3] = _select_triples(triples, _qual, _hit_l, top_n_per_size, mh, results[2])
    results["short_3"] = _select_triples(triples_s, _qual_short, _hit_s, top_n_per_size, mh,
                                         results["short_2"])

    # Catégorie SUPPLÉMENTAIRE : combinaisons composées UNIQUEMENT de cycles courts
    # (tous les cycles < _COURT_MAX_PERIOD jours).
    results["court"] = pick_diverse(short_only, score=_qual, hit=_hit_l,
                                    n=top_n_per_size, min_hit=mh, cross_dedup=True)

    # Cycles SIMPLES (1 cycle) proposés dans le récap, même sans filtre :
    # réussite >= 80%, les top_n_per_size meilleurs par rendement.
    # Construits depuis le POOL COMPLET (FFT + scan par rendement) — comme en mode
    # filtre — pour ne jamais rater un cycle fort trouvé par le scan (ex: 178).
    # La réussite est jugée sur le combo lui-même (cr.hit_rate), car les cycles du
    # scan n'ont pas de hit_rate pré-calculé sur l'objet CycleInfo.
    _singles = []
    for c in pool:
        cr = _build_combo(prices, [c], mask_cache)
        if cr is not None and cr.total_return_pct > 0 and cr.hit_rate >= 80.0:
            _singles.append(cr)
    _singles.sort(key=lambda r: r.total_return_pct, reverse=True)
    results[1] = _best_variants(_singles, lambda c: c.total_return_pct,
                                lambda c: c.hit_rate, lambda c: c.n_zones)[:top_n_per_size]

    # Résumé du haut : les 3 meilleures COMBINAISONS (jamais un cycle simple).
    results["diverse"] = pick_diverse(results[2] + results[3] + results["court"],
                                      score=_qual, hit=_hit_l, n=3, min_hit=0.0, cross_dedup=True)

    return results


def _periods_too_close(p1: int, p2: int) -> bool:
    """True if two periods are within ~18% of each other (ex: 59 vs 65 = même cycle).
    Sert à ne pas mettre deux cycles quasi-identiques dans une même combinaison
    et à ne pas les compter comme distincts dans la diversité."""
    return abs(p1 - p2) < max(8, int(0.18 * max(p1, p2)))


def _combos_too_similar(periods_a: List[int], periods_b: List[int]) -> bool:
    """True when all sorted period pairs are within ~18% of each other."""
    if len(periods_a) != len(periods_b):
        return False
    for pa, pb in zip(sorted(periods_a), sorted(periods_b)):
        threshold = max(8, int(0.18 * max(pa, pb)))
        if abs(pa - pb) >= threshold:
            return False
    return True


def _best_variants(combos_list, ret_of, hit_of, zon_of):
    """Élimine les VARIANTES DOMINÉES parmi les combinaisons quasi-identiques
    (tous les cycles à ~18% près, ex: 801+133 / 800+133 / 799+132).

    Une combinaison est MASQUÉE uniquement si, parmi les combinaisons déjà
    GARDÉES qui lui sont similaires, il en existe une au moins aussi bonne en
    RENDEMENT, une au moins aussi bonne en RÉUSSITE et une au moins aussi
    bonne en ZONES (pas forcément la même). Autrement dit, par groupe de
    cycles proches, on ne garde que les championnes de chaque dimension.

    Ex: 801+133 (577%, 80%, 10z) gardée ; 800+133 (561%, 80%, 10z) masquée
    (dominée sur tout) ; 801+132 (559%, 90%, 10z) gardée (meilleure réussite).
    `combos_list` doit être trié par score décroissant."""
    kept = []
    for c in combos_list:
        sims = [k for k in kept if _combos_too_similar(c.periods, k.periods)]
        dominated = (
            bool(sims)
            and any(ret_of(k) >= ret_of(c) for k in sims)
            and any(hit_of(k) >= hit_of(c) for k in sims)
            and any(zon_of(k) >= zon_of(c) for k in sims)
        )
        if not dominated:
            kept.append(c)
    return kept


def get_custom_combination(prices: np.ndarray, selected_cycles: List[CycleInfo]) -> CombinationResult:
    """Build a combination result for a user-selected set of cycles."""
    cr = _build_combo(prices, selected_cycles)
    if cr is None:
        # Fallback with no filter
        bull_mask = _combined_bullish_mask(prices, selected_cycles)
        bear_mask = _combined_bearish_mask(prices, selected_cycles)
        bull_zones = _compute_zones(prices, bull_mask)
        bear_zones = _compute_zones(prices, bear_mask)
        total_ret, hit_rate, avg_ret = _zone_stats(bull_zones)
        bear_total, _, _ = _zone_stats(bear_zones)
        return CombinationResult(
            cycles=selected_cycles,
            periods=[c.period for c in selected_cycles],
            zones=bull_zones,
            total_return_pct=total_ret,
            compound_return_pct=_compound_return(bull_zones),
            hit_rate=hit_rate,
            avg_return_pct=avg_ret,
            n_zones=len(bull_zones),
            bullish_mask=bull_mask,
            bearish_zones=bear_zones,
            bearish_total_return_pct=bear_total,
            bearish_compound_return_pct=_compound_return(bear_zones),
            bearish_hit_rate=_short_hit_rate(bear_zones),
            short_compound_return_pct=_short_compound_return(bear_zones),
            bearish_mask=bear_mask,
            combo_size=len(selected_cycles),
        )
    return cr


# ── Stop-Loss simulation ───────────────────────────────────────────────────────

def _simulate_sl_zone(prices: np.ndarray, zone: ZoneResult, sl_pct: float) -> SLZoneResult:
    """
    Simulate a trailing step stop-loss on a single bullish zone.

    Mechanism:
      - Entry at zone.start price; initial SL = entry × (1 - sl_pct/100)
      - Each time price rises sl_pct% from the previous tier, SL steps up by sl_pct%
        → tier 0: SL = entry × (1 - sl_pct%)
        → tier 1 (gain ≥ sl_pct%): SL = entry (break-even)
        → tier n (gain ≥ n × sl_pct%): SL = entry × (1 + (n-1) × sl_pct%)
      - If price closes at or below SL: trade exits at SL price
      - Otherwise trade exits at zone end price
    """
    zone_prices = prices[zone.start: zone.end + 1]
    n = len(zone_prices)
    if n < 2:
        path = zone_prices[:1].copy() if n else np.array([])
        return SLZoneResult(zone=zone, sl_return_pct=0.0, sl_hit=False,
                            sl_exit_bar=zone.end, sl_path=path,
                            original_return_pct=zone.return_pct)

    entry = zone_prices[0]
    sl_frac = sl_pct / 100.0
    sl = entry * (1.0 - sl_frac)
    max_price = entry
    tier = 0

    sl_path: List[float] = [sl]
    sl_hit = False
    exit_bar = zone.end
    exit_ret = (zone_prices[-1] - entry) / entry * 100.0

    for i in range(1, n):
        price = float(zone_prices[i])

        if price <= sl:
            sl_hit = True
            exit_bar = zone.start + i
            exit_ret = (sl - entry) / entry * 100.0
            sl_path.append(sl)
            break

        if price > max_price:
            max_price = price
            new_tier = int((max_price - entry) / entry / sl_frac)
            if new_tier > tier:
                tier = new_tier
                sl = entry * (1.0 + (tier - 1) * sl_frac)

        sl_path.append(sl)

    return SLZoneResult(
        zone=zone,
        sl_return_pct=round(exit_ret, 2),
        sl_hit=sl_hit,
        sl_exit_bar=exit_bar,
        sl_path=np.array(sl_path),
        original_return_pct=zone.return_pct,
    )


def simulate_sl_zones(prices: np.ndarray, zones: List[ZoneResult], sl_pct: float) -> List[SLZoneResult]:
    """Simulate trailing SL on every bullish zone of a combination."""
    return [_simulate_sl_zone(prices, zone, sl_pct) for zone in zones]


def _simulate_sl_zone_fixed(prices: np.ndarray, zone: ZoneResult, sl_pct: float) -> SLZoneResult:
    """
    Fixed stop-loss: SL is set once at entry × (1 - sl_pct/100) and NEVER moves,
    regardless of how much the price rises.
    """
    zone_prices = prices[zone.start: zone.end + 1]
    n = len(zone_prices)
    if n < 2:
        path = zone_prices[:1].copy() if n else np.array([])
        return SLZoneResult(zone=zone, sl_return_pct=0.0, sl_hit=False,
                            sl_exit_bar=zone.end, sl_path=path,
                            original_return_pct=zone.return_pct)

    entry = zone_prices[0]
    sl = entry * (1.0 - sl_pct / 100.0)

    sl_hit = False
    exit_bar = zone.end
    exit_ret = (zone_prices[-1] - entry) / entry * 100.0

    for i in range(1, n):
        price = float(zone_prices[i])
        if price <= sl:
            sl_hit = True
            exit_bar = zone.start + i
            exit_ret = (sl - entry) / entry * 100.0
            break

    sl_path = np.full(min(exit_bar - zone.start + 1, n), sl)

    return SLZoneResult(
        zone=zone,
        sl_return_pct=round(exit_ret, 2),
        sl_hit=sl_hit,
        sl_exit_bar=exit_bar,
        sl_path=sl_path,
        original_return_pct=zone.return_pct,
    )


def simulate_sl_zones_fixed(prices: np.ndarray, zones: List[ZoneResult], sl_pct: float) -> List[SLZoneResult]:
    """Simulate fixed SL on every bullish zone of a combination."""
    return [_simulate_sl_zone_fixed(prices, zone, sl_pct) for zone in zones]
