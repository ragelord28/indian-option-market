"""
Open Interest (OI) Regime Swing Breakout Strategy.

Strategy Logic:
- Identifies 3 consecutive trading days of volatility/range contraction (shrinking high - low range).
- Emits a directional BUY signal when price breaks out above the maximum high of the 3-day contraction period.
- Targeted at ATM (0.50 Delta) options directional swing setups.
"""

from typing import List
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Signal


class OISwingStrategy(BaseStrategy):
    """
    OI Regime Swing Breakout Strategy.

    Detects 3-day volatility compression followed by price expansion above the 3-day high.
    """

    def __init__(
        self,
        contraction_days: int = 3,
        name: str = "OISwingStrategy",
    ):
        """
        Initialize the OISwingStrategy parameters.

        Args:
            contraction_days: Number of consecutive range contraction days required (default 3).
            name: Strategy identifier name.
        """
        super().__init__(name=name)
        self.contraction_days = contraction_days

    def generate_signals(self, df: pd.DataFrame) -> List[Signal]:
        """
        Generate range contraction swing breakout signals from standard market data DataFrame.

        Args:
            df: Standardized ADR-005 market data DataFrame.

        Returns:
            List of generated Signal objects.
        """
        min_required = self.contraction_days + 1
        if df is None or df.empty or len(df) < min_required:
            return []

        data = df.copy()
        symbol = str(data["symbol"].iloc[0])

        # Daily high-low range
        data["range"] = data["high"] - data["low"]

        signals: List[Signal] = []

        for i in range(min_required, len(data)):
            curr_row = data.iloc[i]

            # Look at prior contraction_days (e.g., i-3, i-2, i-1)
            r1 = float(data["range"].iloc[i - 3])
            r2 = float(data["range"].iloc[i - 2])
            r3 = float(data["range"].iloc[i - 1])

            # Check 3 consecutive days of shrinking range: r3 < r2 < r1
            is_contracting = (r3 < r2) and (r2 < r1)

            if not is_contracting:
                continue

            # Check breakout above the 3-day max high
            max_high_3d = float(
                max(
                    data["high"].iloc[i - 3],
                    data["high"].iloc[i - 2],
                    data["high"].iloc[i - 1],
                )
            )
            min_low_3d = float(
                min(
                    data["low"].iloc[i - 3],
                    data["low"].iloc[i - 2],
                    data["low"].iloc[i - 1],
                )
            )

            close_p = float(curr_row["close"])

            if close_p > max_high_3d:
                target_p = round(close_p * 1.04, 2)
                stop_p = round(min_low_3d, 2) if min_low_3d < close_p else round(close_p * 0.98, 2)

                signal = Signal(
                    symbol=symbol,
                    timestamp=curr_row.name,
                    action="BUY",
                    strategy_name=self.name,
                    confidence=0.80,
                    entry_price=close_p,
                    target_price=target_p,
                    stop_loss=stop_p,
                    metadata={
                        "type": "OPTION",
                        "option_type": "c",
                        "delta_target": 0.50,
                        "range_contraction_days": self.contraction_days,
                        "3day_max_high": max_high_3d,
                        "3day_min_low": min_low_3d,
                    },
                )
                signals.append(signal)

        return signals
