"""
Strategy Engine Module for the Indian Option Market platform.

Provides BaseStrategy interface, Signal data structure, Rule 8 quality filtering,
and concrete trading strategy implementations.
"""

from src.strategies.base_strategy import Signal, BaseStrategy
from src.strategies.sma_cross import SMACrossoverStrategy

__all__ = [
    "Signal",
    "BaseStrategy",
    "SMACrossoverStrategy",
]
