"""
Simple Moving Average (SMA) Crossover Strategy.

Implements a baseline dual moving average crossover strategy (20 SMA vs 50 SMA)
operating on ADR-005 compliant market data DataFrames. Emits BUY signals when
the fast SMA crosses above the slow SMA, subject to Rule 8 quality filtering.
"""

from typing import List, Optional
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Signal


class SMACrossoverStrategy(BaseStrategy):
    """
    Moving Average Crossover Strategy (20 SMA vs 50 SMA).

    Generates BUY signals on bullish crossovers. Signals are evaluated
    against Rule 8 (confidence >= 0.60) before emission.
    """

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 50,
        name: str = "SMACrossover_20_50",
    ):
        """
        Initialize the SMA Crossover Strategy parameters.

        Args:
            fast_period: Lookback window for the fast moving average (default 20).
            slow_period: Lookback window for the slow moving average (default 50).
            name: Strategy name identifier.
        """
        super().__init__(name=name)
        self.fast_period = fast_period
        self.slow_period = slow_period

    def generate_signals(self, df: pd.DataFrame) -> List[Signal]:
        """
        Generate trade signals for a given market data DataFrame.

        Args:
            df: Standardized market data DataFrame conforming to ADR-005.

        Returns:
            List of Signals that pass Rule 8 filtering (confidence >= 0.60).
        """
        if df is None or df.empty or len(df) < self.slow_period:
            return []

        # Make a shallow copy to calculate indicators without mutating input df
        data = df.copy()
        symbol = str(data["symbol"].iloc[0])

        # Calculate fast and slow Simple Moving Averages
        data["sma_fast"] = data["close"].rolling(window=self.fast_period).mean()
        data["sma_slow"] = data["close"].rolling(window=self.slow_period).mean()

        signals: List[Signal] = []

        # Iterate from slow_period onwards to check for crossovers
        for i in range(self.slow_period, len(data)):
            curr_row = data.iloc[i]
            prev_row = data.iloc[i - 1]

            # Bullish Crossover condition: fast SMA crosses above slow SMA
            prev_fast = prev_row["sma_fast"]
            prev_slow = prev_row["sma_slow"]
            curr_fast = curr_row["sma_fast"]
            curr_slow = curr_row["sma_slow"]

            if pd.isna(prev_fast) or pd.isna(prev_slow) or pd.isna(curr_fast) or pd.isna(curr_slow):
                continue

            if prev_fast <= prev_slow and curr_fast > curr_slow:
                # Calculate trend strength
                price = float(curr_row["close"])
                diff = (curr_fast - curr_slow) / price

                # Assign confidence: 0.80 for strong momentum diff, 0.65 for baseline crossover
                confidence = 0.80 if diff >= 0.005 else 0.65

                # Define target and stop-loss estimates (e.g. 2% target, 1% stop)
                target_price = round(price * 1.02, 2)
                stop_loss = round(price * 0.99, 2)

                signal = Signal(
                    symbol=symbol,
                    timestamp=curr_row.name,  # timestamp index
                    action="BUY",
                    strategy_name=self.name,
                    confidence=confidence,
                    entry_price=price,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    metadata={
                        "sma_fast": float(curr_fast),
                        "sma_slow": float(curr_slow),
                        "fast_period": self.fast_period,
                        "slow_period": self.slow_period,
                    },
                )

                # Filter signal through Rule 8 baseline quality filter before appending
                if self.filter_signal_rule_8(signal):
                    signals.append(signal)

        return signals
