"""
Strategy Benchmarking & Performance Comparison Matrix.

Runs all Phase 6/7 strategy modules against a market data DataFrame,
calculates side-by-side performance metrics (Total Trades, Win Rate, Total PnL, Max Drawdown),
and prints a formatted ASCII comparison matrix.
"""

from typing import Dict, Any, List
import pandas as pd

from src.strategies.orb_momentum import ORBMomentumStrategy
from src.strategies.hedged_vol_premium import HedgedVolPremiumStrategy
from src.strategies.oi_swing import OISwingStrategy
from src.strategies.custom_research_strategy import RelativeStrengthVWAPReversionStrategy
from src.backtester.engine import BacktestEngine


def calculate_max_drawdown(trades: list, initial_capital: float = 100000.0) -> float:
    """
    Calculate Maximum Drawdown (in ₹) from a list of executed Trade objects,
    sorting trades chronologically by exit time first.

    Args:
        trades: List of Trade objects returned by BacktestEngine.
        initial_capital: Initial portfolio capital.

    Returns:
        Maximum Drawdown in currency (₹).
    """
    if not trades:
        return 0.0

    # Sort trades chronologically by exit_time
    sorted_trades = sorted(trades, key=lambda t: t.exit_time)

    equity = initial_capital
    peak = initial_capital
    max_dd = 0.0

    for trade in sorted_trades:
        equity += trade.pnl
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return round(max_dd, 2)


def run_benchmark(df: pd.DataFrame, initial_capital: float = 100000.0) -> Dict[str, Any]:
    """
    Run side-by-side performance benchmark for strategy modules.

    Args:
        df: Standardized ADR-005 market data DataFrame.
        initial_capital: Initial portfolio capital for backtesting.

    Returns:
        Dictionary mapping strategy names to performance metrics.
    """
    strategies = [
        ORBMomentumStrategy(),
        HedgedVolPremiumStrategy(percentile_threshold=50.0),
        OISwingStrategy(),
        RelativeStrengthVWAPReversionStrategy(vwap_dist_threshold=0.005),
    ]

    results = {}

    print("\n" + "=" * 85)
    print(f"{'STRATEGY BENCHMARK & COMPARISON MATRIX':^85}")
    print("=" * 85)
    header = f"{'Strategy Name':<38} | {'Trades':<8} | {'Win Rate':<10} | {'Total PnL (₹)':<14} | {'Max DD (₹)':<12}"
    print(header)
    print("-" * 85)

    for strat in strategies:
        engine = BacktestEngine(strategy=strat, initial_capital=initial_capital)
        raw_signals = strat.generate_signals(df)
        valid_signals = [s for s in raw_signals if strat.filter_signal_rule_8(s)]

        res = engine.run(df, signals=valid_signals)

        metrics = res["metrics"]
        trades = res["trades"]
        max_dd = calculate_max_drawdown(trades, initial_capital)

        total_trades = metrics["total_trades"]
        win_rate_pct = f"{metrics['win_rate'] * 100:.1f}%"
        total_pnl = f"₹{metrics['total_pnl']:,.2f}"
        max_dd_fmt = f"₹{max_dd:,.2f}"

        strat_name = strat.name
        results[strat_name] = {
            "total_trades": total_trades,
            "win_rate_pct": win_rate_pct,
            "total_pnl": metrics["total_pnl"],
            "max_drawdown": max_dd,
            "final_capital": metrics["final_capital"],
            "trades": trades,
        }

        row_str = f"{strat_name:<38} | {total_trades:<8} | {win_rate_pct:<10} | {total_pnl:<14} | {max_dd_fmt:<12}"
        print(row_str)

    print("=" * 85 + "\n")
    return results


if __name__ == "__main__":
    import numpy as np

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

    sample_df = pd.DataFrame(
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
    sample_df.index.name = "timestamp"

    run_benchmark(sample_df)
