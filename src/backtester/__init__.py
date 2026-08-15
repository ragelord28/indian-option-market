"""
Backtesting Engine Module for the Indian Option Market platform.

Provides synthetic Black-Scholes options pricing, trade tracking, backtesting
execution, and side-by-side strategy benchmarking.
"""

from src.backtester.trade import Trade
from src.backtester.synthetic_options import calculate_option_price, find_strike_for_delta
from src.backtester.engine import PortfolioEngine, BacktestEngine
from src.backtester.benchmark import (
    run_benchmark,
    calculate_max_drawdown,
    calculate_max_drawdown_pct,
)

__all__ = [
    "Trade",
    "calculate_option_price",
    "find_strike_for_delta",
    "PortfolioEngine",
    "BacktestEngine",
    "run_benchmark",
    "calculate_max_drawdown",
    "calculate_max_drawdown_pct",
]
