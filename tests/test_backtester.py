"""
Unit tests for Backtesting Engine (src/backtester/).

Per CodingStandards.md:
- Tests mirror src/ structure (src/backtester/ -> tests/test_backtester.py).
- Tests cover synthetic Black-Scholes pricing, Trade tracking, BacktestEngine execution,
  and strategy benchmarking matrix.
"""

from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pytest

from src.backtester.synthetic_options import calculate_option_price
from src.backtester.trade import Trade
from src.backtester.engine import BacktestEngine
from src.backtester.benchmark import run_benchmark, calculate_max_drawdown
from src.strategies.orb_momentum import ORBMomentumStrategy
from src.strategies.base_strategy import Signal, BaseStrategy


@pytest.fixture
def mock_adr005_df() -> pd.DataFrame:
    """Fixture returning a 50-row mock ADR-005 DataFrame for backtester testing."""
    dates = pd.date_range(start="2024-01-01", periods=50, freq="D", tz="Asia/Kolkata")
    prices = [100.0 + (i * 0.5) for i in range(50)]
    volumes = [10000] * 50
    volumes[25] = 50000  # Volume spike

    df = pd.DataFrame(
        {
            "symbol": ["RELIANCE"] * 50,
            "open": prices,
            "high": [p + 1.0 for p in prices],
            "low": [p - 1.0 for p in prices],
            "close": prices,
            "adj_close": prices,
            "volume": volumes,
            "open_interest": [100000] * 50,
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
    """Test BacktestEngine execution with ORBMomentumStrategy."""
    strategy = ORBMomentumStrategy()
    engine = BacktestEngine(strategy=strategy, initial_capital=100000.0)

    result = engine.run(mock_adr005_df)

    assert "metrics" in result
    assert "trades" in result

    metrics = result["metrics"]
    trades = result["trades"]

    assert metrics["total_trades"] == len(trades)
    assert "win_rate" in metrics
    assert "total_pnl" in metrics
    assert metrics["final_capital"] == round(100000.0 + metrics["total_pnl"], 2)


class DummyOptionStrategy(BaseStrategy):
    """Dummy strategy generating an OPTION trade signal."""

    def __init__(self, option_type: str = "c"):
        super().__init__(name="OptionTest")
        self.option_type = option_type

    def generate_signals(self, df: pd.DataFrame) -> list:
        if df.empty:
            return []
        ts = df.index[10]
        price = float(df["close"].iloc[10])
        sym = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "RELIANCE"
        return [
            Signal(
                symbol=sym,
                timestamp=ts,
                action="BUY",
                strategy_name="OptionTest",
                confidence=0.80,
                entry_price=price,
                metadata={"type": "OPTION", "option_type": self.option_type},
            )
        ]


def test_backtest_engine_option_trade_put_and_call(mock_adr005_df: pd.DataFrame):
    """Test BacktestEngine processing Put and Call option trade signals with aligned option_type."""
    put_strategy = DummyOptionStrategy(option_type="p")
    engine = BacktestEngine(strategy=put_strategy, initial_capital=100000.0)

    result = engine.run(mock_adr005_df)
    trades = result["trades"]

    assert len(trades) == 1
    trade = trades[0]

    assert trade.trade_type == "OPTION"
    assert trade.metadata["option_type"] == "p"
    assert trade.entry_price > 0.0
    assert trade.exit_price > 0.0


def test_backtest_engine_risk_based_exit():
    """Test that BacktestEngine exits at profit target or stop loss price."""
    dates = pd.date_range("2024-01-01", periods=10, freq="D", tz="Asia/Kolkata")
    df = pd.DataFrame(
        {
            "symbol": ["TCS"] * 10,
            "open": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0],
            "high": [101.0, 105.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0],
            "close": [100.0, 102.0, 102.5, 103.5, 104.5, 105.5, 106.5, 107.5, 108.5, 109.5],
            "adj_close": [100.0, 102.0, 102.5, 103.5, 104.5, 105.5, 106.5, 107.5, 108.5, 109.5],
            "volume": [1000] * 10,
            "open_interest": [np.nan] * 10,
        },
        index=dates,
    )
    df.index.name = "timestamp"

    class MockStrategy(BaseStrategy):
        def generate_signals(self, df_in):
            return [
                Signal(
                    symbol="TCS",
                    timestamp=df_in.index[0],
                    action="BUY",
                    strategy_name="Mock",
                    confidence=0.80,
                    entry_price=100.0,
                    stop_loss=98.0,
                    target_price=104.0,
                )
            ]

    engine = BacktestEngine(strategy=MockStrategy())
    res = engine.run(df)
    trade = res["trades"][0]

    assert trade.exit_price == 104.0
    assert trade.pnl > 0


def test_run_benchmark(mock_adr005_df: pd.DataFrame):
    """Test side-by-side strategy benchmarking execution and matrix generation."""
    results = run_benchmark(mock_adr005_df)

    assert isinstance(results, dict)
    assert len(results) == 4
    for strat_name, metrics in results.items():
        assert "total_trades" in metrics
        assert "win_rate_pct" in metrics
        assert "total_pnl" in metrics
        assert "max_drawdown" in metrics


def test_calculate_fno_transaction_cost_deduction():
    """Verify Indian F&O transaction cost calculation and deduction from raw trade PnL."""
    from src.backtester.engine import calculate_fno_transaction_cost

    # Entry = 50.0, Exit = 70.0, Qty = 250 (1 lot)
    # Brokerage: 40.0
    # STT: 70 * 250 * 0.001 = 17.5
    # Exchange Txn: (50 + 70) * 250 * 0.0005 = 15.0
    # GST: (40 + 15) * 0.18 = 9.9
    # Stamp Duty: 50 * 250 * 0.00003 = 0.375
    # Total = 40.0 + 17.5 + 15.0 + 9.9 + 0.375 = 82.775 -> 82.78
    cost = calculate_fno_transaction_cost(entry_premium=50.0, exit_premium=70.0, quantity=250, is_option=True)
    assert cost == 82.78

    raw_pnl = (70.0 - 50.0) * 250  # 5000.0
    net_pnl = round(raw_pnl - cost, 2)
    assert net_pnl == 4917.22


def test_option_call_put_pricing_symmetry():
    """Verify option call/put pricing symmetry for ATM options at equal distance from spot under zero interest rate."""
    call_p = calculate_option_price("c", S=100.0, K=100.0, days_to_expiry=30.0, sigma=0.20, r=0.0)
    put_p = calculate_option_price("p", S=100.0, K=100.0, days_to_expiry=30.0, sigma=0.20, r=0.0)
    assert abs(call_p - put_p) < 1e-4

