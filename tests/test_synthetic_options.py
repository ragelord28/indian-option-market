"""
Unit tests for Synthetic Options pricing and Delta strike solver (src/backtester/synthetic_options.py).
"""

import pytest
import math
from src.backtester.synthetic_options import (
    calculate_option_price,
    calculate_option_delta,
    find_strike_for_delta,
)


def test_calculate_option_price_call_and_put():
    """Verify Black-Scholes pricing for standard ATM call and put options."""
    S = 100.0
    K = 100.0
    dte = 30.0
    r = 0.065
    sigma = 0.20

    call_p = calculate_option_price("c", S, K, dte, r, sigma)
    put_p = calculate_option_price("p", S, K, dte, r, sigma)

    assert call_p > 0.0
    assert put_p > 0.0

    # Put-Call parity check: C - P = S - K * exp(-r * t)
    t = dte / 365.0
    pv_k = K * math.exp(-r * t)
    parity_diff = abs((call_p - put_p) - (S - pv_k))
    assert parity_diff < 1e-10


def test_calculate_option_price_expired():
    """Verify expired options (days_to_expiry <= 0.001) return intrinsic value."""
    # ITM Call -> S - K
    assert calculate_option_price("c", S=110.0, K=100.0, days_to_expiry=0.0) == 10.0
    # OTM Call -> 0.0
    assert calculate_option_price("c", S=90.0, K=100.0, days_to_expiry=0.0005) == 0.0

    # ITM Put -> K - S
    assert calculate_option_price("p", S=90.0, K=100.0, days_to_expiry=0.0) == 10.0
    # OTM Put -> 0.0
    assert calculate_option_price("p", S=110.0, K=100.0, days_to_expiry=0.0005) == 0.0


def test_calculate_option_price_invalid_inputs():
    """Verify edge cases for invalid inputs (spot <= 0 or strike <= 0)."""
    assert calculate_option_price("c", S=0.0, K=100.0, days_to_expiry=30.0) == 0.0
    assert calculate_option_price("c", S=100.0, K=-50.0, days_to_expiry=30.0) == 0.0


def test_calculate_option_delta():
    """Verify analytical option delta calculation."""
    S = 100.0
    K = 100.0
    dte = 30.0

    call_delta = calculate_option_delta("c", S, K, dte)
    put_delta = calculate_option_delta("p", S, K, dte)

    # ATM Call Delta ~ 0.54, Put Delta ~ -0.46
    assert 0.50 < call_delta < 0.60
    assert -0.50 < put_delta < -0.40
    # Delta relationship: Call Delta - Put Delta = 1.0
    assert abs((call_delta - put_delta) - 1.0) < 1e-10

    # Expired delta tests
    assert calculate_option_delta("c", S=110.0, K=100.0, days_to_expiry=0.0) == 1.0
    assert calculate_option_delta("c", S=90.0, K=100.0, days_to_expiry=0.0) == 0.0
    assert calculate_option_delta("p", S=90.0, K=100.0, days_to_expiry=0.0) == -1.0
    assert calculate_option_delta("p", S=110.0, K=100.0, days_to_expiry=0.0) == 0.0


def test_find_strike_for_delta():
    """Verify delta strike solver matching."""
    S = 24000.0

    # ATM delta (0.50) returns spot S
    assert find_strike_for_delta("c", S, target_delta=0.50) == float(S)
    assert find_strike_for_delta("p", S, target_delta=0.50) == float(S)

    # String alias mappings
    otm_call_k = find_strike_for_delta("c", S, target_delta="otm", days_to_expiry=30.0)
    assert otm_call_k > S  # OTM Call strike is higher than spot

    otm_put_k = find_strike_for_delta("p", S, target_delta="otm", days_to_expiry=30.0)
    assert otm_put_k < S  # OTM Put strike is lower than spot

    deep_otm_k = find_strike_for_delta("c", S, target_delta="deep_otm_momentum")
    assert deep_otm_k > otm_call_k

    # Expired option returns spot S
    assert find_strike_for_delta("c", S, target_delta=0.20, days_to_expiry=0.0) == float(S)

    # None or invalid target delta returns spot S
    assert find_strike_for_delta("c", S, target_delta=None) == float(S)
    assert find_strike_for_delta("c", S, target_delta="invalid") == float(S)
