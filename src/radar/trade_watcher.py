"""
Live Active Trade Monitor & Alert Engine (5-Minute Cycle).

Monitors open positions in `data/paper/active_positions.json`, fetches live quotes
via batch API calls, evaluates risk alerts with correct priority ordering:
  1. EOD_EXIT (15:10 PM mandatory square-off)
  2. SL_HIT (stop loss breached)
  3. TARGET_HIT (target reached)
  4. TRAILING_SL (+1.0x ATR trailing stop)
  5. TIME_STOP (13:30 PM stagnant trade)

Supports both BULLISH and BEARISH trade directions.
Uses atomic JSON writes to prevent file corruption.
"""

from datetime import datetime, time
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List
import pytz

from src.data.upstox_provider import fetch_live_quotes_batch

logger = logging.getLogger(__name__)

DEFAULT_ACTIVE_POS_FILE = Path("data/paper/active_positions.json")
DEFAULT_ACTIVE_TRADES_FILE = Path("data/paper/active_trades.json")


def _atomic_json_write(filepath: Path, data: Any) -> None:
    """Write JSON data atomically via temp file + os.replace()."""
    tmp_path = filepath.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(str(tmp_path), str(filepath))


def monitor_active_trades(
    active_file: Path | str = DEFAULT_ACTIVE_POS_FILE,
    quotes_override: Dict[str, Dict[str, float]] | None = None,
    now_dt_override: datetime | None = None,
) -> List[Dict[str, Any]]:
    """
    Monitor active paper positions, update current spot/ltp, and evaluate risk alerts.

    Alert priority order (highest to lowest):
      1. EOD_EXIT — 15:10 PM mandatory square-off
      2. SL_HIT — stop loss breached
      3. TARGET_HIT — target price reached
      4. TRAILING_SL — +1.0x ATR trailing stop trigger
      5. TIME_STOP — 13:30 PM stagnant trade exit

    Supports both BULLISH and BEARISH trade directions.

    Args:
        active_file: Path to active positions JSON.
        quotes_override: Optional dict of quotes for testing without API calls.
        now_dt_override: Optional datetime for testing time-based alerts.

    Returns:
        List of active alert dictionaries for trades requiring immediate action.
    """
    pos_path = Path(active_file)
    if not pos_path.exists() or pos_path.stat().st_size == 0:
        # Fallback check for active_trades.json
        alt_path = DEFAULT_ACTIVE_TRADES_FILE
        if alt_path.exists() and alt_path.stat().st_size > 0:
            pos_path = alt_path
        else:
            return []

    try:
        with open(pos_path, "r", encoding="utf-8") as f:
            positions = json.load(f)
    except Exception as err:
        logger.error(f"Error loading active positions from {pos_path}: {err}")
        return []

    open_positions = [p for p in positions if p.get("status") == "OPEN"]
    if not open_positions:
        return []

    # Get unique symbols
    symbols = list({p["symbol"] for p in open_positions if "symbol" in p})
    if not symbols:
        return []

    # Fetch equity quotes batch in 1 single call
    if quotes_override is not None:
        quotes = quotes_override
    else:
        try:
            quotes = fetch_live_quotes_batch(symbols)
        except Exception as err:
            logger.warning(f"Failed to fetch live quotes batch: {err}")
            quotes = {}

    # Get current IST time
    if now_dt_override is not None:
        now_ist = now_dt_override
    else:
        try:
            ist = pytz.timezone("Asia/Kolkata")
            now_ist = datetime.now(ist)
        except Exception:
            now_ist = datetime.now()

    current_time = now_ist.time()
    time_1330 = time(13, 30)
    time_1510 = time(15, 10)

    alerts = []

    for pos in positions:
        if pos.get("status") != "OPEN":
            continue

        sym = pos.get("symbol", "").upper()
        direction = pos.get("direction", "BULLISH").upper()
        quote = quotes.get(sym, {})

        entry_spot = float(pos.get("entry_spot", pos.get("strike", 0.0)))
        entry_prem = float(pos.get("entry_premium", 0.0))
        target_spot = float(pos.get("target_spot", 0.0))
        sl_spot = float(pos.get("sl_spot", 0.0))

        # Update current_spot directly from equity batch quote
        live_ltp = float(quote.get("ltp", 0.0))
        current_spot = live_ltp if live_ltp > 0 else float(pos.get("current_spot", entry_spot))
        pos["current_spot"] = current_spot

        # Option premium tracking (separate from spot)
        current_ltp = float(pos.get("current_ltp", entry_prem))
        pos["current_ltp"] = current_ltp

        lots = int(pos.get("quantity_lots", 1))
        lot_sz = int(pos.get("lot_size", 250))
        units = lots * lot_sz

        pnl_rupees = round((current_ltp - entry_prem) * units, 2)
        pos["unrealized_pnl"] = pnl_rupees

        # Spot-based P&L percentage for time stop evaluation
        spot_pnl_pct = ((current_spot - entry_spot) / entry_spot * 100.0) if entry_spot > 0 else 0.0
        if direction == "BEARISH":
            spot_pnl_pct = -spot_pnl_pct  # Invert for bearish

        alert_msg = None
        action_type = None

        # Priority 1: 15:10 PM Mandatory EOD Square-Off (highest priority)
        if current_time >= time_1510:
            alert_msg = "🛑 15:10 SQUARE OFF: Market closing in 20 mins. Exit immediately to avoid broker auto-square-off penalty."
            action_type = "EOD_EXIT"

        # Priority 2: Stop Loss Hit
        elif sl_spot > 0 and current_spot > 0:
            if direction == "BULLISH" and current_spot <= sl_spot:
                alert_msg = f"❌ STOP LOSS HIT: Spot ₹{current_spot:,.2f} breached SL ₹{sl_spot:,.2f}. Exit on broker immediately."
                action_type = "SL_HIT"
            elif direction == "BEARISH" and current_spot >= sl_spot:
                alert_msg = f"❌ STOP LOSS HIT: Spot ₹{current_spot:,.2f} breached SL ₹{sl_spot:,.2f}. Exit on broker immediately."
                action_type = "SL_HIT"

        # Priority 3: Target Reached
        if alert_msg is None and target_spot > 0 and current_spot > 0:
            if direction == "BULLISH" and current_spot >= target_spot:
                alert_msg = "🎯 TARGET HIT: Target spot reached. Book profit on broker!"
                action_type = "TARGET_HIT"
            elif direction == "BEARISH" and current_spot <= target_spot:
                alert_msg = "🎯 TARGET HIT: Target spot reached. Book profit on broker!"
                action_type = "TARGET_HIT"

        # Priority 4: Trailing SL Trigger (+1.0x ATR / +1.5% spot move)
        if alert_msg is None and not pos.get("trailing_sl_active", False):
            if direction == "BULLISH" and current_spot >= entry_spot * 1.015:
                alert_msg = f"🚨 MOVE SL TO ENTRY: Price reached +1.0x ATR (₹{current_spot:,.2f}). Shift broker SL to ₹{entry_spot:,.2f}."
                action_type = "TRAILING_SL"
                pos["trailing_sl_active"] = True
            elif direction == "BEARISH" and current_spot <= entry_spot * 0.985:
                alert_msg = f"🚨 MOVE SL TO ENTRY: Price reached +1.0x ATR (₹{current_spot:,.2f}). Shift broker SL to ₹{entry_spot:,.2f}."
                action_type = "TRAILING_SL"
                pos["trailing_sl_active"] = True

        # Priority 5: 13:30 Time Stop (-3% to +3% stagnant trade)
        if alert_msg is None and current_time >= time_1330 and -3.0 <= spot_pnl_pct <= 3.0:
            alert_msg = "⏰ 13:30 TIME STOP: Trade stagnant for 4 hours. Exit on broker to avoid theta decay."
            action_type = "TIME_STOP"

        if alert_msg:
            pos["action_alert"] = alert_msg
            pos["action_type"] = action_type
            alerts.append(
                {
                    "trade_id": pos.get("trade_id", "TRD-000"),
                    "symbol": sym,
                    "strategy": pos.get("strategy", "Option Strategy"),
                    "direction": direction,
                    "action_alert": alert_msg,
                    "action_type": action_type,
                    "current_spot": current_spot,
                    "current_ltp": current_ltp,
                    "unrealized_pnl": pnl_rupees,
                }
            )

    # Atomic JSON writes to prevent file corruption
    try:
        _atomic_json_write(DEFAULT_ACTIVE_POS_FILE, positions)
        _atomic_json_write(DEFAULT_ACTIVE_TRADES_FILE, positions)
    except Exception as err:
        logger.error(f"Error persisting updated positions: {err}")

    return alerts
