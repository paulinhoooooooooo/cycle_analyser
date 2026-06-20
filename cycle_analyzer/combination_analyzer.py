from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

from .cycle_detector import CycleInfo, get_bullish_mask


@dataclass
class ZoneResult:
    start: int
    end: int
    return_pct: float
    duration: int


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


def _combined_bullish_mask(prices: np.ndarray, cycles: List[CycleInfo]) -> np.ndarray:
    mask = np.ones(len(prices), dtype=bool)
    for c in cycles:
        mask &= get_bullish_mask(prices, c.period)
    return mask


def _combined_bearish_mask(prices: np.ndarray, cycles: List[CycleInfo]) -> np.ndarray:
    mask = np.ones(len(prices), dtype=bool)
    for c in cycles:
        mask &= ~get_bullish_mask(prices, c.period)
    return mask


def _short_compound_return(zones: List[ZoneResult]) -> float:
    """Compounded return when shorting every zone (gain = -price_change)."""
    if not zones:
        return 0.0
    c = 1.0
    for z in zones:
        c *= 1 + (-z.return_pct) / 100
    return round((c - 1) * 100, 2)


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


def _build_combo(prices: np.ndarray, combo: List[CycleInfo]) -> CombinationResult:
    bull_mask = _combined_bullish_mask(prices, combo)
    bear_mask = _combined_bearish_mask(prices, combo)

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


def analyze_combinations(
    prices: np.ndarray,
    cycles: List[CycleInfo],
    top_n_per_size: int = 3,
) -> Dict[int, List[CombinationResult]]:
    """
    Returns the top combinations grouped by size:
      {2: [top3 pairs], 3: [top3 triples]}
    Both ranked by total compounded return on bullish zones.
    """
    # Deduplicate pool by integer period (two cycles rounding to the same period
    # can appear when FFT bins are close — keep the one with higher stability)
    seen_periods: set = set()
    pool = []
    for c in cycles[:15]:
        if c.period not in seen_periods:
            pool.append(c)
            seen_periods.add(c.period)
        if len(pool) >= 12:
            break

    results: Dict[int, List[CombinationResult]] = {2: [], 3: []}

    for size in (2, 3):
        size_results = []
        for combo in itertools.combinations(pool, size):
            cr = _build_combo(prices, list(combo))
            if cr is not None:
                size_results.append(cr)
        size_results.sort(key=lambda r: r.total_return_pct, reverse=True)
        results[size] = size_results[:top_n_per_size]

    return results


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
