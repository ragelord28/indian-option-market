"""
Unit tests for Strategy Engine (src/strategies/).

Per CodingStandards.md:
- Tests mirror src/ structure (src/strategies/ -> tests/test_strategies.py).
- Tests cover Signal dataclass validation, BaseStrategy Rule 8 quality filtering,
  and SMACrossoverStrategy crossover signal generation.
"""

from datetime import datetime
import numpy as np
import pandas as pd
import pytest

from src.strategies.base_strategy import Signal, BaseStrategy
from src.strategies.sma_cross import SMACrossoverStrategy


@pytest.fixture
def mock_adr005_df() -> pd.DataFrame:
    """
    Fixture creating a mock 100-row ADR-005 compliant DataFrame with a clear
    20/50 SMA crossover around row 60.
    """
    dates = pd.date_range(start="2024-01-01", periods=100, freq="D", tz="Asia/Kolkata")

    # Generate price series: flat/downtrend first 50 days, strong uptrend next 50 days
    prices = [100.0 - (i * 0.1) for i in range(50)] + [
        95.0 + ((i - 50) * 1.5) for i in range(50, 100)
    ]

    df = pd.DataFrame(
        {
            "symbol": ["RELIANCE"] * 100,
            "open": [p - 0.5 for p in prices],
            "high": [p + 1.0 for p in prices],
            "low": [p - 1.0 for p in prices],
            "close": prices,
            "adj_close": prices,
            "volume": [100000] * 100,
            "open_interest": [np.nan] * 100,
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
    assert sig.target_price == 2550.0
    assert sig.stop_loss == 2475.0
    assert sig.metadata["greeks"]["delta"] == 0.5


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


def test_sma_crossover_strategy(mock_adr005_df: pd.DataFrame):
    """Test SMACrossoverStrategy signal generation on ADR-005 DataFrame."""
    strategy = SMACrossoverStrategy(fast_period=20, slow_period=50)
    signals = strategy.generate_signals(mock_adr005_df)

    assert isinstance(signals, list)
    assert len(signals) >= 1

    sig = signals[0]
    assert isinstance(sig, Signal)
    assert sig.symbol == "RELIANCE"
    assert sig.action == "BUY"
    assert sig.strategy_name == "SMACrossover_20_50"
    assert sig.confidence >= 0.60  # Only Rule 8 passing signals emitted!
    assert sig.entry_price > 0.0
    assert sig.target_price is not None
    assert sig.stop_loss is not None
    assert "sma_fast" in sig.metadata
    assert "sma_slow" in sig.metadata


def test_sma_crossover_suppresses_low_confidence():
    """Test that weak crossovers resulting in confidence < 0.60 are suppressed."""
    strategy = SMACrossoverStrategy(fast_period=5, slow_period=10)

    # Create price series with a tiny crossover yielding diff < 0.005 (confidence = 0.40)
    dates = pd.date_range("2024-01-01", periods=20, freq="D", tz="Asia/Kolkata")
    prices = [10.0] * 12 + [10.001, 10.002, 10.003, 10.004, 10.005, 10.006, 10.007, 10.008]
    df = pd.DataFrame(
        {
            "symbol": ["TCS"] * 20,
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "adj_close": prices,
            "volume": [1000] * 20,
            "open_interest": [np.nan] * 20,
        },
        index=dates,
    )
    df.index.name = "timestamp"

    signals = strategy.generate_signals(df)
    # The low-confidence crossover (0.40) must be suppressed by Rule 8 filter
    for sig in signals:
        assert sig.confidence >= 0.60
