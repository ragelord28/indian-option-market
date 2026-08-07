"""
Base Strategy Interface and Signal Data Structure.

Defines:
1. Signal: Dataclass representing a generated trade setup.
2. BaseStrategy: Abstract base class for all trading strategies with Rule 8 signal filtering.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd


@dataclass
class Signal:
    """
    Standard trade signal emitted by strategy modules.

    Attributes:
        symbol: Standardized internal stock/index symbol (e.g. 'RELIANCE').
        timestamp: Signal generation timestamp (datetime or pd.Timestamp).
        action: Trade direction ('BUY' or 'SELL').
        strategy_name: Identifier of the strategy generating the signal.
        confidence: Signal confidence score (0.0 to 1.0).
        entry_price: Trigger price at signal generation.
        target_price: Optional profit target price.
        stop_loss: Optional stop-loss price.
        metadata: Optional dictionary for Greeks, IV, indicators, and additional context.
    """

    symbol: str
    timestamp: Any
    action: str
    strategy_name: str
    confidence: float
    entry_price: float
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """
    Abstract Base Class for all Strategy Engine modules.

    All strategy implementations (e.g. SMACrossoverStrategy) must inherit from this
    class and implement `generate_signals`.
    """

    def __init__(self, name: str = "BaseStrategy"):
        """Initialize base strategy with a name."""
        self.name = name

    def filter_signal_rule_8(self, signal: Signal) -> bool:
        """
        Baseline Rule 8 Quality Filter (per Core.md Rule 8 & Quant_Rules.md).

        Suppresses low-quality or noisy trade signals.
        Rejects any signal with confidence < 0.60.

        Args:
            signal: The candidate Signal instance to evaluate.

        Returns:
            True if the signal passes Rule 8 quality filtering, False if suppressed.
        """
        if signal is None:
            return False

        if signal.confidence < 0.60:
            return False

        return True

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> List[Signal]:
        """
        Generate trade signals from an ADR-005 compliant market data DataFrame.

        Args:
            df: Standardized market data DataFrame.

        Returns:
            List of validated Signal objects that passed Rule 8 quality filtering.
        """
        pass
