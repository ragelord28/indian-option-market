"""
D-1 Nightly Scanner (Agent 1) — Institutional Quant & Risk Upgrade (Phase 11.5).

Scans FULL_FNO_UNIVERSE (~160+ stocks) using 60 days of daily historical data,
computes 20-EMA, 50-EMA, 14-ADX, 14-RSI, 12-ROC, 14-ATR, and 20-HV indicators,
applies Multi-Factor Institutional Regime Filters with Dynamic Conviction Scoring (0-100),
enforces a strict `conviction_score >= 80` qualification threshold up to max 15 candidates,
computes Volatility Risk Premium (VRP), and provides 09:15 AM Gap Veto checking.
"""

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
from typing import Tuple, Dict, Any
import numpy as np
import pandas as pd

# Ensure root directory is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scanner.universe import FULL_FNO_UNIVERSE
from src.data.yahoo_provider import YahooFinanceProvider
from src.data.option_analytics import calculate_vrp


def check_morning_gap_veto(
    open_price: float, prev_close: float, atr_14: float
) -> Tuple[bool, str]:
    """
    Check if 09:15 AM opening gap breaches 1.5x ATR volatility limit.

    Args:
        open_price: Today's 09:15 AM opening spot price.
        prev_close: Previous trading day closing spot price.
        atr_14: 14-period Average True Range.

    Returns:
        Tuple of (is_vetoed: bool, reason_message: str).
    """
    if atr_14 <= 0:
        return (False, "PASS: ATR unavailable")

    gap = abs(open_price - prev_close)
    max_allowed_gap = 1.5 * atr_14

    if gap > max_allowed_gap:
        return (
            True,
            f"VETO: Gap ({gap:.2f}) > 1.5x ATR ({max_allowed_gap:.2f}) — Entry Exhausted",
        )
    return (
        False,
        f"PASS: Gap ({gap:.2f}) within normal volatility limits (Max: {max_allowed_gap:.2f})",
    )


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate 14-period Average Directional Index (ADX)."""
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
    plus_di = 100.0 * (
        pd.Series(plus_dm, index=df.index).rolling(window=period, min_periods=1).mean()
        / atr.replace(0, np.nan)
    )
    minus_di = 100.0 * (
        pd.Series(minus_dm, index=df.index).rolling(window=period, min_periods=1).mean()
        / atr.replace(0, np.nan)
    )

    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / np.where(di_sum == 0, 1.0, di_sum)
    adx = dx.rolling(window=period, min_periods=1).mean()
    return adx.fillna(0.0)


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate 14-period Relative Strength Index (RSI)."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period, min_periods=1).mean()
    avg_loss = loss.rolling(window=period, min_periods=1).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute 20-EMA, 50-EMA, 14-ATR, 14-ADX, 14-RSI, 12-ROC, and 20-HV indicators.
    """
    data = df.copy()

    data["ema_20"] = data["close"].ewm(span=20, adjust=False).mean()
    data["ema_50"] = data["close"].ewm(span=50, adjust=False).mean()

    # 14-ATR
    tr1 = data["high"] - data["low"]
    tr2 = (data["high"] - data["close"].shift(1)).abs()
    tr3 = (data["low"] - data["close"].shift(1)).abs()
    data["atr_14"] = (
        pd.concat([tr1, tr2, tr3], axis=1)
        .max(axis=1)
        .rolling(window=14, min_periods=1)
        .mean()
    )

    # 14-ADX
    data["adx_14"] = calculate_adx(data, period=14)

    # 14-RSI
    data["rsi_14"] = calculate_rsi(data["close"], period=14)

    # 12-ROC
    data["roc_12"] = (
        (data["close"] - data["close"].shift(12)) / data["close"].shift(12).replace(0, np.nan)
    ) * 100.0
    data["roc_12"] = data["roc_12"].fillna(0.0)

    # 20-HV (Annualized Volatility)
    log_ret = np.log(data["close"] / data["close"].shift(1))
    data["hv_20"] = log_ret.rolling(window=20, min_periods=1).std() * np.sqrt(252)

    return data


def run_eod_scanner(
    universe: list[str] = FULL_FNO_UNIVERSE,
    output_dir: Path | str = Path("data/watchlists"),
    min_conviction_score: float = 80.0,
    max_total_candidates: int = 15,
) -> dict:
    """
    Execute D-1 Nightly Scanner across the universe and output JSON & Markdown watchlists.
    Enforces dynamic watchlist sizing (conviction_score >= 80 up to max 15 stocks).
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    provider = YahooFinanceProvider()
    end_dt = datetime.now() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=90)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    all_qualifying = []

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
            ema20 = float(row["ema_20"])
            ema50 = float(row["ema_50"])
            adx14 = float(row["adx_14"])
            rsi14 = float(row["rsi_14"])
            roc12 = float(row["roc_12"])
            atr14 = (
                float(row["atr_14"])
                if not pd.isna(row["atr_14"]) and row["atr_14"] > 0
                else 0.02 * close_p
            )
            hv20 = float(row["hv_20"]) if not pd.isna(row["hv_20"]) else 0.20

            # Calculate estimated IV & VRP
            est_iv = hv20 * 1.15
            vrp_val = calculate_vrp(est_iv, hv20)

            # Conviction Scoring (0 - 100 Scale)
            score = 0.0

            is_bullish = (close_p > ema20 >= ema50) and (adx14 > 20.0)
            is_bearish = (close_p < ema20 <= ema50) and (adx14 > 20.0)
            is_rangebound = (adx14 < 20.0) and (abs(close_p - ema20) / ema20 <= 0.025)

            if is_bullish:
                regime = "Bullish Momentum"
                action = "BUY CALL"
                delta_target = 0.65
                entry = round(close_p, 2)
                stop_loss = round(max(close_p - 1.5 * atr14, 0.01), 2)
                target = round(close_p + 2.5 * atr14, 2)

                score += 25.0 if close_p > ema20 else 0.0
                score += 25.0 if ema20 > ema50 else 0.0
                score += min(25.0, (adx14 / 40.0) * 25.0)
                score += 15.0 if rsi14 > 50.0 else 0.0
                score += 10.0 if roc12 > 0.0 else 0.0

            elif is_bearish:
                regime = "Bearish Momentum"
                action = "BUY PUT"
                delta_target = 0.65
                entry = round(close_p, 2)
                stop_loss = round(close_p + 1.5 * atr14, 2)
                target = round(max(close_p - 2.5 * atr14, 0.01), 2)

                score += 25.0 if close_p < ema20 else 0.0
                score += 25.0 if ema20 < ema50 else 0.0
                score += min(25.0, (adx14 / 40.0) * 25.0)
                score += 15.0 if rsi14 < 50.0 else 0.0
                score += 10.0 if roc12 < 0.0 else 0.0

            elif is_rangebound:
                regime = "Volatility Harvest"
                action = "SELL STRADDLE/STRANGLE"
                delta_target = 0.20
                entry = round(close_p, 2)
                stop_loss = round(close_p * 1.03, 2)
                target = round(close_p * 0.97, 2)

                score += 30.0 if adx14 < 20.0 else 0.0
                score += 30.0 if abs(close_p - ema20) / ema20 <= 0.02 else 0.0
                score += 20.0 if 40.0 <= rsi14 <= 60.0 else 0.0
                score += 20.0 if vrp_val > 0 else 0.0
            else:
                continue

            conviction_score = round(min(100.0, score), 1)

            if conviction_score >= min_conviction_score:
                all_qualifying.append(
                    {
                        "symbol": symbol,
                        "close": round(close_p, 2),
                        "ema_20": round(ema20, 2),
                        "ema_50": round(ema50, 2),
                        "adx_14": round(adx14, 1),
                        "rsi_14": round(rsi14, 1),
                        "roc_12": round(roc12, 1),
                        "atr_14": round(atr14, 2),
                        "hv_20": round(hv20 * 100.0, 1),
                        "vrp": round(vrp_val * 100.0, 1),
                        "regime": regime,
                        "suggested_action": action,
                        "delta_target": delta_target,
                        "entry": entry,
                        "stop_loss": stop_loss,
                        "target": target,
                        "conviction_score": conviction_score,
                    }
                )

        except Exception:
            continue

    # Sort all qualifying candidates by conviction_score descending
    all_qualifying.sort(key=lambda x: x["conviction_score"], reverse=True)
    top_candidates = all_qualifying[:max_total_candidates]

    top_bullish = [c for c in top_candidates if c["regime"] == "Bullish Momentum"]
    top_bearish = [c for c in top_candidates if c["regime"] == "Bearish Momentum"]
    top_vol = [c for c in top_candidates if c["regime"] == "Volatility Harvest"]

    watchlist_data = {
        "timestamp": datetime.now().isoformat(),
        "total_scanned": len(universe),
        "qualifying_count": len(top_candidates),
        "min_conviction_threshold": min_conviction_score,
        "top_bullish": top_bullish,
        "top_bearish": top_bearish,
        "top_volatility_harvest": top_vol,
    }

    today_str = datetime.now().strftime("%Y-%m-%d")

    # Save JSON files
    json_path = out_path / "watchlist_latest.json"
    archive_json_path = out_path / f"watchlist_{today_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(watchlist_data, f, indent=2)
    with open(archive_json_path, "w", encoding="utf-8") as f:
        json.dump(watchlist_data, f, indent=2)

    # Save Markdown files
    md_path = out_path / "watchlist_latest.md"
    archive_md_path = out_path / f"watchlist_{today_str}.md"
    md_content = generate_markdown_briefing(watchlist_data)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    with open(archive_md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(
        f"Scanner Complete! Qualified {len(top_candidates)}/{len(universe)} stocks with conviction >= {min_conviction_score}."
    )
    return watchlist_data


def generate_markdown_briefing(data: dict) -> str:
    """Format scan results into a clean Markdown briefing file."""
    ts = data.get("timestamp", datetime.now().isoformat())
    q_count = data.get("qualifying_count", 0)
    lines = [
        "# D-1 Actionable Nightly Watchlist Briefing",
        f"**Generated**: {ts} | **Scanned**: {data.get('total_scanned', 0)} | **Qualifying Setups**: {q_count} (Conviction >= 80)\n",
        "---",
        "## 🚀 Top Bullish Momentum Setups (Delta ~0.65 Call)",
        "| Symbol | Close (₹) | Conviction | ADX | RSI | VRP (%) | Entry (₹) | Stop Loss (₹) | Target (₹) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for item in data.get("top_bullish", []):
        lines.append(
            f"| **{item['symbol']}** | ₹{item['close']:,.2f} | **{item['conviction_score']}** | {item['adx_14']} | "
            f"{item['rsi_14']} | {item['vrp']}% | ₹{item['entry']:,.2f} | ₹{item['stop_loss']:,.2f} | ₹{item['target']:,.2f} |"
        )

    lines.extend(
        [
            "\n## 🔻 Top Bearish Momentum Setups (Delta ~0.65 Put)",
            "| Symbol | Close (₹) | Conviction | ADX | RSI | VRP (%) | Entry (₹) | Stop Loss (₹) | Target (₹) |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )

    for item in data.get("top_bearish", []):
        lines.append(
            f"| **{item['symbol']}** | ₹{item['close']:,.2f} | **{item['conviction_score']}** | {item['adx_14']} | "
            f"{item['rsi_14']} | {item['vrp']}% | ₹{item['entry']:,.2f} | ₹{item['stop_loss']:,.2f} | ₹{item['target']:,.2f} |"
        )

    lines.extend(
        [
            "\n## ⚡ Top Volatility Harvest Setups (Delta ~0.20 Short Premium)",
            "| Symbol | Close (₹) | Conviction | ADX | RSI | VRP (%) | Entry (₹) | Stop Loss (₹) | Target (₹) |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )

    for item in data.get("top_volatility_harvest", []):
        lines.append(
            f"| **{item['symbol']}** | ₹{item['close']:,.2f} | **{item['conviction_score']}** | {item['adx_14']} | "
            f"{item['rsi_14']} | {item['vrp']}% | ₹{item['entry']:,.2f} | ₹{item['stop_loss']:,.2f} | ₹{item['target']:,.2f} |"
        )

    lines.append("\n---\n*End of D-1 Watchlist Briefing*")
    return "\n".join(lines)


if __name__ == "__main__":
    run_eod_scanner()
