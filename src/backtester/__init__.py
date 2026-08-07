"""
Backtesting Engine Module for the Indian Option Market platform.

Provides synthetic Black-Scholes options pricing, trade tracking, and backtesting
execution against historical market data DataFrames.
"""

from src.backtester.trade import Trade
from src.backtester.synthetic_options import calculate_option_price
from src.backtester.engine import BacktestEngine

__all__ = [
    "Trade",
    "calculate_option_price",
    "BacktestEngine",
]
