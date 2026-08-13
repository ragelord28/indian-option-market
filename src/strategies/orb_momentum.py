"""
Opening Range Breakout (ORB) Momentum Snipe Strategy.

Strategy Logic:
- Identifies the opening 15-minute price range (high and low).
- Emits a high-confidence BUY signal when price breaks above the opening range high
  accompanied by strong volume expansion (> 1.5x 20-period average volume).
- Tailored for Deep OTM momentum options setups on high-catalyst trading days.
"""

from typing import List
import numpy as np
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Signal


class ORBMomentumStrategy(BaseStrategy):
    """
    Opening Range Breakout (ORB) Momentum Strategy.

    Triggers momentum buy signals when spot breaks out of the opening range
    with volume confirmation > 1.5x 20-period average volume.
    """

    def __init__(
        self,
        volume_multiplier: float = 1.5,
        vol_window: int = 20,
        name: str = "ORBMomentumStrategy",
    ):
        """
        Initialize the ORBMomentumStrategy parameters.

        Args:
            volume_multiplier: Minimum volume ratio compared to trailing average (default 1.5).
            vol_window: Lookback window for volume moving average (default 20).
            name: Strategy identifier name.
        """
        super().__init__(name=name)
        self.volume_multiplier = volume_multiplier
        self.vol_window = vol_window

    def generate_signals(self, df: pd.DataFrame) -> List[Signal]:
        """
        Generate ORB momentum signals from standard market data DataFrame.

        Args:
            df: Standardized ADR-005 market data DataFrame.

        Returns:
            List of generated Signal objects.
        """
        if df is None or df.empty or len(df) < self.vol_window:
            return []

        data = df.copy()
        symbol = str(data["symbol"].iloc[0])

        # 20-period volume moving average
        data["vol_avg"] = data["volume"].rolling(window=self.vol_window).mean()

        signals: List[Signal] = []

        # Group data by date to establish opening range
        # For daily data, use previous day's high/low or first 15m bar proxy
        has_intraday = isinstance(data.index, pd.DatetimeIndex) and any(
            data.index.hour != 0
        )

        if has_intraday:
            # Intraday 15-minute opening range determination
            data["date"] = data.index.date
            for date, group in data.groupby("date"):
                if len(group) < 2:
                    continue
                # First 15m window bars (09:15 to 09:30)
                first_bars = group.between_time("09:15", "09:30")
                if first_bars.empty:
                    first_bars = group.iloc[:1]

                orb_high = float(first_bars["high"].max())
                orb_low = float(first_bars["low"].min())

                # Remaining bars of the session
                trading_bars = group[group.index > first_bars.index[-1]]
                for idx, row in trading_bars.iterrows():
                    close_p = float(row["close"])
                    vol = float(row["volume"])
                    vol_avg = float(row["vol_avg"]) if not pd.isna(row["vol_avg"]) else 0.0

                    if close_p > orb_high and vol > (self.volume_multiplier * vol_avg) and vol_avg > 0:
                        signal = Signal(
                            symbol=symbol,
                            timestamp=idx,
                            action="BUY",
                            strategy_name=self.name,
                            confidence=0.85,
                            entry_price=close_p,
                            target_price=round(close_p * 1.03, 2),
                            stop_loss=round(orb_low, 2) if orb_low < close_p else round(close_p * 0.98, 2),
                            metadata={
                                "type": "OPTION",
                                "option_type": "c",
                                "delta_target": "deep_otm_momentum",
                                "opening_range_high": orb_high,
                                "opening_range_low": orb_low,
                                "volume_ratio": round(vol / vol_avg, 2) if vol_avg > 0 else 1.5,
                            },
                        )
                        signals.append(signal)
        else:
            # Daily bar data approximation: Opening range established by day's Open to High/Low offset
            for i in range(self.vol_window, len(data)):
                row = data.iloc[i]
                prev_row = data.iloc[i - 1]

                close_p = float(row["close"])
                open_p = float(row["open"])
                high_p = float(row["high"])
                low_p = float(row["low"])
                vol = float(row["volume"])
                vol_avg = float(row["vol_avg"])

                if pd.isna(vol_avg) or vol_avg <= 0:
                    continue

                # Proxy opening range high as Open + 0.3 * (Prev High - Prev Low)
                prev_range = float(prev_row["high"] - prev_row["low"])
                orb_high = open_p + (0.3 * prev_range) if prev_range > 0 else open_p * 1.005
                orb_low = min(open_p, low_p)

                if close_p > orb_high and vol > (self.volume_multiplier * vol_avg):
                    signal = Signal(
                        symbol=symbol,
                        timestamp=row.name,
                        action="BUY",
                        strategy_name=self.name,
                        confidence=0.85,
                        entry_price=close_p,
                        target_price=round(close_p * 1.03, 2),
                        stop_loss=round(orb_low, 2) if orb_low < close_p else round(close_p * 0.98, 2),
                        metadata={
                            "type": "OPTION",
                            "option_type": "c",
                            "delta_target": "deep_otm_momentum",
                            "opening_range_high": round(orb_high, 2),
                            "opening_range_low": round(orb_low, 2),
                            "volume_ratio": round(vol / vol_avg, 2),
                        },
                    )
                    signals.append(signal)

        return signals
