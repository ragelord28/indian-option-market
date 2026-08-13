"""
Backtesting Engine Module for the Indian Option Market platform.

Provides synthetic Black-Scholes options pricing, trade tracking, backtesting
execution, and side-by-side strategy benchmarking.
"""

from src.backtester.trade import Trade
from src.backtester.synthetic_options import calculate_option_price
from src.backtester.engine import BacktestEngine
from src.backtester.benchmark import run_benchmark, calculate_max_drawdown

__all__ = [
    "Trade",
    "calculate_option_price",
    "BacktestEngine",
    "run_benchmark",
    "calculate_max_drawdown",
]
