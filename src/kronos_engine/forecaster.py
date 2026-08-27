"""
Kronos Forecaster — Wrapper for NeoQuasar/Kronos-base financial candlestick AI.

Handles:
1. Historical OHLCV data fetching (yfinance fallback for Upstox offline).
2. KronosPredictor initialisation & HuggingFace model download.
3. Forecast generation and Plotly chart rendering.
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

import pandas as pd
import numpy as np

# Ensure kronos_engine model package is importable
KRONOS_ROOT = Path(__file__).resolve().parent
if str(KRONOS_ROOT) not in sys.path:
    sys.path.insert(0, str(KRONOS_ROOT))

# Timeframe → yfinance parameter mapping
TF_MAP = {
    "15m": {"period": "5d", "interval": "15m"},
    "1h":  {"period": "1mo", "interval": "1h"},
    "1d":  {"period": "2y", "interval": "1d"},
}

# Prediction horizon per timeframe
PRED_LEN_MAP = {
    "15m": 16,   # 4 hours ahead
    "1h":  24,   # 24 hours ahead
    "1d":  30,   # 30 days ahead
}


def fetch_ohlcv(symbol: str, timeframe: str = "30m", lookback: int = 512, exchange: str = "NSE") -> pd.DataFrame:
    """
    Fetch historical OHLCV candles for a symbol.
    Uses a hybrid approach: Upstox API for 30m/1h intraday, and yfinance for 1d.
    Returns a DataFrame with columns: timestamp, open, high, low, close, volume
    """
    import datetime
    import json
    import requests
    import yfinance as yf

    if timeframe in ["30m", "1h"]:
        # 1. Locate Upstox Token
        try:
            with open("data/cache/upstox_token.json", "r") as f:
                token_data = json.load(f)
                access_token = token_data.get("access_token")
        except:
            raise ValueError("Upstox token not found in data/cache/upstox_token.json")
            
        # 2. Locate Instrument Key
        try:
            with open("data/cache/equity_master.json", "r") as f:
                equity_master = json.load(f)
            
            instrument_key = None
            for key, val in equity_master.items():
                if val.get("symbol") == symbol and val.get("exchange") == exchange:
                    instrument_key = val.get("instrument_key")
                    break
            if not instrument_key:
                if symbol in equity_master:
                    instrument_key = equity_master[symbol].get("instrument_key")
        except:
            raise ValueError("Failed to load data/cache/equity_master.json")
            
        if not instrument_key:
            raise ValueError(f"Instrument key not found for {symbol} on {exchange}")
            
        # 3. Hybrid Fetch Logic
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        
        all_data = []
        end_dt = datetime.datetime.now()
        
        interval = "30minute"
        chunks = 6 if timeframe == "1h" else 3
            
        try:
            for _ in range(chunks):
                to_d = end_dt.strftime('%Y-%m-%d')
                start_dt = end_dt - datetime.timedelta(days=30)
                from_d = start_dt.strftime('%Y-%m-%d')
                
                url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/{interval}/{to_d}/{from_d}"
                res = requests.get(url, headers=headers)
                if res.status_code == 200:
                    data = res.json().get("data", {}).get("candles", [])
                    all_data.extend(data)
                else:
                    if not all_data:
                        raise ValueError(f"Upstox API failed: {res.status_code} - {res.text}")
                    break
                end_dt = start_dt
                
            if not all_data:
                raise ValueError(f"Unable to fetch historical candles from Upstox for {symbol}.")
                
            df = pd.DataFrame(all_data, columns=["timestamp", "open", "high", "low", "close", "volume", "OI"])
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
            df.set_index("timestamp", inplace=True)
            df = df.sort_index()
            
            if timeframe == "1h":
                df = df.resample("1h", offset="15min").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum"
                }).dropna()
            
            df = df.reset_index()
        except Exception as e:
            # Fallback to yfinance if Upstox fails (e.g. invalid token, expired)
            print(f"Upstox fetch failed: {e}. Falling back to yfinance.")
            if exchange == "BSE":
                ticker_sym = f"{symbol}.BO"
            else:
                ticker_sym = f"{symbol}.NS"
                
            if symbol.endswith(".NS") or symbol.endswith(".BO") or "^" in symbol:
                ticker_sym = symbol
    
            params = TF_MAP.get(timeframe, TF_MAP["1d"])
    
            end_dt = datetime.datetime.now()
            # For intraday yfinance, restrict lookback to avoid API errors
            lookback_days = 60 if timeframe == "30m" else 730
            start_dt = end_dt - datetime.timedelta(days=lookback_days)
    
            ticker = yf.Ticker(ticker_sym)
            df = ticker.history(start=start_dt.strftime('%Y-%m-%d'), end=end_dt.strftime('%Y-%m-%d'), interval=params["interval"])
    
            if df is None or df.empty:
                raise ValueError(f"Unable to fetch historical candles for {ticker_sym} via yfinance fallback.")
    
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0].lower() for c in df.columns]
            else:
                df.columns = [c.lower() for c in df.columns]
    
            df.columns = [str(col).lower() for col in df.columns]
    
            for col in ["open", "high", "low", "close"]:
                if col not in df.columns:
                    raise ValueError(f"Missing column '{col}' in downloaded data")
    
            if "volume" not in df.columns:
                df["volume"] = 0.0
    
            df = df.reset_index()
    
            ts_col = None
            for candidate in ["Datetime", "datetime", "Date", "date", "index"]:
                if candidate in df.columns:
                    ts_col = candidate
                    break
            if ts_col is None:
                ts_col = df.columns[0]
    
            df = df.rename(columns={ts_col: "timestamp"})
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
            
    else:
        # yfinance logic for 1d
        if exchange == "BSE":
            ticker_sym = f"{symbol}.BO"
        else:
            ticker_sym = f"{symbol}.NS"
            
        if symbol.endswith(".NS") or symbol.endswith(".BO") or "^" in symbol:
            ticker_sym = symbol

        params = TF_MAP.get(timeframe, TF_MAP["1d"])

        end_dt = datetime.datetime.now()
        start_dt = end_dt - datetime.timedelta(days=850)

        ticker = yf.Ticker(ticker_sym)
        df = ticker.history(start=start_dt.strftime('%Y-%m-%d'), end=end_dt.strftime('%Y-%m-%d'), interval=params["interval"])

        if df is None or df.empty:
            raise ValueError(f"Unable to fetch {lookback} historical candles for {ticker_sym}. Verify if the scrip has sufficient trading history.")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]

        df.columns = [str(col).lower() for col in df.columns]

        for col in ["open", "high", "low", "close"]:
            if col not in df.columns:
                raise ValueError(f"Missing column '{col}' in downloaded data")

        if "volume" not in df.columns:
            df["volume"] = 0.0

        df = df.reset_index()

        ts_col = None
        for candidate in ["Datetime", "datetime", "Date", "date", "index"]:
            if candidate in df.columns:
                ts_col = candidate
                break
        if ts_col is None:
            ts_col = df.columns[0]

        df = df.rename(columns={ts_col: "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        
    # Strip timezones and lowercase columns
    if not df.empty and getattr(df.index, 'tz', None) is not None:
        df.index = df.index.tz_localize(None)
    elif "timestamp" in df.columns and hasattr(df["timestamp"].dt, "tz") and df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df.columns = [str(c).lower() for c in df.columns]

    # Soft-cap at 600 candles. Newly listed stocks with <600 will safely return all they have.
    return df.tail(600)

def load_kronos_predictor(device: str = "cpu"):
    """
    Load Kronos-base model and tokenizer from HuggingFace Hub.
    Returns a KronosPredictor instance.
    """
    from model import Kronos, KronosTokenizer, KronosPredictor

    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    model = Kronos.from_pretrained("NeoQuasar/Kronos-base")
    predictor = KronosPredictor(model, tokenizer, device=device, max_context=512)
    return predictor


def run_kronos_forecast(
    symbol: str,
    timeframe: str = "30m",
    device: str = "cpu",
    lookback: int = 512,
    pred_len: int = None,
    exchange: str = "NSE"
) -> Dict[str, Any]:
    """
    End-to-end forecast pipeline:
    1. Fetch OHLCV data
    2. Load Kronos model
    3. Generate forecast
    4. Return historical + forecast data for charting

    Returns dict with keys:
        df, forecast, signal, pct_change, last_close, forecast_close, symbol, timeframe, pred_len, error, exchange
    """
    result = {
        "df": None,
        "forecast": None,
        "signal": None,
        "pct_change": 0.0,
        "last_close": 0.0,
        "forecast_close": 0.0,
        "symbol": symbol,
        "exchange": exchange,
        "timeframe": timeframe,
        "pred_len": 0,
        "error": None,
    }

    # 1. Fetch data
    try:
        df = fetch_ohlcv(symbol, timeframe, lookback=lookback, exchange=exchange)
    except Exception as e:
        result["error"] = f"Data fetch failed: {e}"
        return result

    if len(df) < 30:
        result["error"] = f"Insufficient data: only {len(df)} candles available (need ≥30)"
        return result

    result["df"] = df

    # 2. Load model
    try:
        predictor = load_kronos_predictor(device=device)
    except Exception as e:
        result["error"] = f"Model load failed: {e}"
        return result

    # 3. Prepare inputs
    pred_len = PRED_LEN_MAP.get(timeframe, 16)
    result["pred_len"] = pred_len

    x_df = df[["open", "high", "low", "close", "volume"]].copy()
    x_timestamp = df["timestamp"].copy()

    # Generate market-session-aware future timestamps.
    # Naive linear generation (last_ts + delta * i) breaks intraday charts because it
    # produces bars at 15:45, 16:15 etc — outside market hours — which are then hidden
    # by Plotly rangebreaks, making the forecast completely invisible.
    if len(df) >= 2:
        freq_delta = df["timestamp"].iloc[-1] - df["timestamp"].iloc[-2]
    else:
        freq_delta = timedelta(minutes=30)

    last_ts = df["timestamp"].iloc[-1]

    def _next_market_timestamps(last: pd.Timestamp, delta: timedelta, n: int, tf: str) -> pd.Series:
        """Generate n future timestamps that fall within NSE market session (09:15–15:30)."""
        import pandas as pd
        from datetime import time as dtime
        MARKET_OPEN  = dtime(9, 15)
        MARKET_CLOSE = dtime(15, 30)

        if tf == "1d":
            # For daily, just advance by calendar days (skipping weekends)
            result = []
            cur = last
            while len(result) < n:
                cur = cur + delta
                if cur.weekday() < 5:  # Mon–Fri
                    result.append(cur)
            return pd.Series(result)

        # Intraday: advance bar-by-bar, skipping non-session times
        result = []
        cur = last
        while len(result) < n:
            cur = cur + delta
            # Skip weekends
            if cur.weekday() >= 5:
                # Jump to next Monday 09:15
                days_ahead = 7 - cur.weekday()  # Saturday→2, Sunday→1
                cur = (cur + pd.Timedelta(days=days_ahead)).replace(
                    hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0, microsecond=0
                )
            # If we've gone past market close, jump to next trading day open
            elif cur.time() > MARKET_CLOSE:
                next_day = cur + pd.Timedelta(days=1)
                while next_day.weekday() >= 5:
                    next_day += pd.Timedelta(days=1)
                cur = next_day.replace(
                    hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0, microsecond=0
                )
            # If before market open, snap to market open same day
            elif cur.time() < MARKET_OPEN:
                cur = cur.replace(
                    hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0, microsecond=0
                )
            result.append(cur)
        return pd.Series(result)

    future_timestamps = _next_market_timestamps(last_ts, freq_delta, pred_len, timeframe)

    # 4. Run inference
    try:
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=future_timestamps,
            pred_len=pred_len,
            T=0.7,
            top_p=0.85,
            sample_count=1,
            verbose=False,
        )
        
        # Strip timezone from forecast index/timestamp just in case
        if "timestamp" in pred_df.columns:
            pred_df["timestamp"] = pd.to_datetime(pred_df["timestamp"]).dt.tz_localize(None)
        elif hasattr(pred_df.index, "tz_localize"):
            pred_df.index = pred_df.index.tz_localize(None)

        if not pred_df.empty and not df.empty:
            # === Last-Value Anchoring ===
            # Fixes massive gap-downs caused by global standard-scaling in the foundation model
            # by vertically shifting the entire forecast trajectory to begin at the last true close.
            last_close = float(df["close"].iloc[-1])
            first_pred_close = float(pred_df["close"].iloc[0])
            anchor_delta = last_close - first_pred_close
            
            for col in ["open", "high", "low", "close"]:
                if col in pred_df.columns:
                    pred_df[col] = pred_df[col] + anchor_delta

            # Recalculate metrics based on anchored forecast
            forecast_close = float(pred_df["close"].iloc[-1])
            pct_change = ((forecast_close - last_close) / last_close) * 100
            
            if pct_change > 0.5:
                signal = "BULLISH"
            elif pct_change < -0.5:
                signal = "BEARISH"
            else:
                signal = "NEUTRAL"
        else:
            last_close = 0.0
            forecast_close = 0.0
            pct_change = 0.0
            signal = "NEUTRAL"
            
        result.update({
            "forecast": pred_df,
            "signal": signal,
            "pct_change": pct_change,
            "last_close": last_close,
            "forecast_close": forecast_close
        })
    except Exception as e:
        result["error"] = f"Inference failed: {e}"

    return {
        "df": result.get("df"),                 # This fixes KeyError: 'df'
        "forecast": result.get("forecast"),     # This fixes the missing trajectory
        "signal": result.get("signal", "NEUTRAL"),
        "pct_change": result.get("pct_change", 0.0),
        "last_close": result.get("last_close", 0.0),
        "forecast_close": result.get("forecast_close", 0.0),
        "symbol": result.get("symbol"),
        "timeframe": result.get("timeframe"),
        "exchange": result.get("exchange"),
        "pred_len": result.get("pred_len", 0),
        "error": result.get("error")
    }


def build_kronos_chart(df: pd.DataFrame, forecast_df: pd.DataFrame, symbol: str, tf: str):
    """
    Build a Plotly figure showing historical OHLC + Kronos forecast overlay.
    Returns a plotly Figure object.
    """
    import plotly.graph_objects as go

    fig = go.Figure()

    # Historical candlestick
    fig.add_trace(go.Candlestick(
        x=df.index if df.index.name == "timestamp" else df["timestamp"],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name="Historical",
        increasing_line_color="#00c087",
        decreasing_line_color="#ff3b69",
    ))

    if forecast_df is not None and not forecast_df.empty:
        # Connect forecast to last historical point
        last_hist_ts = df.index[-1] if df.index.name == "timestamp" else df["timestamp"].iloc[-1]
        last_hist_close = float(df["close"].iloc[-1])

        forecast_ts = list(forecast_df.index) if forecast_df.index.name == "timestamp" else list(forecast_df["timestamp"]) if "timestamp" in forecast_df.columns else list(forecast_df.index)
        forecast_close = list(forecast_df["close"].values)
        forecast_high = list(forecast_df["high"].values)
        forecast_low = list(forecast_df["low"].values)

        # Forecast candlestick
        fig.add_trace(go.Candlestick(
            x=forecast_ts,
            open=list(forecast_df['open'].values),
            high=forecast_high,
            low=forecast_low,
            close=forecast_close,
            name="Kronos Forecast",
            increasing_line_color="#00c087",
            decreasing_line_color="#ff3b69",
            opacity=0.6,
        ))

        # Forecast close line (dotted)
        fig.add_trace(go.Scatter(
            x=[last_hist_ts] + forecast_ts,
            y=[last_hist_close] + forecast_close,
            mode="lines",
            name="Forecast Trajectory",
            line=dict(color="#ffffff", width=2, dash="dot"),
        ))

        # Confidence band
        fig.add_trace(go.Scatter(
            x=forecast_ts + forecast_ts[::-1],
            y=forecast_high + forecast_low[::-1],
            fill="toself",
            fillcolor="rgba(255, 255, 255, 0.1)",
            line=dict(color="rgba(255, 255, 255, 0)"),
            name="Forecast Range (H/L)",
            showlegend=True,
        ))

    fig.update_layout(
        title=f"🔮 Kronos Forecast — {symbol} ({tf})",
        xaxis_title="Time",
        yaxis_title="Price (₹)",
        template="plotly_white",
        hovermode="x unified",
        dragmode="pan",
        xaxis_rangeslider_visible=False,
        height=600,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    if tf in ["30m", "1h"]:
        rangebreaks = [
            dict(bounds=["sat", "mon"]),
            dict(bounds=[15.5, 9.25], pattern="hour")
        ]
        
        # Calculate missing holidays safely over the short intraday period
        import pandas as pd
        if df is not None and not df.empty:
            ts_series = df.index if df.index.name == "timestamp" else df["timestamp"]
            all_days = pd.date_range(start=ts_series.min().date(), end=ts_series.max().date())
            trading_days = pd.to_datetime(ts_series.dt.date).unique()
            missing_holidays = all_days.difference(trading_days).strftime('%Y-%m-%d').tolist()
            if missing_holidays:
                rangebreaks.append(dict(values=missing_holidays))
    else:
        rangebreaks = [dict(bounds=["sat", "mon"])]

    fig.update_xaxes(rangebreaks=rangebreaks)

    # === Auto-zoom to recent context + forecast ===
    # Show last N historical candles + forecast so the forecast is clearly visible.
    # User can still pan/zoom out to see all 600 candles of history.
    ZOOM_LOOKBACK = {"30m": 90, "1h": 120, "1d": 140}
    zoom_n = ZOOM_LOOKBACK.get(tf, 60)

    if df is not None and not df.empty:
        ts_series = df.index if df.index.name == "timestamp" else df["timestamp"]
        zoom_start = ts_series.iloc[-min(zoom_n, len(ts_series))]
        # Extend x-axis end to include the full forecast window
        if forecast_df is not None and not forecast_df.empty:
            forecast_ts_all = list(forecast_df.index) if "timestamp" not in forecast_df.columns else list(forecast_df["timestamp"])
            zoom_end = forecast_ts_all[-1] if forecast_ts_all else ts_series.iloc[-1]
        else:
            zoom_end = ts_series.iloc[-1]
        fig.update_xaxes(range=[zoom_start, zoom_end])

    return fig

