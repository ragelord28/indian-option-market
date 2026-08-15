"""
D-1 Nightly Scanner (Agent 1).

Scans the FULL_FNO_UNIVERSE (~160+ stocks) using 60 days of daily historical data,
computes 20-day SMA, 50-day SMA, 14-day ADX, 14-day ATR, and 20-day Historical Volatility (HV),
applies Multi-Factor Regime Filters (Bullish Momentum, Bearish Momentum, Volatility Harvest),
ranks candidate setups by conviction, and exports structured JSON and Markdown briefings to `data/watchlists/`.
"""

from datetime import datetime, timedelta
import json

import os
from pathlib import Path
import sys
import numpy as np
import pandas as pd

# Ensure root directory is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scanner.universe import FULL_FNO_UNIVERSE
from src.data.yahoo_provider import YahooFinanceProvider


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate 14-period Average Directional Index (ADX).
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period, min_periods=1).mean()
    plus_di = 100.0 * (pd.Series(plus_dm, index=df.index).rolling(window=period, min_periods=1).mean() / atr.replace(0, np.nan))
    minus_di = 100.0 * (pd.Series(minus_dm, index=df.index).rolling(window=period, min_periods=1).mean() / atr.replace(0, np.nan))

    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / np.where(di_sum == 0, 1.0, di_sum)
    adx = dx.rolling(window=period, min_periods=1).mean()
    return adx.fillna(0.0)


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute 20-SMA, 50-SMA, 14-ATR, 14-ADX, and 20-HV indicators for a stock DataFrame.
    """
    data = df.copy()

    data["sma_20"] = data["close"].rolling(window=20, min_periods=1).mean()
    data["sma_50"] = data["close"].rolling(window=50, min_periods=1).mean()

    # 14-ATR
    tr1 = data["high"] - data["low"]
    tr2 = (data["high"] - data["close"].shift(1)).abs()
    tr3 = (data["low"] - data["close"].shift(1)).abs()
    data["atr_14"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(window=14, min_periods=1).mean()

    # 14-ADX
    data["adx_14"] = calculate_adx(data, period=14)

    # 20-HV (Annualized Volatility)
    log_ret = np.log(data["close"] / data["close"].shift(1))
    data["hv_20"] = log_ret.rolling(window=20, min_periods=1).std() * np.sqrt(252)

    return data


def run_eod_scanner(
    universe: list[str] = FULL_FNO_UNIVERSE,
    output_dir: Path | str = Path("data/watchlists"),
) -> dict:
    """
    Execute D-1 Nightly Scanner across the universe and output JSON & Markdown watchlists.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    provider = YahooFinanceProvider()
    end_dt = datetime.now() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=90)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    candidates = {
        "bullish": [],
        "bearish": [],
        "volatility_harvest": [],
    }

    print(f"Scanning {len(universe)} F&O stocks for D-1 Actionable Watchlist...")

    for symbol in universe:
        try:
            df = provider.fetch_historical_data(
                symbol=symbol, start_date=start_date, end_date=end_date, timeframe="1d"
            )
            if df is None or len(df) < 20:
                continue

            ind_df = calculate_indicators(df)
            row = ind_df.iloc[-1]

            close_p = float(row["close"])
            sma20 = float(row["sma_20"])
            sma50 = float(row["sma_50"])
            adx14 = float(row["adx_14"])
            atr14 = float(row["atr_14"]) if not pd.isna(row["atr_14"]) and row["atr_14"] > 0 else 0.02 * close_p
            hv20 = float(row["hv_20"]) if not pd.isna(row["hv_20"]) else 0.20

            # Regime Filters
            is_bullish = (close_p > sma20 >= sma50) and (adx14 > 22.0)
            is_bearish = (close_p < sma20 <= sma50) and (adx14 > 22.0)
            is_rangebound = (adx14 < 20.0) and (abs(close_p - sma20) / sma20 <= 0.025)

            item = {
                "symbol": symbol,
                "close": round(close_p, 2),
                "sma_20": round(sma20, 2),
                "sma_50": round(sma50, 2),
                "adx_14": round(adx14, 2),
                "atr_14": round(atr14, 2),
                "hv_20": round(hv20 * 100.0, 1),
            }

            if is_bullish:
                item["regime"] = "Bullish Momentum"
                item["suggested_action"] = "BUY CALL"
                item["delta_target"] = 0.65
                item["entry"] = round(close_p, 2)
                item["stop_loss"] = round(max(close_p - 1.5 * atr14, 0.01), 2)
                item["target"] = round(close_p + 2.5 * atr14, 2)
                item["conviction"] = round(adx14, 2)
                candidates["bullish"].append(item)

            elif is_bearish:
                item["regime"] = "Bearish Momentum"
                item["suggested_action"] = "BUY PUT"
                item["delta_target"] = 0.65
                item["entry"] = round(close_p, 2)
                item["stop_loss"] = round(close_p + 1.5 * atr14, 2)
                item["target"] = round(max(close_p - 2.5 * atr14, 0.01), 2)
                item["conviction"] = round(adx14, 2)
                candidates["bearish"].append(item)

            elif is_rangebound:
                item["regime"] = "Volatility Harvest"
                item["suggested_action"] = "SELL STRADDLE/STRANGLE"
                item["delta_target"] = 0.20
                item["entry"] = round(close_p, 2)
                item["stop_loss"] = round(close_p * 1.03, 2)
                item["target"] = round(close_p * 0.97, 2)
                item["conviction"] = round(20.0 - adx14, 2)
                candidates["volatility_harvest"].append(item)

        except Exception as e:
            continue

    # Rank candidate setups by conviction
    candidates["bullish"].sort(key=lambda x: x["conviction"], reverse=True)
    candidates["bearish"].sort(key=lambda x: x["conviction"], reverse=True)
    candidates["volatility_harvest"].sort(key=lambda x: x["conviction"], reverse=True)

    # Select Top 5 for each setup category
    top_bullish = candidates["bullish"][:5]
    top_bearish = candidates["bearish"][:5]
    top_vol = candidates["volatility_harvest"][:5]

    watchlist_data = {
        "timestamp": datetime.now().isoformat(),
        "total_scanned": len(universe),
        "top_bullish": top_bullish,
        "top_bearish": top_bearish,
        "top_volatility_harvest": top_vol,
    }

    # Save JSON file
    json_path = out_path / "watchlist_latest.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(watchlist_data, f, indent=2)

    # Save Markdown file
    md_path = out_path / "watchlist_latest.md"
    md_content = generate_markdown_briefing(watchlist_data)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"Scanner Complete! Saved watchlist to {json_path} and {md_path}")
    return watchlist_data


def generate_markdown_briefing(data: dict) -> str:
    """
    Format scan results into a clean Markdown briefing file.
    """
    ts = data.get("timestamp", datetime.now().isoformat())
    lines = [
        "# D-1 Actionable Nightly Watchlist Briefing",
        f"**Generated**: {ts} | **Total Stocks Scanned**: {data.get('total_scanned', 0)}\n",
        "---",
        "## 🚀 Top Bullish Momentum Setups (Delta ~0.65 Call)",
        "| Symbol | Close (₹) | ADX | ATR (₹) | HV (%) | Entry (₹) | Stop Loss (₹) | Target (₹) |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for item in data.get("top_bullish", []):
        lines.append(
            f"| **{item['symbol']}** | ₹{item['close']:,.2f} | {item['adx_14']} | ₹{item['atr_14']} | "
            f"{item['hv_20']}% | ₹{item['entry']:,.2f} | ₹{item['stop_loss']:,.2f} | ₹{item['target']:,.2f} |"
        )

    lines.extend([
        "\n## 🔻 Top Bearish Momentum Setups (Delta ~0.65 Put)",
        "| Symbol | Close (₹) | ADX | ATR (₹) | HV (%) | Entry (₹) | Stop Loss (₹) | Target (₹) |",
        "|---|---|---|---|---|---|---|---|",
    ])

    for item in data.get("top_bearish", []):
        lines.append(
            f"| **{item['symbol']}** | ₹{item['close']:,.2f} | {item['adx_14']} | ₹{item['atr_14']} | "
            f"{item['hv_20']}% | ₹{item['entry']:,.2f} | ₹{item['stop_loss']:,.2f} | ₹{item['target']:,.2f} |"
        )

    lines.extend([
        "\n## ⚡ Top Volatility Harvest Setups (Delta ~0.20 Short Premium)",
        "| Symbol | Close (₹) | ADX | ATR (₹) | HV (%) | Entry (₹) | Stop Loss (₹) | Target (₹) |",
        "|---|---|---|---|---|---|---|---|",
    ])

    for item in data.get("top_volatility_harvest", []):
        lines.append(
            f"| **{item['symbol']}** | ₹{item['close']:,.2f} | {item['adx_14']} | ₹{item['atr_14']} | "
            f"{item['hv_20']}% | ₹{item['entry']:,.2f} | ₹{item['stop_loss']:,.2f} | ₹{item['target']:,.2f} |"
        )

    lines.append("\n---\n*End of D-1 Watchlist Briefing*")
    return "\n".join(lines)


if __name__ == "__main__":
    run_eod_scanner()
