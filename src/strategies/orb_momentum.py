"""
Opening Range Breakout (ORB) Momentum Snipe Strategy.

Strategy Logic:
- Identifies the opening 15-minute price range (high and low).
- Emits a high-confidence BUY signal when price breaks above opening range high
  accompanied by volume expansion (> 2.0x 20-period average volume) and ATR expansion
  (current 14-period ATR > 1.2x 14-period ATR SMA).
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
    with volume confirmation > 2.0x average volume and expanding ATR (> 1.2x ATR SMA).
    """

    def __init__(
        self,
        volume_multiplier: float = 2.0,
        vol_window: int = 20,
        name: str = "ORBMomentumStrategy",
    ):
        """
        Initialize the ORBMomentumStrategy parameters.

        Args:
            volume_multiplier: Minimum volume ratio compared to trailing average (default 2.0).
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

        # 14-period Average True Range (ATR) & ATR 14-period SMA
        tr1 = data["high"] - data["low"]
        tr2 = (data["high"] - data["close"].shift(1)).abs()
        tr3 = (data["low"] - data["close"].shift(1)).abs()
        data["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        data["atr_14"] = data["tr"].rolling(window=14).mean()
        data["atr_sma_14"] = data["atr_14"].rolling(window=14).mean()

        signals: List[Signal] = []

        has_intraday = isinstance(data.index, pd.DatetimeIndex) and any(
            data.index.hour != 0
        )

        if has_intraday:
            data["date"] = data.index.date
            for date, group in data.groupby("date"):
                if len(group) < 2:
                    continue
                first_bars = group.between_time("09:15", "09:30")
                if first_bars.empty:
                    first_bars = group.iloc[:1]

                orb_high = float(first_bars["high"].max())
                orb_low = float(first_bars["low"].min())

                trading_bars = group[group.index > first_bars.index[-1]]
                for idx, row in trading_bars.iterrows():
                    close_p = float(row["close"])
                    vol = float(row["volume"])
                    vol_avg = float(row["vol_avg"]) if not pd.isna(row["vol_avg"]) else 0.0

                    atr_val = float(row["atr_14"]) if not pd.isna(row["atr_14"]) else 0.0
                    atr_sma = float(row["atr_sma_14"]) if not pd.isna(row["atr_sma_14"]) else 0.0
                    atr_expanding = (atr_sma > 0.0) and (atr_val > 1.25 * atr_sma)

                    if (
                        close_p > orb_high
                        and vol > (self.volume_multiplier * vol_avg)
                        and vol_avg > 0
                        and atr_expanding
                    ):
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
                                "volume_ratio": round(vol / vol_avg, 2) if vol_avg > 0 else 2.0,
                                "atr_expanding": atr_expanding,
                            },
                        )
                        signals.append(signal)
        else:
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

                prev_range = float(prev_row["high"] - prev_row["low"])
                orb_high = open_p + (0.3 * prev_range) if prev_range > 0 else open_p * 1.005
                orb_low = min(open_p, low_p)

                atr_val = float(row["atr_14"]) if not pd.isna(row["atr_14"]) else 0.0
                atr_sma = float(row["atr_sma_14"]) if not pd.isna(row["atr_sma_14"]) else 0.0
                atr_expanding = (atr_sma > 0.0) and (atr_val > 1.25 * atr_sma)

                if (
                    close_p > orb_high
                    and vol > (self.volume_multiplier * vol_avg)
                    and atr_expanding
                ):
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
                            "atr_expanding": atr_expanding,
                        },
                    )
                    signals.append(signal)

        return signals
