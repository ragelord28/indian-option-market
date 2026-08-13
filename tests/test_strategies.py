"""
Unit tests for Strategy Engine (src/strategies/).

Per CodingStandards.md:
- Tests mirror src/ structure (src/strategies/ -> tests/test_strategies.py).
- Tests cover Signal dataclass validation, BaseStrategy Rule 8 quality filtering,
  composite_factors dynamic scoring, and concrete strategy implementations:
  1. ORBMomentumStrategy
  2. HedgedVolPremiumStrategy
  3. OISwingStrategy
  4. RelativeStrengthVWAPReversionStrategy
  5. CompositeHolyGrailStrategy
  6. AVPCAfternoonStrategy
"""

import numpy as np
import pandas as pd
import pytest

from src.strategies.base_strategy import Signal, BaseStrategy
from src.strategies.orb_momentum import ORBMomentumStrategy
from src.strategies.hedged_vol_premium import HedgedVolPremiumStrategy
from src.strategies.oi_swing import OISwingStrategy
from src.strategies.custom_research_strategy import RelativeStrengthVWAPReversionStrategy
from src.strategies.composite_holy_grail import CompositeHolyGrailStrategy
from src.strategies.avpc_afternoon import AVPCAfternoonStrategy


@pytest.fixture
def mock_adr005_df() -> pd.DataFrame:
    """Fixture creating a 150-row mock ADR-005 DataFrame for strategy testing."""
    dates = pd.date_range(start="2024-01-01", periods=150, freq="D", tz="Asia/Kolkata")
    
    np.random.seed(42)
    base_price = 1000.0
    returns = np.random.normal(0.001, 0.02, 150)
    returns[110:130] = np.random.normal(0.005, 0.05, 20)

    prices = [base_price]
    for r in returns[1:]:
        prices.append(prices[-1] * (1.0 + r))

    volumes = [100000] * 150
    volumes[50] = 300000

    highs = [p * 1.015 for p in prices]
    lows = [p * 0.985 for p in prices]

    highs[80], lows[80] = prices[80] + 20.0, prices[80] - 20.0
    highs[81], lows[81] = prices[81] + 10.0, prices[81] - 10.0
    highs[82], lows[82] = prices[82] + 5.0, prices[82] - 5.0
    highs[83], lows[83] = prices[83] + 25.0, prices[83] - 2.0
    prices[83] = highs[82] + 10.0

    df = pd.DataFrame(
        {
            "symbol": ["RELIANCE"] * 150,
            "open": prices,
            "high": highs,
            "low": lows,
            "close": prices,
            "adj_close": prices,
            "volume": volumes,
            "open_interest": [100000] * 150,
        },
        index=dates,
    )
    df.index.name = "timestamp"
    return df


def test_signal_dataclass():
    """Test Signal dataclass initialization and field attributes."""
    ts = pd.Timestamp("2024-01-01 09:15:00", tz="Asia/Kolkata")
    sig = Signal(
        symbol="RELIANCE",
        timestamp=ts,
        action="BUY",
        strategy_name="TestStrategy",
        confidence=0.85,
        entry_price=2500.0,
        target_price=2550.0,
        stop_loss=2475.0,
        metadata={"greeks": {"delta": 0.5}},
    )

    assert sig.symbol == "RELIANCE"
    assert sig.action == "BUY"
    assert sig.confidence == 0.85
    assert sig.entry_price == 2500.0


class DummyStrategy(BaseStrategy):
    """Concrete dummy strategy for testing BaseStrategy filter logic."""

    def generate_signals(self, df: pd.DataFrame):
        return []


def test_rule_8_filter():
    """Test Rule 8 quality filtering (confidence < 0.60 rejected)."""
    strat = DummyStrategy(name="Dummy")
    ts = pd.Timestamp("2024-01-01", tz="Asia/Kolkata")

    high_conf_sig = Signal(
        symbol="TCS",
        timestamp=ts,
        action="BUY",
        strategy_name="Dummy",
        confidence=0.75,
        entry_price=3000.0,
    )
    low_conf_sig = Signal(
        symbol="TCS",
        timestamp=ts,
        action="BUY",
        strategy_name="Dummy",
        confidence=0.40,
        entry_price=3000.0,
    )

    assert strat.filter_signal_rule_8(high_conf_sig) is True
    assert strat.filter_signal_rule_8(low_conf_sig) is False


def test_composite_factors_rule_8_dynamic_scoring():
    """Test Phase 8.5 dynamic multi-factor confidence scoring under Rule 8."""
    strat = DummyStrategy(name="CompositeTest")
    ts = pd.Timestamp("2024-01-01", tz="Asia/Kolkata")

    # Case 1: All factors False -> Base 0.50 score -> < 0.60 -> Rejected
    sig_low = Signal(
        symbol="INFY",
        timestamp=ts,
        action="BUY",
        strategy_name="CompositeTest",
        confidence=0.50,
        entry_price=1500.0,
        metadata={
            "composite_factors": {
                "daily_adx_gt_20": False,
                "rsi_15m_divergence": False,
                "vwap_5m_reversion": False,
                "vol_15m_surge": False,
                "oi_surge": False,
            }
        },
    )
    assert strat.filter_signal_rule_8(sig_low) is False
    assert sig_low.confidence == 0.50

    # Case 2: Partial factors (base 0.50 + vwap_5m_reversion 0.15 = 0.65) -> Passed
    sig_mid = Signal(
        symbol="INFY",
        timestamp=ts,
        action="BUY",
        strategy_name="CompositeTest",
        confidence=0.50,
        entry_price=1500.0,
        metadata={
            "composite_factors": {
                "daily_adx_gt_20": False,
                "rsi_15m_divergence": False,
                "vwap_5m_reversion": True,  # +0.15
                "vol_15m_surge": False,
                "oi_surge": False,
            }
        },
    )
    assert strat.filter_signal_rule_8(sig_mid) is True
    assert sig_mid.confidence == 0.65

    # Case 3: All factors True (0.50 + 0.10 + 0.15 + 0.15 + 0.10 + 0.10 = 1.10 -> Capped at 0.99) -> Passed
    sig_high = Signal(
        symbol="INFY",
        timestamp=ts,
        action="BUY",
        strategy_name="CompositeTest",
        confidence=0.50,
        entry_price=1500.0,
        metadata={
            "composite_factors": {
                "daily_adx_gt_20": True,
                "rsi_15m_divergence": True,
                "vwap_5m_reversion": True,
                "vol_15m_surge": True,
                "oi_surge": True,
            }
        },
    )
    assert strat.filter_signal_rule_8(sig_high) is True
    assert sig_high.confidence == 0.99


def test_orb_momentum_strategy(mock_adr005_df: pd.DataFrame):
    """Test ORBMomentumStrategy signal generation."""
    strategy = ORBMomentumStrategy()
    signals = strategy.generate_signals(mock_adr005_df)

    assert isinstance(signals, list)
    if len(signals) > 0:
        sig = signals[0]
        assert sig.action == "BUY"
        assert sig.confidence == 0.85
        assert sig.metadata["delta_target"] == "deep_otm_momentum"


def test_hedged_vol_premium_strategy(mock_adr005_df: pd.DataFrame):
    """Test HedgedVolPremiumStrategy signal generation."""
    strategy = HedgedVolPremiumStrategy(hv_period=10, lookback_window=30, percentile_threshold=50.0)
    signals = strategy.generate_signals(mock_adr005_df)

    assert isinstance(signals, list)
    if len(signals) > 0:
        sig = signals[0]
        assert sig.action == "SELL"
        assert sig.confidence == 0.75
        assert sig.metadata["delta_target"] == 0.20


def test_oi_swing_strategy(mock_adr005_df: pd.DataFrame):
    """Test OISwingStrategy signal generation on range contraction breakout."""
    strategy = OISwingStrategy(contraction_days=3)
    signals = strategy.generate_signals(mock_adr005_df)

    assert isinstance(signals, list)
    if len(signals) > 0:
        sig = signals[0]
        assert sig.action == "BUY"
        assert sig.confidence == 0.80
        assert sig.metadata["delta_target"] == 0.50


def test_relative_strength_vwap_reversion_strategy(mock_adr005_df: pd.DataFrame):
    """Test RelativeStrengthVWAPReversionStrategy custom research strategy."""
    strategy = RelativeStrengthVWAPReversionStrategy(rsi_period=14, vwap_dist_threshold=0.001)
    signals = strategy.generate_signals(mock_adr005_df)

    assert isinstance(signals, list)
    for sig in signals:
        assert sig.confidence == 0.82
        assert sig.metadata["strategy"] == "vwap_rsi_reversion"
        assert strategy.filter_signal_rule_8(sig) is True


def test_composite_holy_grail_strategy(mock_adr005_df: pd.DataFrame):
    """Test CompositeHolyGrailStrategy multi-factor signal generation."""
    strategy = CompositeHolyGrailStrategy(rsi_period=14)
    signals = strategy.generate_signals(mock_adr005_df)

    assert isinstance(signals, list)
    for sig in signals:
        assert "composite_factors" in sig.metadata
        passed = strategy.filter_signal_rule_8(sig)
        assert isinstance(passed, bool)
        assert sig.confidence >= 0.50


def test_avpc_afternoon_strategy(mock_adr005_df: pd.DataFrame):
    """Test AVPCAfternoonStrategy Anchored VWAP Continuation signal generation."""
    strategy = AVPCAfternoonStrategy()
    signals = strategy.generate_signals(mock_adr005_df)

    assert isinstance(signals, list)
    for sig in signals:
        assert sig.action == "BUY"
        assert sig.confidence == 0.85
        assert sig.metadata["regime"] == "bull_avpc"
        assert strategy.filter_signal_rule_8(sig) is True
