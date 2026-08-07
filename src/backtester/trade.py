"""
Trade Data Structure for Backtesting & Signal Execution.

Defines the Trade dataclass tracking trade execution, entry/exit prices, PnL,
and trade type ('STOCK' or 'OPTION').
"""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Trade:
    """
    Dataclass tracking individual simulated or live trades.

    Attributes:
        symbol: Standardized internal symbol (e.g. 'RELIANCE').
        entry_time: Timestamp of trade entry.
        exit_time: Timestamp of trade exit.
        entry_price: Price per share or option contract premium at entry.
        exit_price: Price per share or option contract premium at exit.
        quantity: Number of shares or option contracts traded.
        pnl: Absolute monetary profit and loss (exit_price - entry_price) * quantity.
        pnl_percent: Percentage return ((exit_price - entry_price) / entry_price) * 100.
        trade_type: Instrument type ('STOCK' or 'OPTION').
        metadata: Additional details (e.g. strike, expiry, Greeks, underlying price).
    """

    symbol: str
    entry_time: Any
    exit_time: Any
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    pnl_percent: float
    trade_type: str = "STOCK"
    metadata: Dict[str, Any] = field(default_factory=dict)
