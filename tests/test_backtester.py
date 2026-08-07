"""
Unit tests for Backtesting Engine (src/backtester/).

Per CodingStandards.md:
- Tests mirror src/ structure (src/backtester/ -> tests/test_backtester.py).
- Tests cover synthetic Black-Scholes pricing, Trade tracking, and BacktestEngine execution.
"""

from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pytest

from src.backtester.synthetic_options import calculate_option_price
from src.backtester.trade import Trade
from src.backtester.engine import BacktestEngine
from src.strategies.sma_cross import SMACrossoverStrategy
from src.strategies.base_strategy import Signal, BaseStrategy


@pytest.fixture
def mock_adr005_df() -> pd.DataFrame:
    """Fixture returning a mock 100-row ADR-005 DataFrame with a SMA crossover."""
    dates = pd.date_range(start="2024-01-01", periods=100, freq="D", tz="Asia/Kolkata")
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


def test_calculate_option_price_black_scholes():
    """Test Black-Scholes pricing calculation for Call and Put options."""
    # ATM Call option with 30 DTE should have positive premium
    call_price = calculate_option_price("c", S=100.0, K=100.0, days_to_expiry=30.0)
    assert call_price > 0.0

    # ATM Put option with 30 DTE should have positive premium
    put_price = calculate_option_price("p", S=100.0, K=100.0, days_to_expiry=30.0)
    assert put_price > 0.0

    # Expired Call option (days_to_expiry = 0) returns intrinsic value max(S - K, 0)
    assert calculate_option_price("c", S=110.0, K=100.0, days_to_expiry=0.0) == 10.0
    assert calculate_option_price("c", S=90.0, K=100.0, days_to_expiry=0.0) == 0.0

    # Expired Put option (days_to_expiry = 0) returns intrinsic value max(K - S, 0)
    assert calculate_option_price("p", S=90.0, K=100.0, days_to_expiry=0.0) == 10.0
    assert calculate_option_price("p", S=110.0, K=100.0, days_to_expiry=0.0) == 0.0


def test_backtest_engine_run(mock_adr005_df: pd.DataFrame):
    """Test BacktestEngine execution with SMACrossoverStrategy."""
    strategy = SMACrossoverStrategy(fast_period=20, slow_period=50)
    engine = BacktestEngine(strategy=strategy, initial_capital=100000.0)

    result = engine.run(mock_adr005_df)

    assert "metrics" in result
    assert "trades" in result

    metrics = result["metrics"]
    trades = result["trades"]

    assert metrics["total_trades"] == len(trades)
    assert metrics["total_trades"] >= 1
    assert "win_rate" in metrics
    assert "total_pnl" in metrics
    assert metrics["final_capital"] == round(100000.0 + metrics["total_pnl"], 2)

    trade = trades[0]
    assert isinstance(trade, Trade)
    assert trade.symbol == "RELIANCE"
    assert trade.trade_type == "STOCK"
    assert trade.entry_price > 0.0
    assert trade.exit_price > 0.0
    assert trade.quantity > 0


class DummyOptionStrategy(BaseStrategy):
    """Dummy strategy generating an OPTION trade signal."""

    def generate_signals(self, df: pd.DataFrame) -> list:
        if df.empty:
            return []
        ts = df.index[10]
        price = float(df["close"].iloc[10])
        return [
            Signal(
                symbol="NIFTY50",
                timestamp=ts,
                action="BUY",
                strategy_name="OptionTest",
                confidence=0.80,
                entry_price=price,
                metadata={"type": "OPTION"},
            )
        ]


def test_backtest_engine_option_trade(mock_adr005_df: pd.DataFrame):
    """Test BacktestEngine processing option trade signals with synthetic Black-Scholes pricing."""
    strategy = DummyOptionStrategy(name="OptionTest")
    engine = BacktestEngine(strategy=strategy, initial_capital=100000.0)

    result = engine.run(mock_adr005_df)
    trades = result["trades"]

    assert len(trades) == 1
    trade = trades[0]

    assert trade.trade_type == "OPTION"
    assert trade.quantity == 100
    assert trade.entry_price > 0.0
    assert trade.exit_price > 0.0
    assert "strike" in trade.metadata
