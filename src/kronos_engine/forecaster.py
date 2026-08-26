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


def fetch_ohlcv(symbol: str, timeframe: str = "15m", lookback: int = 512) -> pd.DataFrame:
    """
    Fetch historical OHLCV candles for a symbol.
    Uses yfinance as the primary source (Upstox token is frequently offline).
    Returns a DataFrame with columns: open, high, low, close, volume
    """
    import yfinance as yf

    ticker_sym = symbol if symbol.endswith(".NS") or "^" in symbol else f"{symbol}.NS"
    params = TF_MAP.get(timeframe, TF_MAP["1d"])

    df = yf.download(ticker_sym, period=params["period"], interval=params["interval"], progress=False)

    if df is None or df.empty:
        raise ValueError(f"Unable to fetch {lookback} historical candles for {ticker_sym}. Verify if the scrip has sufficient trading history.")

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]

    # Ensure required columns
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            raise ValueError(f"Missing column '{col}' in downloaded data")

    if "volume" not in df.columns:
        df["volume"] = 0.0

    # Take last `lookback` candles
    if len(df) > lookback:
        df = df.iloc[-lookback:]

    df = df.reset_index()

    # Normalise the timestamp column name
    ts_col = None
    for candidate in ["Datetime", "datetime", "Date", "date", "index"]:
        if candidate in df.columns:
            ts_col = candidate
            break
    if ts_col is None:
        ts_col = df.columns[0]

    df = df.rename(columns={ts_col: "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    return df


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
    timeframe: str = "15m",
    lookback: int = 512,
    device: str = "cpu",
) -> Dict[str, Any]:
    """
    End-to-end forecast pipeline:
    1. Fetch OHLCV data
    2. Load Kronos model
    3. Generate forecast
    4. Return historical + forecast data for charting

    Returns dict with keys:
        symbol, timeframe, historical_df, forecast_df, pred_len, error
    """
    result = {
        "symbol": symbol,
        "timeframe": timeframe,
        "historical_df": None,
        "forecast_df": None,
        "pred_len": 0,
        "error": None,
    }

    # 1. Fetch data
    try:
        df = fetch_ohlcv(symbol, timeframe, lookback)
    except Exception as e:
        result["error"] = f"Data fetch failed: {e}"
        return result

    if len(df) < 30:
        result["error"] = f"Insufficient data: only {len(df)} candles available (need ≥30)"
        return result

    result["historical_df"] = df

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

    # Generate future timestamps
    if len(df) >= 2:
        freq_delta = df["timestamp"].iloc[-1] - df["timestamp"].iloc[-2]
    else:
        freq_delta = timedelta(minutes=15)

    last_ts = df["timestamp"].iloc[-1]
    future_timestamps = pd.Series([last_ts + freq_delta * (i + 1) for i in range(pred_len)])

    # 4. Run inference
    try:
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=future_timestamps,
            pred_len=pred_len,
            T=1.0,
            top_p=0.9,
            sample_count=1,
            verbose=False,
        )
        result["forecast_df"] = pred_df
    except Exception as e:
        result["error"] = f"Inference failed: {e}"

    return result


def build_kronos_chart(result: Dict[str, Any]):
    """
    Build a Plotly figure showing historical OHLC + Kronos forecast overlay.
    Returns a plotly Figure object.
    """
    import plotly.graph_objects as go

    hist_df = result["historical_df"]
    pred_df = result["forecast_df"]
    symbol = result["symbol"]
    tf = result["timeframe"]

    fig = go.Figure()

    # Historical candlestick
    fig.add_trace(go.Candlestick(
        x=hist_df["timestamp"],
        open=hist_df["open"],
        high=hist_df["high"],
        low=hist_df["low"],
        close=hist_df["close"],
        name="Historical",
        increasing_line_color="#00c087",
        decreasing_line_color="#ff3b69",
    ))

    if pred_df is not None and not pred_df.empty:
        # Connect forecast to last historical point
        last_hist_ts = hist_df["timestamp"].iloc[-1]
        last_hist_close = float(hist_df["close"].iloc[-1])

        forecast_ts = list(pred_df.index)
        forecast_close = list(pred_df["close"].values)
        forecast_high = list(pred_df["high"].values)
        forecast_low = list(pred_df["low"].values)

        # Forecast candlestick
        fig.add_trace(go.Candlestick(
            x=forecast_ts,
            open=list(pred_df["open"].values),
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
        template="plotly_dark",
        hovermode="x unified",
        dragmode="pan",
        xaxis_rangeslider_visible=True,
        height=600,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    return fig
