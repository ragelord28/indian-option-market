"""
Relative Strength & VWAP Mean Reversion Strategy (Indian FnO Edge).

Research Edge & Citation:
Based on quantitative research from QuantInsti and Zerodha Varsity institutional trading studies:
- Institutional execution algorithms (FII/DII) benchmark heavily against Volume Weighted Average Price (VWAP).
- When a liquid FnO stock stretches > 1.5% away from VWAP concurrently with extreme RSI levels
  (RSI < 35 oversold or RSI > 65 overbought), price mean-reverts sharply back toward VWAP.
- Nifty 50 Macro Trend Filter: Only generates BUY Call signals when Nifty 50 is above its 20-day SMA,
  and BUY Put signals when Nifty 50 is below its 20-day SMA.
"""

from typing import List
import numpy as np
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Signal


class RelativeStrengthVWAPReversionStrategy(BaseStrategy):
    """
    Relative Strength & VWAP Mean Reversion Strategy.

    Combines VWAP distance tracking with 14-period RSI and Nifty 50 macro trend filter.
    """

    def __init__(
        self,
        rsi_period: int = 14,
        vwap_dist_threshold: float = 0.015,  # 1.5% distance from VWAP
        rsi_oversold: float = 35.0,
        rsi_overbought: float = 65.0,
        name: str = "RelativeStrengthVWAPReversionStrategy",
    ):
        """
        Initialize the RelativeStrengthVWAPReversionStrategy parameters.

        Args:
            rsi_period: Lookback window for RSI calculation (default 14).
            vwap_dist_threshold: Minimum percentage distance from VWAP to trigger reversion (default 0.015 = 1.5%).
            rsi_oversold: RSI threshold for oversold long call entry (default 35.0).
            rsi_overbought: RSI threshold for overbought long put entry (default 65.0).
            name: Strategy identifier name.
        """
        super().__init__(name=name)
        self.rsi_period = rsi_period
        self.vwap_dist_threshold = vwap_dist_threshold
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

    def _calculate_rsi(self, series: pd.Series, period: int) -> pd.Series:
        """Calculate 14-period Relative Strength Index (RSI)."""
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()

        rs = avg_gain / (avg_loss + 1e-9)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def generate_signals(self, df: pd.DataFrame) -> List[Signal]:
        """
        Generate VWAP + RSI mean-reversion signals with Nifty 50 macro trend filter.

        Args:
            df: Standardized ADR-005 market data DataFrame.

        Returns:
            List of generated Signal objects.
        """
        min_required = max(self.rsi_period + 5, 20)
        if df is None or df.empty or len(df) < min_required:
            return []

        data = df.copy()
        symbol = str(data["symbol"].iloc[0])

        # 1. Calculate Typical Price and Volume Weighted Average Price (VWAP) via 75-period rolling window
        data["tp"] = (data["high"] + data["low"] + data["close"]) / 3.0
        data["tp_vol"] = data["tp"] * data["volume"]

        roll_tp_vol = data["tp_vol"].rolling(window=75, min_periods=1).sum()
        roll_vol = data["volume"].rolling(window=75, min_periods=1).sum()
        data["vwap"] = np.where(roll_vol > 0, roll_tp_vol / roll_vol, data["close"])

        # 2. Percentage distance from VWAP: (close - vwap) / vwap
        data["vwap_dist"] = (data["close"] - data["vwap"]) / data["vwap"]

        # 3. Calculate RSI
        data["rsi"] = self._calculate_rsi(data["close"], self.rsi_period)

        # 4. Check Nifty 50 Macro Trend Filter
        has_nifty_col = "nifty_above_20sma" in data.columns

        signals: List[Signal] = []

        for i in range(min_required, len(data)):
            row = data.iloc[i]
            vwap_dist = float(row["vwap_dist"])
            rsi_val = float(row["rsi"])
            price = float(row["close"])
            vwap_p = float(row["vwap"])

            if pd.isna(vwap_dist) or pd.isna(rsi_val):
                continue

            nifty_above_20sma_bull = (
                bool(row["nifty_above_20sma"])
                if has_nifty_col
                else bool(df.attrs.get("nifty_above_20sma", False))
            )
            nifty_above_20sma_bear = (
                bool(row["nifty_above_20sma"])
                if has_nifty_col
                else bool(df.attrs.get("nifty_above_20sma", False))
            )

            # Bullish Mean Reversion: Spot < VWAP (-1.5%), RSI < 35, and Nifty 50 above 20 SMA
            if (
                vwap_dist < -self.vwap_dist_threshold
                and rsi_val < self.rsi_oversold
                and nifty_above_20sma_bull is True
            ):
                target_p = round(vwap_p, 2)  # Revert back to VWAP
                stop_p = round(price * 0.985, 2)

                signal = Signal(
                    symbol=symbol,
                    timestamp=row.name,
                    action="BUY",
                    strategy_name=self.name,
                    confidence=0.82,
                    entry_price=price,
                    target_price=target_p,
                    stop_loss=stop_p,
                    metadata={
                        "type": "OPTION",
                        "option_type": "c",
                        "delta_target": 0.50,
                        "strategy": "vwap_rsi_reversion",
                        "rsi": round(rsi_val, 2),
                        "vwap_dist_pct": round(vwap_dist * 100, 2),
                        "vwap": round(vwap_p, 2),
                        "nifty_above_20sma": True,
                    },
                )
                signals.append(signal)

            # Bearish Mean Reversion: Spot > VWAP (+1.5%), RSI > 65, and Nifty 50 below 20 SMA
            elif (
                vwap_dist > self.vwap_dist_threshold
                and rsi_val > self.rsi_overbought
                and nifty_above_20sma_bear is False
            ):
                target_p = round(vwap_p, 2)
                stop_p = round(price * 1.015, 2)

                signal = Signal(
                    symbol=symbol,
                    timestamp=row.name,
                    action="BUY",
                    strategy_name=self.name,
                    confidence=0.82,
                    entry_price=price,
                    target_price=target_p,
                    stop_loss=stop_p,
                    metadata={
                        "type": "OPTION",
                        "option_type": "p",
                        "delta_target": 0.50,
                        "strategy": "vwap_rsi_reversion",
                        "rsi": round(rsi_val, 2),
                        "vwap_dist_pct": round(vwap_dist * 100, 2),
                        "vwap": round(vwap_p, 2),
                        "nifty_above_20sma": False,
                    },
                )
                signals.append(signal)

        return signals
