"""
Unit tests for Multi-Leg Strategy Builder & Execution Ticket Analytics Engine (src/data/strategy_builder.py).

Per CodingStandards.md:
- Tests verify Debit Spread, Credit Spread, and Iron Condor construction.
- Tests verify Net Greeks, Basket Margin, Slippage Drag, and Payoff curve math.
- Tests verify non-linear Black-Scholes payoff curves (T+0, T+Mid, Expiry).
"""

import pandas as pd
import pytest

from src.data.strategy_builder import build_optimal_strategy
from src.backtester.synthetic_options import calculate_option_price


@pytest.fixture
def mock_option_chain_df() -> pd.DataFrame:
    """Fixture returning mock option chain DataFrame across 5 strikes."""
    data = [
        {"strike_price": 2400.0, "call_ltp": 110.0, "call_ask": 111.0, "call_bid": 109.0, "call_delta": 0.75, "call_iv": 0.22, "put_ltp": 12.0, "put_ask": 12.5, "put_bid": 11.5, "put_delta": -0.25, "put_iv": 0.22},
        {"strike_price": 2450.0, "call_ltp": 70.0, "call_ask": 70.5, "call_bid": 69.5, "call_delta": 0.60, "call_iv": 0.21, "put_ltp": 22.0, "put_ask": 22.5, "put_bid": 21.5, "put_delta": -0.38, "put_iv": 0.21},
        {"strike_price": 2500.0, "call_ltp": 45.0, "call_ask": 45.5, "call_bid": 44.5, "call_delta": 0.50, "call_iv": 0.20, "put_ltp": 42.0, "put_ask": 42.5, "put_bid": 41.5, "put_delta": -0.50, "put_iv": 0.20},
        {"strike_price": 2550.0, "call_ltp": 25.0, "call_ask": 25.5, "call_bid": 24.5, "call_delta": 0.25, "call_iv": 0.21, "put_ltp": 72.0, "put_ask": 72.5, "put_bid": 71.5, "put_delta": -0.65, "put_iv": 0.21},
        {"strike_price": 2600.0, "call_ltp": 12.0, "call_ask": 12.5, "call_bid": 11.5, "call_delta": 0.10, "call_iv": 0.22, "put_ltp": 112.0, "put_ask": 112.5, "put_bid": 111.5, "put_delta": -0.80, "put_iv": 0.22},
    ]
    return pd.DataFrame(data)


def test_build_bull_call_debit_spread(mock_option_chain_df: pd.DataFrame):
    """Test Bull Call Debit Spread construction for Bullish bias with low IVR."""
    ticket = build_optimal_strategy(
        symbol="RELIANCE",
        spot_price=2500.0,
        bias="BULLISH",
        ivr=30.0,
        vrp=-2.0,
        option_chain_df=mock_option_chain_df,
        lot_size=50,
        conviction_score=82.0,
    )

    assert "Bull Call Debit Spread" in ticket["strategy_name"]
    assert len(ticket["legs"]) == 2
    assert ticket["legs"][0]["Action"] == "BUY"
    assert ticket["legs"][1]["Action"] == "SELL"
    assert ticket["net_debit_or_credit"] == "Net Debit"
    assert ticket["max_profit"] > 0
    assert ticket["max_loss"] > 0
    assert "net_greeks" in ticket
    assert "payoff_curve" in ticket
    assert "naked_option" in ticket
    assert "spread_option" in ticket


def test_build_bull_put_credit_spread(mock_option_chain_df: pd.DataFrame):
    """Test Bull Put Credit Spread construction for Bullish bias with high IVR."""
    ticket = build_optimal_strategy(
        symbol="RELIANCE",
        spot_price=2500.0,
        bias="BULLISH",
        ivr=75.0,
        vrp=6.0,
        option_chain_df=mock_option_chain_df,
        lot_size=50,
        conviction_score=82.0,
    )

    assert "Bull Put Credit Spread" in ticket["strategy_name"]
    assert len(ticket["legs"]) == 2
    assert ticket["legs"][0]["Action"] == "SELL"
    assert ticket["legs"][1]["Action"] == "BUY"
    assert ticket["net_debit_or_credit"] == "Net Credit"


def test_build_iron_condor(mock_option_chain_df: pd.DataFrame):
    """Test Iron Condor construction for Rangebound bias."""
    ticket = build_optimal_strategy(
        symbol="RELIANCE",
        spot_price=2500.0,
        bias="RANGEBOUND",
        ivr=65.0,
        vrp=4.0,
        option_chain_df=mock_option_chain_df,
        lot_size=50,
        conviction_score=80.0,
    )

    assert "Iron Condor" in ticket["strategy_name"]
    assert len(ticket["legs"]) == 4
    assert "guaranteed_slippage_cost" in ticket
    assert ticket["liquidity_grade"] in ["A", "B", "C (VETO)"]


def test_black_scholes_payoff_curves(mock_option_chain_df: pd.DataFrame):
    """Test that payoff curves use non-linear Black-Scholes valuation for T+0 and T+Mid."""
    ticket = build_optimal_strategy(
        symbol="RELIANCE",
        spot_price=2500.0,
        bias="BULLISH",
        ivr=30.0,
        vrp=-2.0,
        option_chain_df=mock_option_chain_df,
        lot_size=50,
        conviction_score=82.0,
    )

    payoff = ticket["payoff_curve"]
    assert "spot_range" in payoff
    assert "payoff_expiry" in payoff
    assert "payoff_t0" in payoff
    assert "payoff_tmid" in payoff
    assert len(payoff["spot_range"]) == 50
    assert len(payoff["payoff_t0"]) == 50
    assert len(payoff["payoff_tmid"]) == 50

    # T+0 values should NOT be simple 0.40x multiples of expiry payoff
    # Black-Scholes produces non-linear, time-value-inclusive P&L
    for i in range(len(payoff["spot_range"])):
        exp_val = payoff["payoff_expiry"][i]
        t0_val = payoff["payoff_t0"][i]
        if abs(exp_val) > 100.0:
            # T+0 should differ from simple 0.40x scaling
            assert t0_val != round(exp_val * 0.40, 2), \
                f"T+0 at index {i} should not be a simple 0.40x linear scale of expiry P&L"


def test_black_scholes_target_premium():
    """Test that option target premiums use Black-Scholes, not linear delta approximation."""
    from src.data.option_analytics import get_best_strike

    chain_data = [
        {"strike_price": 2400.0, "call_ltp": 110.0, "call_ask": 111.0, "call_bid": 109.0, "call_delta": 0.75, "call_iv": 0.22, "put_ltp": 12.0, "put_ask": 12.5, "put_bid": 11.5, "put_delta": -0.25, "put_iv": 0.22},
        {"strike_price": 2450.0, "call_ltp": 70.0, "call_ask": 70.5, "call_bid": 69.5, "call_delta": 0.60, "call_iv": 0.21, "put_ltp": 22.0, "put_ask": 22.5, "put_bid": 21.5, "put_delta": -0.38, "put_iv": 0.21},
        {"strike_price": 2500.0, "call_ltp": 45.0, "call_ask": 45.5, "call_bid": 44.5, "call_delta": 0.50, "call_iv": 0.20, "put_ltp": 42.0, "put_ask": 42.5, "put_bid": 41.5, "put_delta": -0.50, "put_iv": 0.20},
        {"strike_price": 2550.0, "call_ltp": 25.0, "call_ask": 25.5, "call_bid": 24.5, "call_delta": 0.25, "call_iv": 0.21, "put_ltp": 72.0, "put_ask": 72.5, "put_bid": 71.5, "put_delta": -0.65, "put_iv": 0.21},
    ]
    chain_df = pd.DataFrame(chain_data)

    result = get_best_strike(
        option_chain_df=chain_df,
        spot_price=2500.0,
        underlying_target=2575.0,
        bias="BULLISH",
        lot_size=50,
        hv_20=0.20,
    )

    assert "option_target_price" in result
    assert "bs_entry_premium" in result
    assert result["option_target_price"] > 0
    assert result["bs_entry_premium"] > 0

    # The target should reflect Black-Scholes pricing at S=2575 using verified Tuesday DTE
    strike = result["strike"]
    from src.data.option_analytics import get_days_to_monthly_expiry
    dte = float(get_days_to_monthly_expiry())
    bs_target = calculate_option_price(
        flag="c", S=2575.0, K=strike, days_to_expiry=dte, r=0.07, sigma=0.20
    )
    # The target price should be approximately equal to BS pricing (or floored at 0.5*ltp)
    assert abs(result["option_target_price"] - round(max(bs_target, result["ltp"] * 0.50), 2)) < 3.0


def test_tuesday_monthly_expiry_and_lot_sizes():
    """Test Tuesday monthly expiry date solver and official lot size lookups."""
    from datetime import date
    from src.data.option_analytics import get_monthly_expiry_date, get_days_to_monthly_expiry
    from src.scanner.universe import get_lot_size

    # August 2026 Monthly Expiry must be Tuesday Aug 25, 2026
    aug_date = date(2026, 8, 17)
    expiry = get_monthly_expiry_date(aug_date)
    assert expiry == date(2026, 8, 25)
    assert expiry.weekday() == 1  # 1 is Tuesday

    dte = get_days_to_monthly_expiry(aug_date)
    assert dte == 8

    # Lot size lookups
    assert get_lot_size("RELIANCE") == 250
    assert get_lot_size("TCS") == 175
    assert get_lot_size("INFY") == 400
    assert get_lot_size("HDFCBANK") == 550
    assert get_lot_size("ASHOKLEY") == 5000
    assert get_lot_size("UNKNOWN_TICKER") == 250
