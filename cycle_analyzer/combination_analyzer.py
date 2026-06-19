from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import List, Tuple

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
    zones: List[ZoneResult]
    total_return_pct: float
    hit_rate: float
    avg_return_pct: float
    n_zones: int
    bullish_mask: np.ndarray = field(repr=False)

    @property
    def label(self) -> str:
        return " + ".join(str(c.period) for c in self.cycles)

    @property
    def periods_str(self) -> str:
        return ", ".join(str(p) for p in self.periods)


def _compute_zones(prices: np.ndarray, mask: np.ndarray) -> List[ZoneResult]:
    """Find contiguous bullish zones and their returns."""
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
                zones.append(ZoneResult(start=start, end=end, return_pct=round(ret, 2), duration=end - start + 1))
        else:
            i += 1
    return zones


def _combined_mask(prices: np.ndarray, cycles: List[CycleInfo]) -> np.ndarray:
    mask = np.ones(len(prices), dtype=bool)
    for c in cycles:
        mask &= get_bullish_mask(prices, c.period)
    return mask


def _zone_stats(prices: np.ndarray, zones: List[ZoneResult]) -> Tuple[float, float, float]:
    if not zones:
        return 0.0, 0.0, 0.0
    compound = 1.0
    hits = 0
    for z in zones:
        r = z.return_pct / 100
        compound *= 1 + r
        if r > 0:
            hits += 1
    total_return = (compound - 1) * 100
    hit_rate = hits / len(zones) * 100
    avg_return = float(np.mean([z.return_pct for z in zones]))
    return round(total_return, 2), round(hit_rate, 1), round(avg_return, 2)


def analyze_combinations(
    prices: np.ndarray,
    cycles: List[CycleInfo],
    max_cycles_in_combo: int = 4,
    top_n: int = 10,
) -> List[CombinationResult]:
    """
    Evaluate all combinations of 2..max_cycles_in_combo from the provided cycles.
    Returns the top_n combinations ranked by total compounded return.
    """
    results: List[CombinationResult] = []
    pool = cycles[:12]  # limit pool for speed

    for size in range(2, min(max_cycles_in_combo + 1, len(pool) + 1)):
        for combo in itertools.combinations(pool, size):
            combo = list(combo)
            mask = _combined_mask(prices, combo)

            # Skip if too few bullish bars or too many (degenerate)
            bullish_pct = mask.mean()
            if bullish_pct < 0.05 or bullish_pct > 0.95:
                continue

            zones = _compute_zones(prices, mask)
            if not zones:
                continue

            total_ret, hit_rate, avg_ret = _zone_stats(prices, zones)

            results.append(
                CombinationResult(
                    cycles=combo,
                    periods=[c.period for c in combo],
                    zones=zones,
                    total_return_pct=total_ret,
                    hit_rate=hit_rate,
                    avg_return_pct=avg_ret,
                    n_zones=len(zones),
                    bullish_mask=mask,
                )
            )

    results.sort(key=lambda r: r.total_return_pct, reverse=True)
    return results[:top_n]


def get_custom_combination(prices: np.ndarray, selected_cycles: List[CycleInfo]) -> CombinationResult:
    """Build a combination result for a user-selected set of cycles."""
    mask = _combined_mask(prices, selected_cycles)
    zones = _compute_zones(prices, mask)
    total_ret, hit_rate, avg_ret = _zone_stats(prices, zones)
    return CombinationResult(
        cycles=selected_cycles,
        periods=[c.period for c in selected_cycles],
        zones=zones,
        total_return_pct=total_ret,
        hit_rate=hit_rate,
        avg_return_pct=avg_ret,
        n_zones=len(zones),
        bullish_mask=mask,
    )
