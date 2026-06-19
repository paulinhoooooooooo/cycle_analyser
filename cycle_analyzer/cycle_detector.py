from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from scipy.signal import find_peaks


@dataclass
class CycleInfo:
    period: int
    amplitude: float        # in price units
    strength: float         # SNR-like (amplitude / noise rms)
    stability: float        # 0-1, rolling window consistency
    phase_state: str        # 'bullish', 'bearish', 'peak', 'trough'
    current_value: float    # current oscillator value (log-price units)
    current_direction: float  # derivative sign (>0 = rising)
    oscillator: np.ndarray  # oscillator series in price units (centered on price)
    r_squared: float
    amplitude_log: float    # amplitude in log-price units (for internal use)
    coeff_a: float          # cos component
    coeff_b: float          # sin component
    rank: int = 0


def _detrend_log(prices: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Detrend log-prices using linear regression. Returns (detrended, trend)."""
    N = len(prices)
    log_p = np.log(prices)
    t = np.arange(N, dtype=float)
    poly = np.polyfit(t, log_p, 1)
    trend = np.polyval(poly, t)
    return log_p - trend, trend


def _fit_sine(detrended: np.ndarray, period: float) -> Tuple[float, float, float]:
    """Fit A*cos(2π*t/T) + B*sin(2π*t/T) to detrended via least squares."""
    N = len(detrended)
    t = np.arange(N, dtype=float)
    cos_c = np.cos(2 * np.pi * t / period)
    sin_c = np.sin(2 * np.pi * t / period)
    X = np.column_stack([cos_c, sin_c, np.ones(N)])
    coeffs, _, _, _ = np.linalg.lstsq(X, detrended, rcond=None)
    A, B, _ = coeffs
    amplitude = np.sqrt(A**2 + B**2)
    return A, B, amplitude


def _compute_r2(detrended: np.ndarray, period: float, A: float, B: float) -> float:
    N = len(detrended)
    t = np.arange(N, dtype=float)
    fitted = A * np.cos(2 * np.pi * t / period) + B * np.sin(2 * np.pi * t / period)
    ss_res = np.sum((detrended - fitted) ** 2)
    ss_tot = np.sum((detrended - np.mean(detrended)) ** 2)
    if ss_tot == 0:
        return 0.0
    return float(np.clip(1 - ss_res / ss_tot, 0, 1))


def _compute_stability(detrended: np.ndarray, period: int) -> float:
    """
    Rolling window stability: fraction of windows where the cycle is detectable.
    A cycle is detectable if its power is above the median power in that window.
    """
    N = len(detrended)
    window_size = max(int(period * 4), N // 4, 40)
    if window_size >= N:
        window_size = N // 2
    if window_size < 20:
        return 0.5

    step = max(1, (N - window_size) // 6)
    detections = 0
    total = 0

    target_freq = 1.0 / period

    for start in range(0, N - window_size + 1, step):
        seg = detrended[start: start + window_size]
        win = np.hanning(len(seg))
        fft = np.fft.rfft(seg * win)
        freqs = np.fft.rfftfreq(len(seg))
        power = np.abs(fft[1:]) ** 2
        freqs = freqs[1:]

        if len(freqs) == 0:
            continue

        closest = np.argmin(np.abs(freqs - target_freq))
        p_at_cycle = power[closest]
        p_median = np.median(power)

        if p_median > 0 and p_at_cycle > 1.5 * p_median:
            detections += 1
        total += 1

    return detections / total if total > 0 else 0.5


def _phase_state(A: float, B: float, period: float, t_last: int) -> Tuple[str, float, float]:
    """Return phase state string, oscillator value and direction at t_last."""
    osc = A * np.cos(2 * np.pi * t_last / period) + B * np.sin(2 * np.pi * t_last / period)
    # Derivative: d/dt[A*cos + B*sin] = (-A*sin + B*cos) * 2π/T
    direction = (
        (-A * np.sin(2 * np.pi * t_last / period) + B * np.cos(2 * np.pi * t_last / period))
        * (2 * np.pi / period)
    )
    amp = np.sqrt(A**2 + B**2)
    max_direction = amp * (2 * np.pi / period)
    turning_threshold = 0.25 * max_direction if max_direction > 0 else 0

    if abs(direction) <= turning_threshold:
        state = "peak" if osc > 0 else "trough"
    elif direction > 0:
        state = "bullish"
    else:
        state = "bearish"

    return state, float(osc), float(direction)


def detect_cycles(
    prices: np.ndarray,
    min_period: int = 10,
    max_period: Optional[int] = None,
    n_cycles: int = 25,
) -> List[CycleInfo]:
    """
    Detect dominant cycles using FFT on detrended log-prices.
    Returns cycles sorted by stability (descending).
    """
    N = len(prices)
    if max_period is None:
        max_period = N // 2

    max_period = min(max_period, N // 2)

    detrended, trend = _detrend_log(prices)

    # Windowed FFT for robust peak detection
    win = np.hanning(N)
    fft = np.fft.rfft(detrended * win)
    freqs = np.fft.rfftfreq(N)
    power = np.abs(fft[1:]) ** 2
    freqs_pos = freqs[1:]

    # Convert to periods and filter
    with np.errstate(divide="ignore", invalid="ignore"):
        raw_periods = np.where(freqs_pos > 0, 1.0 / freqs_pos, 0)

    valid = (raw_periods >= min_period) & (raw_periods <= max_period)
    if not valid.any():
        return []

    v_periods = raw_periods[valid]
    v_power = power[valid]
    v_freqs = freqs_pos[valid]

    # Find peaks with minimum prominence
    peaks, _ = find_peaks(
        v_power,
        distance=2,
        prominence=np.percentile(v_power, 40),
    )

    if len(peaks) == 0:
        peaks = np.argsort(v_power)[::-1][: n_cycles * 3]

    sorted_peaks = peaks[np.argsort(v_power[peaks])[::-1]]

    cycles: List[CycleInfo] = []
    seen_periods: List[float] = []

    for idx in sorted_peaks:
        T_raw = v_periods[idx]

        # Refine period via parabolic interpolation in log-power space
        if 0 < idx < len(v_power) - 1:
            lp = np.log(v_power[idx - 1] + 1e-30)
            lc = np.log(v_power[idx] + 1e-30)
            lr = np.log(v_power[idx + 1] + 1e-30)
            denom = lp - 2 * lc + lr
            if denom < 0:
                k_frac = v_freqs[idx] + v_freqs[1] * (lp - lr) / (2 * denom) if v_freqs[1] > 0 else v_freqs[idx]
                if k_frac > 0:
                    T_raw = 1.0 / k_frac

        T_raw = float(np.clip(T_raw, min_period, max_period))

        # Skip harmonically close periods
        if any(abs(T_raw - sp) / sp < 0.08 for sp in seen_periods):
            continue

        T_int = max(min_period, round(T_raw))

        try:
            A, B, amp_log = _fit_sine(detrended, T_raw)
        except Exception:
            continue

        if amp_log < 1e-10:
            continue

        r2 = _compute_r2(detrended, T_raw, A, B)

        # Residuals noise
        t_arr = np.arange(N, dtype=float)
        fitted = A * np.cos(2 * np.pi * t_arr / T_raw) + B * np.sin(2 * np.pi * t_arr / T_raw)
        residuals = detrended - fitted
        noise_rms = np.sqrt(np.mean(residuals**2))
        strength = float(amp_log / noise_rms) if noise_rms > 1e-12 else 0.0

        stability = _compute_stability(detrended, T_int)

        state, osc_val, direction = _phase_state(A, B, T_raw, N - 1)

        # Oscillator in price-space (centered on actual prices)
        price_center = np.exp(trend)
        amp_price = float(amp_log * prices[-1])

        oscillator_price = price_center * np.exp(fitted) / np.exp(fitted).mean() * np.exp(fitted).mean()
        oscillator_price = price_center + price_center * fitted

        seen_periods.append(T_raw)

        cycles.append(
            CycleInfo(
                period=T_int,
                amplitude=round(amp_price, 2),
                strength=round(strength, 2),
                stability=round(stability, 2),
                phase_state=state,
                current_value=osc_val,
                current_direction=direction,
                oscillator=oscillator_price,
                r_squared=round(r2, 3),
                amplitude_log=float(amp_log),
                coeff_a=float(A),
                coeff_b=float(B),
            )
        )

        if len(cycles) >= n_cycles:
            break

    cycles.sort(key=lambda c: c.stability, reverse=True)
    for i, c in enumerate(cycles):
        c.rank = i + 1

    return cycles


def get_oscillator_series(prices: np.ndarray, period: int) -> np.ndarray:
    """Return the oscillator time series (normalized, centered on zero) for a period."""
    N = len(prices)
    detrended, _ = _detrend_log(prices)
    A, B, _ = _fit_sine(detrended, float(period))
    t = np.arange(N, dtype=float)
    return A * np.cos(2 * np.pi * t / period) + B * np.sin(2 * np.pi * t / period)


def get_bullish_mask(prices: np.ndarray, period: int) -> np.ndarray:
    """Boolean mask: True where cycle is in ascending (bullish) phase."""
    N = len(prices)
    detrended, _ = _detrend_log(prices)
    A, B, _ = _fit_sine(detrended, float(period))
    t = np.arange(N, dtype=float)
    # Direction = derivative of oscillator
    direction = (
        -A * np.sin(2 * np.pi * t / period) + B * np.cos(2 * np.pi * t / period)
    ) * (2 * np.pi / period)
    return direction > 0
