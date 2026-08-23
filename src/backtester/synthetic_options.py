"""
Synthetic Options Pricing & Delta Strike Solver Module using Black-Scholes-Merton.

Enables historical options trade simulation off underlying equity OHLCV data
without requiring expensive historical tick option datasets.
Uses pure analytical Black-Scholes implementation with Python standard library math.
"""

import math
import numpy as np

_SQRT2 = math.sqrt(2.0)


def _std_norm_cdf(x: float) -> float:
    """
    Cumulative distribution function for standard normal distribution N(x).
    Uses standard library math.erf for high speed and exact precision.
    """
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def calculate_option_price(
    flag: str,
    S: float,
    K: float,
    days_to_expiry: float,
    r: float = 0.065,
    sigma: float = 0.20,
) -> float:
    """
    Calculates analytical Black-Scholes option price, handling expiration safely.

    Args:
        flag: Option flag ('c' for Call, 'p' for Put).
        S: Current underlying asset spot price.
        K: Strike price of the option contract.
        days_to_expiry: Remaining time to expiration in days.
        r: Annualized risk-free interest rate (default 0.065 = RBI repo rate proxy).
        sigma: Implied volatility as a decimal (default 0.20 = 20% IV).

    Returns:
        Theoretical Black-Scholes option contract price / premium.
    """
    if S is None or K is None or S <= 0 or K <= 0:
        return 0.0

    t = days_to_expiry / 365.0
    flag_lower = flag.lower()
    is_call = flag_lower.startswith("c")

    if t <= 0.001:  # Expired or expiring today (intrinsic value)
        return float(max(S - K, 0.0) if is_call else max(K - S, 0.0))

    safe_sigma = max(sigma, 0.01)
    try:
        sqrt_t = math.sqrt(t)
        d1 = (math.log(S / K) + (r + 0.5 * safe_sigma * safe_sigma) * t) / (safe_sigma * sqrt_t)
        d2 = d1 - safe_sigma * sqrt_t
        if is_call:
            price = S * _std_norm_cdf(d1) - K * math.exp(-r * t) * _std_norm_cdf(d2)
        else:
            price = K * math.exp(-r * t) * _std_norm_cdf(-d2) - S * _std_norm_cdf(-d1)
        return float(max(price, 0.0))
    except Exception:
        return float(max(S - K, 0.0) if is_call else max(K - S, 0.0))


def calculate_option_delta(
    flag: str,
    S: float,
    K: float,
    days_to_expiry: float,
    r: float = 0.065,
    sigma: float = 0.20,
) -> float:
    """
    Calculates analytical option Delta using _std_norm_cdf(d1).

    Args:
        flag: Option flag ('c' for Call, 'p' for Put).
        S: Current underlying asset spot price.
        K: Strike price of the option contract.
        days_to_expiry: Remaining time to expiration in days.
        r: Annualized risk-free interest rate (default 0.065).
        sigma: Implied volatility as a decimal (default 0.20).

    Returns:
        Delta value (+0.0 to +1.0 for Call, -1.0 to 0.0 for Put).
    """
    if S is None or K is None or S <= 0 or K <= 0:
        return 0.0

    t = days_to_expiry / 365.0
    flag_lower = flag.lower()
    is_call = flag_lower.startswith("c")

    if t <= 0.001:
        if is_call:
            return 1.0 if S > K else 0.0
        else:
            return -1.0 if S < K else 0.0

    safe_sigma = max(sigma, 0.01)
    try:
        sqrt_t = math.sqrt(t)
        d1 = (math.log(S / K) + (r + 0.5 * safe_sigma * safe_sigma) * t) / (safe_sigma * sqrt_t)
        if is_call:
            return float(_std_norm_cdf(d1))
        else:
            return float(_std_norm_cdf(d1) - 1.0)
    except Exception:
        return 0.5 if is_call else -0.5


def find_strike_for_delta(
    flag: str,
    S: float,
    target_delta: float | str | None,
    days_to_expiry: float = 30.0,
    r: float = 0.065,
    sigma: float = 0.20,
) -> float:
    """
    Solves for the option strike price K that closest matches a target Delta.

    Args:
        flag: Option flag ('c' for Call, 'p' for Put).
        S: Current underlying asset spot price.
        target_delta: Target delta value (e.g. 0.50, 0.20, "deep_otm_momentum").
        days_to_expiry: Days to expiration (default 30.0).
        r: Risk-free rate.
        sigma: Volatility.

    Returns:
        Closest matching strike price K.
    """
    if target_delta is None or S <= 0:
        return float(S)

    if isinstance(target_delta, str):
        if target_delta == "deep_otm_momentum":
            target_val = 0.15
        elif target_delta == "otm":
            target_val = 0.20
        elif target_delta == "itm":
            target_val = 0.70
        else:
            try:
                target_val = float(target_delta)
            except ValueError:
                return float(S)
    else:
        target_val = float(target_delta)

    target_val = abs(target_val)
    if abs(target_val - 0.50) < 0.05:
        return float(S)

    t = days_to_expiry / 365.0
    if t <= 0.001:
        return float(S)

    safe_sigma = max(sigma, 0.01)
    best_strike = float(S)
    best_diff = 999.0

    sqrt_t = math.sqrt(t)
    sigma_sqrt_t = safe_sigma * sqrt_t
    r_plus_half_sig2_t = (r + 0.5 * safe_sigma * safe_sigma) * t
    is_call = flag.lower().startswith("c")

    for k_mult in np.linspace(0.70, 1.30, 61):
        K = round(S * k_mult, 2)
        if K <= 0:
            continue
        try:
            d1 = (math.log(S / K) + r_plus_half_sig2_t) / sigma_sqrt_t
            d = _std_norm_cdf(d1) if is_call else _std_norm_cdf(-d1)
            diff = abs(d - target_val)
            if diff < best_diff:
                best_diff = diff
                best_strike = K
        except Exception:
            continue

    return float(best_strike)
