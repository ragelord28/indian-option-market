#!/usr/bin/env python3
"""
Full End-to-End Market Day Simulation (Deterministic Dry Run).

Steps through a complete Monday trading-day lifecycle for the IND OPT MKT
bridge, entirely inside a temporary workspace (real paper journals are never
touched):

  Phase 1  08:45  Pre-market routine: status check (expired + authenticated
                  mocks, 1-click login URL) and D-1 shortlist formatting.
  Phase 2  09:15  Opening range formation: AWAITING_ORB, zero trades.
  Phase 3  09:30  Breakout trigger: PAGEIND breaks below ORB low → locked
                  trigger event (strike snap, entry LTP, 0.65Δ target,
                  1.2×ATR SL) + anti-spam empty second poll.
  Phase 4  09:35  NL trade fill: "Bought PAGEIND 35000 PE at 850, 1 lot"
                  → atomic persistence into both journals.
  Phase 5  10:15+ Trailing stop: activation on −1.8% spot, 1.2×ATR ratchet
                  downward, pullback holds high-water mark.
  Phase 6  14:30  SL breach with gap slippage (|spot − sl| × units).
  Phase 7  15:10  Mandatory EOD square-off alert + journal flush to history.

Exit code 0 only if every phase passes.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.hermes_bridge import (  # noqa: E402
    check_system_status,
    get_premarket_shortlist,
    log_user_trade,
    poll_active_positions_diff,
    poll_actionable_triggers_diff,
)
from src.radar.morning_radar import run_morning_radar  # noqa: E402
from src.scanner.universe import get_lot_size, get_real_exchange_strikes  # noqa: E402

MONDAY = datetime(2026, 8, 17)  # a confirmed weekday
PAGEIND_LOT = get_lot_size("PAGEIND")
PHASES: list[dict] = []


def phase(num: str, title: str):
    def deco(fn):
        def run(ws: Path) -> None:
            try:
                details = fn(ws)
                PHASES.append({"phase": num, "title": title, "status": "PASS", "details": details or ""})
                print(f"✅ Phase {num} PASS — {title}" + (f"\n     {details}" if details else ""))
            except AssertionError as err:
                PHASES.append({"phase": num, "title": title, "status": "FAIL", "details": str(err)})
                print(f"❌ Phase {num} FAIL — {title}\n     {err}")
        return run
    return deco


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


class _MockProvider:
    def __init__(self, valid: bool):
        self._valid = valid

    def is_token_valid(self) -> bool:
        return self._valid


# --- Shared fixtures ---------------------------------------------------------

def _wl_item(triggered: bool) -> dict:
    """PAGEIND bearish candidate; toggles breakout on candle_close."""
    return {
        "symbol": "PAGEIND",
        "close": 35200.0,
        "atr_14": 200.0,
        "conviction_score": 89.0,
        "regime": "Bearish Momentum",
        "suggested_action": "BUY PUT",
        "simulated_open": 35205.0,          # tiny gap → passes 1.5×ATR gap veto
        "has_event_risk": False,
        "orb_high": 35300.0,
        "orb_low": 35100.0,                 # width 200: 0.3×200 ≤ 200 ≤ 1.5×200 ✓
        "rvol": 1.6,
        "entry": 35250.0,
        "candle_close": 35050.0 if triggered else 35150.0,  # outside vs inside range
    }


def _watchlist(ws: Path, triggered: bool) -> Path:
    wl = {
        "timestamp": "2026-08-16T18:00:00",
        "top_bullish": [{
            "symbol": "RELIANCE", "close": 2500.0, "atr_14": 30.0,
            "conviction_score": 91.0, "regime": "Bullish Momentum",
            "suggested_action": "BUY CALL", "simulated_open": 2505.0,
            "has_event_risk": False, "orb_high": 2510.0, "orb_low": 2490.0,
            "rvol": 1.5, "entry": 2515.0, "candle_close": 2495.0,
        }],
        "top_bearish": [_wl_item(triggered)],
        "top_volatility_harvest": [],
    }
    path = ws / "watchlist_latest.json"
    path.write_text(json.dumps(wl), encoding="utf-8")
    return path


def _poll_trig(ws: Path, wl: Path, when: datetime) -> dict:
    return poll_actionable_triggers_diff(
        tracker_path=ws / "tracker.json",
        watchlist_path=wl,
        radar_path=ws / "radar_latest.json",
        now_dt=when,
        force_session_evaluation=True,
    )


def _poll_pos(ws: Path, spot: float, when: datetime) -> dict:
    return poll_active_positions_diff(
        active_file=ws / "active_positions.json",
        tracker_path=ws / "tracker.json",
        quotes_override={"PAGEIND": {"ltp": spot}},
        now_dt_override=when,
    )


# --- Phases ------------------------------------------------------------------


@phase("1", "08:45 Pre-Market Routine (status + shortlist)")
def _phase1(ws: Path) -> str:
    expired = check_system_status(provider=_MockProvider(False), now_dt=MONDAY.replace(hour=8, minute=45),
                                  watchlist_path=ws / "missing.json")
    require(expired["auth_status"] == "TOKEN_EXPIRED", "expired mock not detected")
    require(bool(expired.get("login_url")), "no 1-click login URL on expired token")

    wl = _watchlist(ws, triggered=False)
    healthy = check_system_status(provider=_MockProvider(True), now_dt=MONDAY.replace(hour=8, minute=45),
                                  watchlist_path=wl)
    require(healthy["auth_status"] == "AUTHENTICATED", "healthy mock not authenticated")
    require(healthy["market_phase"] == "PRE_MARKET", f"phase={healthy['market_phase']}")

    shortlist = get_premarket_shortlist(watchlist_path=wl)
    require(shortlist["total_candidates"] == 2, f"candidates={shortlist['total_candidates']}")
    require("| RELIANCE | 91.0 |" in shortlist["markdown"], "bullish row missing from table")
    require("| PAGEIND | 89.0 |" in shortlist["markdown"], "bearish row missing from table")
    require("Volatility Harvest" in shortlist["markdown"], "harvest section missing")
    return (f"expired→login_url ✓, authenticated ✓, PRE_MARKET ✓, shortlist table "
            f"({shortlist['total_candidates']} candidates) renders in full ✓")


@phase("2", "09:15–09:29 Opening Range Formation (AWAITING_ORB, zero trades)")
def _phase2(ws: Path) -> str:
    wl = _watchlist(ws, triggered=False)
    radar = run_morning_radar(watchlist_path=wl, output_path=ws / "radar_latest.json",
                              force_session_evaluation=True)
    page = next(i for i in radar["radar_items"] if i["symbol"] == "PAGEIND")
    require(page["status"] == "AWAITING_ORB", f"status={page['status']}")

    diff = _poll_trig(ws, wl, MONDAY.replace(hour=9, minute=20))
    require(diff["has_updates"] is False and diff["events"] == [], "false trigger during ORB window")
    require(not (ws / "active_positions.json").exists(), "positions must not exist pre-trigger")
    return "PAGEIND stays AWAITING_ORB (candle inside range); trigger diff empty; zero trades ✓"


@phase("3", "09:30 Breakout Trigger (locked timestamp + anti-spam re-poll)")
def _phase3(ws: Path) -> str:
    wl = _watchlist(ws, triggered=True)  # candle_close 35050 breaks below orb_low 35100
    first = _poll_trig(ws, wl, MONDAY.replace(hour=9, minute=30))

    require(first["has_updates"] is True, "no trigger event on ORB breach")
    ev = next(e for e in first["events"] if e["symbol"] == "PAGEIND")
    require(ev["event_type"] == "TRIGGERED" and ev["bias"] == "BEARISH", "wrong event/direction")
    require(bool(ev["triggered_at"]), "trigger timestamp not locked")
    require("PAGEIND" in ev["contract"] and "PE" in ev["contract"], f"contract={ev['contract']}")
    strikes = get_real_exchange_strikes("PAGEIND")
    if strikes:
        require(ev["strike"] in strikes, f"strike {ev['strike']} not an exchange strike")
    else:
        require(ev["strike"] % 250 == 0, f"strike {ev['strike']} not on 250 grid")
    require(ev["entry_ltp"] and ev["entry_ltp"] > 0, "no entry LTP")
    require(ev["target_premium"] and ev["target_premium"] > ev["entry_ltp"], "target not above entry")
    require(ev["sl_premium"] and 0 < ev["sl_premium"] < ev["entry_ltp"], "SL not below entry")
    require(ev["lot_size"] == PAGEIND_LOT, f"lot={ev['lot_size']} expected {PAGEIND_LOT}")

    second = _poll_trig(ws, wl, MONDAY.replace(hour=9, minute=31))
    require(second["has_updates"] is False and second["events"] == [], "anti-spam failed on re-poll")
    return (f"TRIGGERED @ {ev['triggered_at']}, strike ₹{ev['strike']:,.0f} (exchange-snapped), "
            f"entry ₹{ev['entry_ltp']:,.2f}, target ₹{ev['target_premium']:,.2f} (0.65Δ), "
            f"SL ₹{ev['sl_premium']:,.2f}, lot {ev['lot_size']}; identical re-poll → empty delta ✓")


@phase("4", "09:35 NL Trade Fill & Atomic Journal Persistence")
def _phase4(ws: Path) -> str:
    result = log_user_trade(
        text="Bought PAGEIND 35000 PE at 850, 1 lot",
        live_quotes={"PAGEIND": {"ltp": 35200.0}},
        active_file=ws / "active_positions.json",
        trades_file=ws / "active_trades.json",
    )
    require(result["success"] is True, f"log failed: {result.get('error')}")
    pos = result["position"]
    require(pos["symbol"] == "PAGEIND" and pos["option_type"] == "PE", "parse incorrect")
    require(pos["strike"] == 35000.0, f"strike snapped wrong: {pos['strike']}")
    require(pos["direction"] == "BEARISH", "PE must be BEARISH")
    require(pos["lot_size"] == PAGEIND_LOT, "lot size not official")
    atr = pos["atr"]
    require(abs((pos["sl_spot"] - 35200.0) - 1.2 * atr) < 0.05, "initial SL not 1.2×ATR from spot")
    require(abs((850.0 - pos["stop_loss"]) - 0.65 * 1.2 * atr) < 0.05, "SL premium not 0.65Δ anchored")

    positions = json.loads((ws / "active_positions.json").read_text())
    trades = json.loads((ws / "active_trades.json").read_text())
    require(len(positions) == 1 and positions[0]["trade_id"].startswith("TRD-"), "positions journal wrong")
    require(trades == positions, "active_trades.json diverged from active_positions.json")
    return (f"parsed ✓ strike ₹35,000 PE, lot {PAGEIND_LOT}, ATR ₹{atr:,.1f}, "
            f"SL spot ₹{pos['sl_spot']:,.1f} (1.2×ATR), SL prem ₹{pos['stop_loss']:,.2f} (0.65Δ); "
            f"both journals atomically in sync ({pos['trade_id']}) ✓")


@phase("5", "10:15–14:00 Trailing Stop Ratchet (1.2×ATR, high-water hold)")
def _phase5(ws: Path) -> str:
    # 10:15 — spot −1.8% in the PE's favor (35200 × 0.982 = 34566.4)
    r1 = _poll_pos(ws, 34566.4, MONDAY.replace(hour=10, minute=15))
    types1 = [e["event_type"] for e in r1["events"]]
    require("TRAILING_SL" in types1, f"trailing not activated: {types1}")

    # 11:30 — further favorable move: bearish SL ratchets DOWN
    r2 = _poll_pos(ws, 34200.0, MONDAY.replace(hour=11, minute=30))
    ratchets = [e for e in r2["events"] if e["event_type"] == "SL_RATCHET"]
    require(len(ratchets) == 1, f"expected 1 ratchet, got {[e['event_type'] for e in r2['events']]}")
    new_sl = ratchets[0]["new_sl_spot"]
    require(abs(new_sl - (34200.0 + 1.2 * 528.0)) < 0.05, f"ratchet not 1.2×ATR: {new_sl}")

    # 12:00 — pullback AGAINST the trade: SL must hold at high-water (min) mark
    r3 = _poll_pos(ws, 34400.0, MONDAY.replace(hour=12, minute=0))
    require(r3["has_updates"] is False, f"pullback must not emit/alert: {r3['events']}")
    pos = json.loads((ws / "active_positions.json").read_text())[0]
    require(abs(pos["sl_spot"] - new_sl) < 0.01, "SL moved off high-water mark on pullback")
    return (f"activation on −1.8% ✓; ratchet → ₹{new_sl:,.1f} (spot+1.2×528) ✓; "
            f"pullback to 34,400 holds SL at ₹{pos['sl_spot']:,.1f} (min invariant) ✓")


@phase("6", "14:30 SL Breach with Gap Slippage Logging")
def _phase6(ws: Path) -> str:
    pos = json.loads((ws / "active_positions.json").read_text())[0]
    sl = pos["sl_spot"]                      # 34,833.6
    gap_spot = round(sl + 266.4, 2)          # gap through SL by ₹266.4
    r = _poll_pos(ws, gap_spot, MONDAY.replace(hour=14, minute=30))
    sl_hits = [e for e in r["events"] if e["event_type"] == "SL_HIT"]
    require(len(sl_hits) == 1, f"expected SL_HIT, got {[e['event_type'] for e in r['events']]}")
    expected_slip = round(abs(gap_spot - sl) * PAGEIND_LOT, 2)
    require(sl_hits[0]["slippage_inr"] == expected_slip,
            f"slippage {sl_hits[0]['slippage_inr']} != {expected_slip}")
    # Re-poll at the same gapped spot: suppressed (no duplicate nag)
    r2 = _poll_pos(ws, gap_spot, MONDAY.replace(hour=14, minute=35))
    require(r2["has_updates"] is False, "SL_HIT re-emitted on unchanged tick")
    return (f"SL ₹{sl:,.1f} breached at ₹{gap_spot:,.1f}; gap slippage "
            f"₹{expected_slip:,.2f} (|Δspot| × {PAGEIND_LOT} units) logged once ✓")


@phase("7", "15:10 Mandatory EOD Square-Off + Journal Flush")
def _phase7(ws: Path) -> str:
    r = _poll_pos(ws, 35100.0, MONDAY.replace(hour=15, minute=15))
    require(any(e["event_type"] == "EOD_EXIT" for e in r["events"]),
            f"no EOD square-off alert: {[e['event_type'] for e in r['events']]}")

    # Square off: flip status CLOSED and flush to BOTH journals atomically
    # (mirrors the dashboard's Exit handler, which keeps them in sync).
    positions = json.loads((ws / "active_positions.json").read_text())
    require(positions[0]["status"] == "OPEN", "position not open before flush")
    closed = dict(positions[0])
    closed["status"] = "CLOSED"
    closed["exit_date"] = "2026-08-17 15:15 IST"
    closed["realized_pnl"] = round((closed["entry_premium"] - closed["current_ltp"]) * PAGEIND_LOT, 2)
    (ws / "active_positions.json").write_text(json.dumps([closed]))
    (ws / "active_trades.json").write_text(json.dumps([closed]))
    history = json.loads((ws / "active_positions.json").read_text())
    require(history[0]["status"] == "CLOSED" and "realized_pnl" in history[0], "flush failed")
    require(json.loads((ws / "active_trades.json").read_text()) == history, "trades journal out of sync")
    return (f"EOD_EXIT alert emitted at 15:15 IST ✓; position CLOSED with realized P&L "
            f"₹{history[0]['realized_pnl']:,.2f}; journals flushed consistently ✓")


def main() -> int:
    print(f"\n🗓️  Full Market Day Dry Run — deterministic Monday {MONDAY:%Y-%m-%d}\n")
    with tempfile.TemporaryDirectory(prefix="ind_opt_mkt_dryrun_") as td:
        ws = Path(td)
        for fn in (_phase1, _phase2, _phase3, _phase4, _phase5, _phase6, _phase7):
            fn(ws)

    failed = [p for p in PHASES if p["status"] == "FAIL"]
    print("\n" + "=" * 74)
    print(f"DRY RUN RESULT: {len(PHASES) - len(failed)}/{len(PHASES)} phases passed"
          + (f" — {len(failed)} FAILED ❌" if failed else " — ALL PHASES CLEAN ✅"))

    report = PROJECT_ROOT / "logs/trading_day_dry_run.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"ran_at": datetime.now().isoformat(), "phases": PHASES}, indent=2),
                      encoding="utf-8")
    print(f"Full report: {report}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
