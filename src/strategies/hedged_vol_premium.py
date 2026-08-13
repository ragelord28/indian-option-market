"""
Tail-Hedged Volatility Premium Strategy.

Strategy Logic:
- Calculates 20-day annualized Historical Volatility (HV).
- Calculates the HV percentile rank over a trailing 100-day window to simulate IV Rank (IVR).
- Emits a premium-selling SELL signal (simulating Credit Spreads / Iron Condors) when HV percentile > 80th percentile.
- Configured with 0.20 Delta target per Quant_Rules.md.
"""

from typing import List
import numpy as np
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Signal


class HedgedVolPremiumStrategy(BaseStrategy):
    """
    Tail-Hedged Volatility Premium Strategy.

    Identifies elevated volatility regimes (HV percentile > 80th percentile)
    to sell option premium via credit spread / iron condor structures.
    """

    def __init__(
        self,
        hv_period: int = 20,
        lookback_window: int = 100,
        percentile_threshold: float = 80.0,
        name: str = "HedgedVolPremiumStrategy",
    ):
        """
        Initialize the HedgedVolPremiumStrategy parameters.

        Args:
            hv_period: Period for historical volatility calculation (default 20 days).
            lookback_window: Trailing window for HV percentile ranking (default 100 days).
            percentile_threshold: Minimum percentile threshold to trigger premium sell (default 80.0).
            name: Strategy identifier name.
        """
        super().__init__(name=name)
        self.hv_period = hv_period
        self.lookback_window = lookback_window
        self.percentile_threshold = percentile_threshold

    def generate_signals(self, df: pd.DataFrame) -> List[Signal]:
        """
        Generate volatility premium SELL signals from standard market data DataFrame.

        Args:
            df: Standardized ADR-005 market data DataFrame.

        Returns:
            List of generated Signal objects.
        """
        min_required = self.hv_period + self.lookback_window
        if df is None or df.empty or len(df) < min_required:
            return []

        data = df.copy()
        symbol = str(data["symbol"].iloc[0])

        # 1. Log returns and 20-day annualized Historical Volatility
        data["log_ret"] = np.log(data["close"] / data["close"].shift(1))
        data["hv_20"] = data["log_ret"].rolling(window=self.hv_period).std() * np.sqrt(252)

        # 2. HV Percentile rank over trailing 100 days
        hv_min = data["hv_20"].rolling(window=self.lookback_window).min()
        hv_max = data["hv_20"].rolling(window=self.lookback_window).max()
        hv_denom = hv_max - hv_min

        # Avoid division by zero
        data["hv_percentile"] = np.where(
            hv_denom > 0, ((data["hv_20"] - hv_min) / hv_denom) * 100.0, 0.0
        )

        signals: List[Signal] = []

        for i in range(min_required, len(data)):
            row = data.iloc[i]
            hv_pct = float(row["hv_percentile"])
            price = float(row["close"])

            if pd.isna(hv_pct):
                continue

            if hv_pct > self.percentile_threshold:
                target_p = round(price * 0.98, 2)
                stop_p = round(price * 1.02, 2)

                signal = Signal(
                    symbol=symbol,
                    timestamp=row.name,
                    action="SELL",
                    strategy_name=self.name,
                    confidence=0.75,
                    entry_price=price,
                    target_price=target_p,
                    stop_loss=stop_p,
                    metadata={
                        "type": "OPTION",
                        "option_type": "c",
                        "strategy": "iron_condor_sim",
                        "delta_target": 0.20,
                        "hv_20": round(float(row["hv_20"]), 4),
                        "hv_percentile": round(hv_pct, 2),
                    },
                )
                signals.append(signal)

        return signals
