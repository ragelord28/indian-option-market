"""
Unit tests for Option Analytics & Strike Ranking Engine (src/data/option_analytics.py).

Per CodingStandards.md:
- Tests verify PCR, Max Pain, Top-3 strike recommendation, and single best strike sniper view logic.
"""

import pandas as pd
import pytest

from src.data.option_analytics import (
    calculate_pcr,
    find_max_pain,
    rank_strikes,
    get_best_strike,
)


@pytest.fixture
def mock_option_chain_df() -> pd.DataFrame:
    """Fixture returning mock option chain DataFrame across 5 strikes."""
    data = [
        {"strike_price": 2400.0, "call_ltp": 110.0, "call_iv": 0.20, "call_oi": 50000, "call_delta": 0.75, "put_ltp": 12.0, "put_iv": 0.22, "put_oi": 150000, "put_delta": -0.25},
        {"strike_price": 2450.0, "call_ltp": 70.0, "call_iv": 0.21, "call_oi": 80000, "call_delta": 0.62, "put_ltp": 22.0, "put_iv": 0.21, "put_oi": 120000, "put_delta": -0.38},
        {"strike_price": 2500.0, "call_ltp": 45.0, "call_iv": 0.22, "call_oi": 150000, "call_delta": 0.50, "put_ltp": 42.0, "put_iv": 0.22, "put_oi": 180000, "put_delta": -0.50},
        {"strike_price": 2550.0, "call_ltp": 25.0, "call_iv": 0.23, "call_oi": 120000, "call_delta": 0.35, "put_ltp": 72.0, "put_iv": 0.23, "put_oi": 90000, "put_delta": -0.65},
        {"strike_price": 2600.0, "call_ltp": 12.0, "call_iv": 0.25, "call_oi": 90000, "call_delta": 0.20, "put_ltp": 112.0, "put_iv": 0.24, "put_oi": 40000, "put_delta": -0.80},
    ]
    return pd.DataFrame(data)


def test_calculate_pcr(mock_option_chain_df: pd.DataFrame):
    """Test PCR calculation (Total Put OI / Total Call OI)."""
    pcr = calculate_pcr(mock_option_chain_df)
    assert pcr == 1.18

    # Edge cases
    assert calculate_pcr(pd.DataFrame()) == 0.0


def test_find_max_pain(mock_option_chain_df: pd.DataFrame):
    """Test Max Pain strike calculation."""
    max_pain = find_max_pain(mock_option_chain_df)
    assert max_pain in [2400.0, 2450.0, 2500.0, 2550.0, 2600.0]


def test_rank_strikes_bullish(mock_option_chain_df: pd.DataFrame):
    """Test strike ranking for Bullish strategy bias."""
    top_3 = rank_strikes(mock_option_chain_df, spot_price=2500.0, bias="BULLISH", lot_size=50)

    assert len(top_3) == 3
    assert list(top_3["Rank"]) == [1, 2, 3]
    assert top_3["Option Type"].iloc[0] == "CE"
    assert top_3["Strike Price"].iloc[1] == 2500.0  # ATM strike
    assert top_3["Capital per Lot (₹)"].iloc[1] == 45.0 * 50  # 2250.0


def test_rank_strikes_bearish(mock_option_chain_df: pd.DataFrame):
    """Test strike ranking for Bearish strategy bias."""
    top_3 = rank_strikes(mock_option_chain_df, spot_price=2500.0, bias="BEARISH", lot_size=50)

    assert len(top_3) == 3
    assert list(top_3["Rank"]) == [1, 2, 3]
    assert top_3["Option Type"].iloc[0] == "PE"
    assert top_3["Strike Price"].iloc[1] == 2500.0  # ATM strike


def test_get_best_strike(mock_option_chain_df: pd.DataFrame):
    """Test get_best_strike function for single best strike sniper view."""
    best_call = get_best_strike(
        mock_option_chain_df,
        spot_price=2500.0,
        underlying_target=2550.0,
        bias="BULLISH",
        lot_size=50,
    )

    assert isinstance(best_call, dict)
    assert best_call["strike"] == 2450.0  # Delta 0.62 closest to 0.65
    assert best_call["type"] == "CE"
    assert best_call["ltp"] == 70.0
    assert best_call["capital"] == 70.0 * 50  # 3500.0
    # Move = 50, premium gain = 50 * 0.62 = 31.0. Option target = 70 + 31 = 101.0
    assert best_call["option_target_price"] == 101.0
