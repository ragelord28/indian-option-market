"""
Live Active Trade Monitor & Alert Engine (5-Minute Cycle).

Monitors open positions in `data/paper/active_positions.json`, fetches live quotes
via batch API calls, evaluates risk alerts (Trailing SL, 13:30 Time Stop, 15:10 Square-Off,
Target Hit, SL Hit), and updates position metrics.
"""

from datetime import datetime, time
import json
import logging
from pathlib import Path
from typing import Dict, Any, List
import pytz

from src.data.upstox_provider import fetch_live_quotes_batch

logger = logging.getLogger(__name__)

DEFAULT_ACTIVE_POS_FILE = Path("data/paper/active_positions.json")
DEFAULT_ACTIVE_TRADES_FILE = Path("data/paper/active_trades.json")


def monitor_active_trades(
    active_file: Path | str = DEFAULT_ACTIVE_POS_FILE,
    quotes_override: Dict[str, Dict[str, float]] | None = None,
    now_dt_override: datetime | None = None,
) -> List[Dict[str, Any]]:
    """
    Monitor active paper positions, update current spot/ltp, and evaluate risk alerts.

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

    # Fetch quotes batch in 1 single call
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
        quote = quotes.get(sym, {})
        live_quote_price = quote.get("ltp", 0.0)

        entry_prem = float(pos.get("entry_premium", 0.0))
        entry_spot = float(pos.get("entry_spot", pos.get("strike", 2500.0)))

        # Differentiate underlying spot price vs option contract premium
        if live_quote_price > 200.0:
            current_spot = live_quote_price
            current_ltp = float(pos.get("current_ltp", entry_prem))
        else:
            current_ltp = live_quote_price if live_quote_price > 0 else float(pos.get("current_ltp", entry_prem))
            current_spot = float(pos.get("current_spot", entry_spot))

        pos["current_ltp"] = current_ltp
        pos["current_spot"] = current_spot

        lots = int(pos.get("quantity_lots", 1))
        lot_sz = int(pos.get("lot_size", 250))
        units = lots * lot_sz

        pnl_rupees = round((current_ltp - entry_prem) * units, 2)
        pos["unrealized_pnl"] = pnl_rupees

        pnl_pct = ((current_ltp - entry_prem) / entry_prem * 100.0) if entry_prem > 0 else 0.0

        alert_msg = None
        action_type = None

        target_spot = float(pos.get("target_spot", 0.0))
        sl_spot = float(pos.get("sl_spot", 0.0))
        target_prem = float(pos.get("target", 0.0))
        sl_prem = float(pos.get("stop_loss", 0.0))

        # 1. Target Reached Check
        if (target_spot > 0 and current_spot >= target_spot and target_spot > entry_spot) or (target_prem > 0 and current_ltp >= target_prem and target_prem > entry_prem):
            alert_msg = "🎯 TARGET HIT: Target spot reached. Book profit on broker!"
            action_type = "TARGET_HIT"

        # 2. Stop Loss Hit Check
        elif (sl_spot > 0 and current_spot > 0 and current_spot <= sl_spot and sl_spot < entry_spot) or (sl_prem > 0 and current_ltp > 0 and current_ltp <= sl_prem and sl_prem < entry_prem):
            alert_msg = "❌ STOP LOSS HIT: Spot breached SL level. Exit on broker immediately."
            action_type = "SL_HIT"

        # 3. Trailing SL Trigger (+1.0x ATR gain or +1.5% spot move)
        elif (current_spot >= entry_spot * 1.015 or pnl_pct >= 15.0) and not pos.get("trailing_sl_active", False):
            alert_msg = f"🚨 MOVE SL TO ENTRY: Price reached +1.0x ATR (₹{current_spot:,.2f}). Shift broker SL to ₹{entry_spot:,.2f}."
            action_type = "TRAILING_SL"
            pos["trailing_sl_active"] = True

        # 4. 15:10 PM Mandatory Square-Off
        elif current_time >= time_1510:
            alert_msg = "🛑 15:10 SQUARE OFF: Market closing in 20 mins. Exit immediately to avoid broker auto-square-off penalty."
            action_type = "EOD_EXIT"

        # 5. 13:30 Time Stop Check (-3% to +3% stagnant trade after 13:30)
        elif current_time >= time_1330 and -3.0 <= pnl_pct <= 3.0:
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
                    "action_alert": alert_msg,
                    "action_type": action_type,
                    "current_ltp": current_spot,
                    "unrealized_pnl": pnl_rupees,
                }
            )

    # Save updated metrics back to active positions files
    try:
        with open(DEFAULT_ACTIVE_POS_FILE, "w", encoding="utf-8") as f:
            json.dump(positions, f, indent=2)
        with open(DEFAULT_ACTIVE_TRADES_FILE, "w", encoding="utf-8") as f:
            json.dump(positions, f, indent=2)
    except Exception as err:
        logger.error(f"Error persisting updated positions: {err}")

    return alerts
