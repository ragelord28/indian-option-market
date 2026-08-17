"""
Agent 1.5 Morning Radar — Real-Time Pre-Market Risk & Trigger Engine.

Evaluates shortlisted D-1 watchlist candidates against mandatory Risk Guards:
1. Sector Limit Guard: Max 1 active setup per sector.
2. Event Risk Blackout Guard: Vetoes stocks with earnings/binary events within 48h.
3. 09:15 AM Gap Veto Guard: Vetoes setups breaching 1.5x ATR gap limits.
4. ORB Width Guard: Vetoes setups with overly narrow or exhausted ranges.

Evaluates 09:30 AM ORB Trigger Status using 15m candle close logic,
manages a conviction-based priority queue (max 5 slots),
and builds complete multi-leg execution tickets for all non-vetoed candidates.
"""

from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Dict, Any, List
import pandas as pd

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scanner.universe import get_sector
from src.scanner.eod_scanner import check_morning_gap_veto
from src.data.strategy_builder import build_optimal_strategy


def is_market_session_active(dt: datetime | None = None) -> bool:
    """
    Check if current IST time is within live market hours (Mon-Fri after 09:15 AM IST).
    """
    if dt is None:
        dt = datetime.now()
    if dt.weekday() >= 5:  # Weekend
        return False
    time_min = dt.hour * 60 + dt.minute
    if time_min < 9 * 60 + 15:  # Before 09:15 AM IST
        return False
    return True


def run_morning_radar(
    watchlist_path: Path | str = Path("data/watchlists/watchlist_latest.json"),
    output_path: Path | str = Path("data/radar/radar_latest.json"),
    force_session_evaluation: bool = False,
) -> Dict[str, Any]:
    """
    Execute Morning Radar Guard checks and attach execution tickets.

    Args:
        watchlist_path: Path to latest D-1 watchlist JSON.
        output_path: Path to save output radar JSON.
        force_session_evaluation: If True, evaluate intraday guards regardless of time of day.

    Returns:
        Structured radar output dictionary.
    """
    w_path = Path(watchlist_path)
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    if not w_path.exists():
        empty_res = {
            "timestamp": datetime.now().isoformat(),
            "total_shortlisted": 0,
            "sector_counts": {},
            "radar_items": [],
        }
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(empty_res, f, indent=2)
        return empty_res

    with open(w_path, "r", encoding="utf-8") as f:
        wl_data = json.load(f)

    # Flatten all categories into a single list sorted by conviction_score
    raw_items = []
    for cat in ["top_bullish", "top_bearish", "top_volatility_harvest"]:
        for item in wl_data.get(cat, []):
            item_copy = dict(item)
            if "sector" not in item_copy:
                item_copy["sector"] = get_sector(item_copy["symbol"])
            raw_items.append(item_copy)

    raw_items.sort(key=lambda x: x.get("conviction_score", 80.0), reverse=True)

    sector_counts: Dict[str, int] = {}
    radar_items: List[Dict[str, Any]] = []

    for idx, item in enumerate(raw_items, 1):
        sym = item["symbol"]
        sec = item["sector"]
        close_p = float(item["close"])
        atr14 = float(item.get("atr_14", close_p * 0.02))
        has_event = bool(item.get("has_event_risk", False))
        conv_score = float(item.get("conviction_score", 80.0))

        # Market session active check
        session_active = (
            is_market_session_active()
            or force_session_evaluation
            or ("candle_close" in item)
            or ("simulated_open" in item)
            or ("simulated_triggered" in item)
        )

        veto_reason = None
        status = "AWAITING_ORB"

        if session_active:
            # Guard 1: Sector Limit
            if sector_counts.get(sec, 0) >= 1:
                status = "VETOED_SECTOR_LIMIT"
                veto_reason = f"Sector limit reached (Max 1 setup for {sec})"
            else:
                # Guard 2: Event Risk Blackout
                if has_event:
                    status = "VETOED_EVENT"
                    veto_reason = "Binary corporate event / earnings blackout within 48h"
                else:
                    # Guard 3: 09:15 Opening Gap Check
                    sim_open = item.get("simulated_open", close_p)
                    is_gap_vetoed, gap_msg = check_morning_gap_veto(sim_open, close_p, atr14)
                    if is_gap_vetoed:
                        status = "VETOED_GAP"
                        veto_reason = gap_msg

            if status == "AWAITING_ORB":
                # Guard 4: ORB Width Check
                orb_high = item.get("orb_high", close_p * 1.005)
                orb_low = item.get("orb_low", close_p * 0.995)
                orb_width = orb_high - orb_low
                if orb_width < 0.3 * atr14:
                    status = "VETOED_ORB_CHOP"
                    veto_reason = "Range too narrow / low volume chop"
                elif orb_width > 1.5 * atr14:
                    status = "VETOED_ORB_EXHAUSTED"
                    veto_reason = "Range too wide / entry exhausted"

            if status == "AWAITING_ORB":
                sector_counts[sec] = sector_counts.get(sec, 0) + 1

                # Check 09:30 ORB Trigger (15m Candle Close)
                candle_close = item.get("candle_close", close_p)
                rvol = item.get("rvol", 1.0)

                is_long_trigger = (candle_close > orb_high + (0.001 * close_p)) and (rvol >= 1.3)
                is_short_trigger = (candle_close < orb_low - (0.001 * close_p)) and (rvol >= 1.3)

                if is_long_trigger or is_short_trigger or item.get("simulated_triggered", False):
                    status = "TRIGGERED"

        # Attach Strategy Execution Ticket
        bias = "BULLISH" if "BULL" in item.get("regime", "").upper() else (
            "BEARISH" if "BEAR" in item.get("regime", "").upper() else "RANGEBOUND"
        )
        ivr_val = float(item.get("ivr", 45.0))
        vrp_val = float(item.get("vrp", 5.0))

        ticket = build_optimal_strategy(
            symbol=sym,
            spot_price=close_p,
            bias=bias,
            ivr=ivr_val,
            vrp=vrp_val,
            option_chain_df=pd.DataFrame(),  # Synthetic strike builder
            lot_size=50,
            underlying_target=item.get("target"),
        )

        orb_high_val = item.get("orb_high", close_p * 1.005)
        orb_low_val = item.get("orb_low", close_p * 0.995)
        candle_close_val = item.get("candle_close", close_p)
        orb_reason = f"Spot ₹{candle_close_val:,.2f} inside ORB range ₹{orb_low_val:,.2f} - ₹{orb_high_val:,.2f}"

        radar_items.append(
            {
                "#": idx,
                "symbol": sym,
                "sector": sec,
                "regime": item.get("regime", "Bullish Momentum"),
                "bias": bias,
                "suggested_action": item.get("suggested_action", "BUY CALL"),
                "status": status,
                "veto_reason": veto_reason,
                "orb_reason": orb_reason,
                "close": close_p,
                "entry": item.get("entry", close_p),
                "stop_loss": item.get("stop_loss", round(close_p * 0.98, 2)),
                "target": item.get("target", round(close_p * 1.04, 2)),
                "trigger_zone": f"₹{item.get('entry', close_p):,.2f}",
                "conviction_score": conv_score,
                "vrp": vrp_val,
                "ivr": ivr_val,
                "execution_ticket": ticket,
            }
        )

    # Conviction-Based Priority Queue
    triggered_items = [item for item in radar_items if item["status"] == "TRIGGERED"]
    triggered_items.sort(key=lambda x: x.get("conviction_score", 80.0), reverse=True)
    
    max_slots = 5
    for i, item in enumerate(triggered_items):
        if i >= max_slots:
            item["status"] = "QUEUED_NO_SLOT"
            item["veto_reason"] = "All 5 portfolio slots allocated to higher conviction setups"

    output_data = {
        "timestamp": datetime.now().isoformat(),
        "total_shortlisted": len(raw_items),
        "sector_counts": sector_counts,
        "radar_items": radar_items,
    }

    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    print(f"Morning Radar Complete! Processed {len(radar_items)} candidates into {out_p}.")
    return output_data


def scan_morning_radar(
    watchlist_path: Path | str = Path("data/watchlists/watchlist_latest.json"),
    output_path: Path | str = Path("data/radar/radar_latest.json"),
    data_provider: Any = None,
    input_watchlist: Any = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Main runner function for Morning Radar scans.
    Evaluates Morning Radar guards and ORB triggers, updating data/radar/radar_latest.json.
    """
    w_path = input_watchlist or watchlist_path
    return run_morning_radar(
        watchlist_path=w_path,
        output_path=output_path,
        force_session_evaluation=True,
    )


if __name__ == "__main__":
    run_morning_radar()
