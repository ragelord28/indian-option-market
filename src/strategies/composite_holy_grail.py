"""
Composite "Holy Grail" Strategy with Multi-Timeframe Multi-Factor Confidence Scoring.

Strategy Logic:
- Simulates institutional multi-timeframe matrix (Daily ADX, 15m RSI, 5m VWAP, 15m Volume Surge, OI Surge).
- Triggers BUY setups on VWAP mean-reversion.
- Populates `metadata["composite_factors"]` for dynamic Rule 8 multi-factor confidence scoring:
  - Base Score: 0.50
  - daily_adx_gt_20: +0.10
  - rsi_15m_divergence: +0.15
  - vwap_5m_reversion: +0.15
  - vol_15m_surge: +0.10
  - oi_surge: +0.10
"""

from typing import List
import numpy as np
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Signal


class CompositeHolyGrailStrategy(BaseStrategy):
    """
    Composite Multi-Timeframe "Holy Grail" Options Strategy.

    Evaluates technical indicators across timeframes (ADX, RSI, VWAP, Volume, OI)
    and attaches composite_factors to signals for dynamic Rule 8 confidence aggregation.
    """

    def __init__(
        self,
        rsi_period: int = 14,
        vol_period: int = 20,
        name: str = "CompositeHolyGrailStrategy",
    ):
        """
        Initialize CompositeHolyGrailStrategy.

        Args:
            rsi_period: Lookback window for RSI calculation (default 14).
            vol_period: Lookback window for volume moving average (default 20).
            name: Strategy identifier name.
        """
        super().__init__(name=name)
        self.rsi_period = rsi_period
        self.vol_period = vol_period

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
        Generate multi-factor Composite signals from standard market data DataFrame.

        Args:
            df: Standardized ADR-005 market data DataFrame.

        Returns:
            List of generated Signal objects with composite_factors metadata.
        """
        min_required = max(self.rsi_period + 5, self.vol_period)
        if df is None or df.empty or len(df) < min_required:
            return []

        data = df.copy()
        symbol = str(data["symbol"].iloc[0])

        # 1. 14-period RSI
        data["rsi"] = self._calculate_rsi(data["close"], self.rsi_period)

        # 2. VWAP & distance
        data["tp"] = (data["high"] + data["low"] + data["close"]) / 3.0
        data["tp_vol"] = data["tp"] * data["volume"]
        cum_tp_vol = data["tp_vol"].cumsum()
        cum_vol = data["volume"].cumsum()
        data["vwap"] = np.where(cum_vol > 0, cum_tp_vol / cum_vol, data["close"])
        data["vwap_dist"] = (data["close"] - data["vwap"]) / data["vwap"]

        # 3. Volume SMA & Surge
        data["vol_sma"] = data["volume"].rolling(window=self.vol_period).mean()

        # 4. ADX / Trend Strength Proxy over 14 bars
        data["high_low_diff"] = data["high"] - data["low"]
        data["price_change_14"] = (data["close"] - data["close"].shift(14)).abs()
        data["range_sum_14"] = data["high_low_diff"].rolling(14).sum()
        data["adx_proxy"] = np.where(
            data["range_sum_14"] > 0,
            (data["price_change_14"] / data["range_sum_14"]) * 100.0,
            25.0,
        )

        signals: List[Signal] = []

        for i in range(min_required, len(data)):
            row = data.iloc[i]

            close_p = float(row["close"])
            vwap_p = float(row["vwap"])
            vwap_dist = float(row["vwap_dist"])
            rsi_val = float(row["rsi"])
            vol = float(row["volume"])
            vol_sma = float(row["vol_sma"])
            adx_val = float(row["adx_proxy"])

            if pd.isna(vwap_dist) or pd.isna(rsi_val):
                continue

            # Check factor conditions
            vwap_5m_reversion = vwap_dist < -0.005  # Price below VWAP by > 0.5%
            rsi_extreme = rsi_val < 40.0 or rsi_val > 60.0
            daily_adx_gt_20 = adx_val > 20.0
            vol_15m_surge = (vol_sma > 0) and (vol > 1.5 * vol_sma)

            # Open Interest surge check
            has_oi = "open_interest" in data.columns and not data["open_interest"].isna().all()
            if has_oi and i >= 3:
                oi_start = float(data["open_interest"].iloc[i - 3])
                oi_curr = float(data["open_interest"].iloc[i])
                oi_surge = (oi_curr > 1.03 * oi_start) if (oi_start > 0 and not pd.isna(oi_start) and not pd.isna(oi_curr)) else False
            else:
                oi_surge = bool(df.attrs.get("oi_surge", False))

            # Trigger BUY signal when VWAP mean-reversion is indicated
            if vwap_5m_reversion:
                composite_factors = {
                    "daily_adx_gt_20": bool(daily_adx_gt_20),
                    "rsi_extreme": bool(rsi_extreme),
                    "vwap_5m_reversion": bool(vwap_5m_reversion),
                    "vol_15m_surge": bool(vol_15m_surge),
                    "oi_surge": bool(oi_surge),
                }

                target_p = round(vwap_p, 2) if vwap_p > close_p else round(close_p * 1.03, 2)
                stop_p = round(close_p * 0.98, 2)

                signal = Signal(
                    symbol=symbol,
                    timestamp=row.name,
                    action="BUY",
                    strategy_name=self.name,
                    confidence=0.50,  # Base confidence, dynamically updated by filter_signal_rule_8
                    entry_price=close_p,
                    target_price=target_p,
                    stop_loss=stop_p,
                    metadata={
                        "type": "OPTION",
                        "option_type": "c",
                        "delta_target": 0.50,
                        "composite_factors": composite_factors,
                    },
                )
                signals.append(signal)

        return signals
