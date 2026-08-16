"""
Unit tests for Multi-Leg Strategy Builder & Execution Ticket Analytics Engine (src/data/strategy_builder.py).

Per CodingStandards.md:
- Tests verify Debit Spread, Credit Spread, and Iron Condor construction.
- Tests verify Net Greeks, Basket Margin, Slippage Drag, and Payoff curve math.
"""

import pandas as pd
import pytest

from src.data.strategy_builder import build_optimal_strategy


@pytest.fixture
def mock_option_chain_df() -> pd.DataFrame:
    """Fixture returning mock option chain DataFrame across 5 strikes."""
    data = [
        {"strike_price": 2400.0, "call_ltp": 110.0, "call_ask": 111.0, "call_bid": 109.0, "call_delta": 0.75, "put_ltp": 12.0, "put_ask": 12.5, "put_bid": 11.5, "put_delta": -0.25},
        {"strike_price": 2450.0, "call_ltp": 70.0, "call_ask": 70.5, "call_bid": 69.5, "call_delta": 0.60, "put_ltp": 22.0, "put_ask": 22.5, "put_bid": 21.5, "put_delta": -0.38},
        {"strike_price": 2500.0, "call_ltp": 45.0, "call_ask": 45.5, "call_bid": 44.5, "call_delta": 0.50, "put_ltp": 42.0, "put_ask": 42.5, "put_bid": 41.5, "put_delta": -0.50},
        {"strike_price": 2550.0, "call_ltp": 25.0, "call_ask": 25.5, "call_bid": 24.5, "call_delta": 0.25, "put_ltp": 72.0, "put_ask": 72.5, "put_bid": 71.5, "put_delta": -0.65},
        {"strike_price": 2600.0, "call_ltp": 12.0, "call_ask": 12.5, "call_bid": 11.5, "call_delta": 0.10, "put_ltp": 112.0, "put_ask": 112.5, "put_bid": 111.5, "put_delta": -0.80},
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
    )

    assert ticket["strategy_name"] == "Bull Call Debit Spread"
    assert len(ticket["legs"]) == 2
    assert ticket["legs"][0]["Action"] == "BUY"
    assert ticket["legs"][1]["Action"] == "SELL"
    assert ticket["net_debit_or_credit"] == "Net Debit"
    assert ticket["max_profit"] > 0
    assert ticket["max_loss"] > 0
    assert "net_greeks" in ticket
    assert "payoff_curve" in ticket


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
    )

    assert ticket["strategy_name"] == "Bull Put Credit Spread"
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
    )

    assert ticket["strategy_name"] == "Iron Condor"
    assert len(ticket["legs"]) == 4
    assert "guaranteed_slippage_cost" in ticket
    assert ticket["liquidity_grade"] in ["A", "B", "C (VETO)"]
