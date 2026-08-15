"""
Synthetic Options Pricing & Delta Strike Solver Module using Black-Scholes-Merton.

Enables historical options trade simulation off underlying equity OHLCV data
without requiring expensive historical tick option datasets.
"""

import numpy as np
from py_vollib.black_scholes import black_scholes
from py_vollib.black_scholes.greeks.analytical import delta


def calculate_option_price(
    flag: str,
    S: float,
    K: float,
    days_to_expiry: float,
    r: float = 0.065,
    sigma: float = 0.20,
) -> float:
    """
    Calculates Black-Scholes option price, handling expiration safely.

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
    if S <= 0 or K <= 0:
        return 0.0

    t = days_to_expiry / 365.0
    if t <= 0.001:  # Expired or expiring today (intrinsic value)
        return float(max(S - K, 0.0) if flag == "c" else max(K - S, 0.0))

    # Safe sigma bounds
    safe_sigma = max(sigma, 0.01)
    try:
        price = float(black_scholes(flag, S, K, t, r, safe_sigma))
        return max(price, 0.0)
    except Exception:
        return float(max(S - K, 0.0) if flag == "c" else max(K - S, 0.0))


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

    for k_mult in np.linspace(0.70, 1.30, 61):
        K = round(S * k_mult, 2)
        try:
            d = abs(delta(flag, S, K, t, r, safe_sigma))
            diff = abs(d - target_val)
            if diff < best_diff:
                best_diff = diff
                best_strike = K
        except Exception:
            continue

    return float(best_strike)
