"""
Anchored VWAP Continuation (AVPC) Afternoon Strategy (DeepSeek Quant Model).

Strategy Logic (15-minute intraday resolution):
- Calculates Anchored VWAP (AVWAP) starting at the beginning of each trading day.
- Calculates 20-period Exponential Moving Average (20-EMA) and 20-period Volume SMA.
- Determines Market Regime:
  - Bullish Regime: Close > AVWAP AND Close > 20-EMA.
  - Bearish Regime: Close < AVWAP AND Close < 20-EMA.
- Triggers high-conviction BUY setups on pullback continuations:
  - In Bullish Regime, when Low <= AVWAP * 1.001 and Close >= AVWAP * 1.001 with Volume >= 1.0 * 20-volume SMA.
- Emits ATM 0.50 Delta Call Option signals with 1.5 * ATR stop loss and 3.0 * ATR profit target (2.0 R:R).
"""

from typing import List
import numpy as np
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Signal


class AVPCAfternoonStrategy(BaseStrategy):
    """
    Anchored VWAP Continuation (AVPC) Strategy.

    Identifies intraday trend continuation setups during afternoon sessions off Anchored VWAP.
    """

    def __init__(
        self,
        ema_period: int = 20,
        vol_period: int = 20,
        atr_period: int = 14,
        vwap_buffer_pct: float = 0.001,  # 0.1% buffer near AVWAP
        name: str = "AVPCAfternoonStrategy",
    ):
        """
        Initialize AVPCAfternoonStrategy parameters.

        Args:
            ema_period: Exponential Moving Average span (default 20).
            vol_period: Volume SMA lookback window (default 20).
            atr_period: Average True Range lookback window (default 14).
            vwap_buffer_pct: Percentage buffer near Anchored VWAP (default 0.001 = 0.1%).
            name: Strategy identifier name.
        """
        super().__init__(name=name)
        self.ema_period = ema_period
        self.vol_period = vol_period
        self.atr_period = atr_period
        self.vwap_buffer_pct = vwap_buffer_pct

    def generate_signals(self, df: pd.DataFrame) -> List[Signal]:
        """
        Generate AVPC signals from an intraday ADR-005 market data DataFrame.

        Args:
            df: Standardized ADR-005 market data DataFrame.

        Returns:
            List of generated Signal objects.
        """
        if df is None or df.empty or len(df) < max(self.ema_period, self.vol_period):
            return []

        data = df.copy()
        symbol = str(data["symbol"].iloc[0])

        # 1. Calculate Typical Price
        data["tp"] = (data["high"] + data["low"] + data["close"]) / 3.0
        data["tp_vol"] = data["tp"] * data["volume"]

        # 2. Daily Anchored VWAP calculation
        if isinstance(data.index, pd.DatetimeIndex):
            data["date"] = data.index.date
            cum_tp_vol = data.groupby("date")["tp_vol"].cumsum()
            cum_vol = data.groupby("date")["volume"].cumsum()
            data["vwap"] = np.where(cum_vol > 0, cum_tp_vol / cum_vol, data["close"])
        else:
            cum_tp_vol = data["tp_vol"].cumsum()
            cum_vol = data["volume"].cumsum()
            data["vwap"] = np.where(cum_vol > 0, cum_tp_vol / cum_vol, data["close"])

        # 3. 20-EMA & 20-Volume SMA
        data["ema_20"] = data["close"].ewm(span=self.ema_period, adjust=False).mean()
        data["vol_avg_20"] = data["volume"].rolling(window=self.vol_period, min_periods=1).mean()

        # 4. 14-period ATR
        tr1 = data["high"] - data["low"]
        tr2 = (data["high"] - data["close"].shift(1)).abs()
        tr3 = (data["low"] - data["close"].shift(1)).abs()
        data["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        data["atr_14"] = data["tr"].rolling(window=self.atr_period, min_periods=1).mean()

        signals: List[Signal] = []
        min_bars = max(self.ema_period, self.vol_period)

        for i in range(min_bars, len(data)):
            row = data.iloc[i]

            close_p = float(row["close"])
            low_p = float(row["low"])
            vwap_p = float(row["vwap"])
            ema_p = float(row["ema_20"])
            vol = float(row["volume"])
            vol_avg = float(row["vol_avg_20"])
            atr_val = float(row["atr_14"]) if not pd.isna(row["atr_14"]) else 0.02 * close_p

            if pd.isna(vwap_p) or pd.isna(ema_p):
                continue

            # Regime Check
            is_bull_regime = (close_p > vwap_p) and (close_p > ema_p)

            # Pullback Continuation Trigger
            vwap_threshold = vwap_p * (1.0 + self.vwap_buffer_pct)
            near_vwap_pullback = (low_p <= vwap_threshold) and (close_p >= vwap_threshold)
            volume_confirmed = (vol_avg > 0) and (vol >= 1.0 * vol_avg)

            if is_bull_regime and near_vwap_pullback and volume_confirmed:
                stop_dist = 1.5 * atr_val if atr_val > 0 else 0.02 * close_p
                stop_p = round(max(close_p - stop_dist, 0.01), 2)
                target_p = round(close_p + (2.0 * stop_dist), 2)

                signal = Signal(
                    symbol=symbol,
                    timestamp=row.name,
                    action="BUY",
                    strategy_name=self.name,
                    confidence=0.85,
                    entry_price=close_p,
                    target_price=target_p,
                    stop_loss=stop_p,
                    metadata={
                        "type": "OPTION",
                        "option_type": "c",
                        "delta_target": 0.50,
                        "regime": "bull_avpc",
                        "vwap": round(vwap_p, 2),
                        "ema_20": round(ema_p, 2),
                        "atr_14": round(atr_val, 2),
                    },
                )
                signals.append(signal)

        return signals
