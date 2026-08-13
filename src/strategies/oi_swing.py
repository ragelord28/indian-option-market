"""
Open Interest (OI) Regime Swing Breakout Strategy.

Strategy Logic:
- Identifies 3 consecutive trading days of range contraction (shrinking high - low range).
- Checks Open Interest (OI) buildup: Requires cumulative OI expansion >= 5% during the 3-day contraction period.
- Emits a directional BUY signal when price breaks out above the 3-day max high.
- Targeted at ATM (0.50 Delta) options directional swing setups.
"""

from typing import List
import numpy as np
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Signal


class OISwingStrategy(BaseStrategy):
    """
    OI Regime Swing Breakout Strategy.

    Detects 3-day volatility compression with cumulative OI buildup (>= 5%)
    followed by price expansion above the 3-day high.
    """

    def __init__(
        self,
        contraction_days: int = 3,
        min_oi_buildup_pct: float = 0.05,  # 5% cumulative OI expansion requirement
        name: str = "OISwingStrategy",
    ):
        """
        Initialize the OISwingStrategy parameters.

        Args:
            contraction_days: Number of consecutive range contraction days required (default 3).
            min_oi_buildup_pct: Minimum cumulative OI growth required over contraction period (default 0.05 = 5%).
            name: Strategy identifier name.
        """
        super().__init__(name=name)
        self.contraction_days = contraction_days
        self.min_oi_buildup_pct = min_oi_buildup_pct

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

            # Check OI accumulation: Cumulative OI growth over the contraction period >= 5%
            has_oi_col = "open_interest" in data.columns and not data["open_interest"].isna().all()
            if has_oi_col:
                oi_start = float(data["open_interest"].iloc[i - 3])
                oi_curr = float(data["open_interest"].iloc[i - 1])
                oi_buildup = ((oi_curr - oi_start) / oi_start) if (oi_start > 0 and not pd.isna(oi_start) and not pd.isna(oi_curr)) else self.min_oi_buildup_pct
            else:
                # If Open Interest column is NaN (e.g. Yahoo Finance), check DataFrame metadata or default to threshold
                oi_buildup = float(df.attrs.get("oi_buildup_pct", self.min_oi_buildup_pct))

            if oi_buildup < self.min_oi_buildup_pct:
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
                        "oi_buildup_pct": round(oi_buildup, 4),
                        "3day_max_high": max_high_3d,
                        "3day_min_low": min_low_3d,
                    },
                )
                signals.append(signal)

        return signals
