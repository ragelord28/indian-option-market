"""
Synthetic Options Pricing Module using Black-Scholes-Merton.

Enables historical options trade simulation off underlying equity OHLCV data
without requiring expensive historical tick option datasets.
"""

from py_vollib.black_scholes import black_scholes


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
    t = days_to_expiry / 365.0
    if t <= 0.001:  # Expired or expiring today (intrinsic value)
        return float(max(S - K, 0.0) if flag == "c" else max(K - S, 0.0))
    return float(black_scholes(flag, S, K, t, r, sigma))
