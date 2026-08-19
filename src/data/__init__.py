"""
Data Ingestion & Caching Module for the Indian Option Market platform.

This module provides data provider adapters (e.g. YahooFinanceProvider, UpstoxProvider),
standard schema validation according to ADR-005, and option chain analytics.
"""

from src.data.base_provider import BaseDataProvider, validate_schema
from src.data.yahoo_provider import YahooFinanceProvider
from src.data.upstox_provider import UpstoxProvider, fetch_live_quotes_batch, check_upstox_live_status
from src.data.option_analytics import (
    calculate_pcr,
    interpret_pcr,
    calculate_vrp,
    find_max_pain,
    rank_strikes,
    get_best_strike,
)
from src.data.strategy_builder import build_optimal_strategy, build_naked_itm_ticket

__all__ = [
    "BaseDataProvider",
    "validate_schema",
    "YahooFinanceProvider",
    "UpstoxProvider",
    "fetch_live_quotes_batch",
    "check_upstox_live_status",
    "calculate_pcr",
    "interpret_pcr",
    "calculate_vrp",
    "find_max_pain",
    "rank_strikes",
    "get_best_strike",
    "build_optimal_strategy",
    "build_naked_itm_ticket",
]
