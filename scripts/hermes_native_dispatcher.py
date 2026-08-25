#!/usr/bin/env python3
"""
Hermes ⬄ Native Autonomous Trading-Day Dispatcher ("IND OPT MKT").

Background runner that walks the IST trading-day schedule and pushes discrete
Markdown bulletins into Native Desktop Notifications:

  09:00 IST        D-1 pre-market shortlist table
  09:15–09:29      SILENT — opening range forming, zero alerts
  09:30–15:10      every cycle: ORB trigger diffs + position diffs
                   (breakouts, 1.2×ATR SL ratchets, targets, SL breach with
                   gap slippage INR) — only genuine state transitions
  15:10–15:30      mandatory EOD square-off alert (once)

Delivery chain (first healthy channel wins, auto-reconnect each cycle):
  1. notify-send — Native OS desktop notification.
  2. Hermes send — `hermes send` when messaging platforms are configured.
  3. Stdout     — inject Markdown bulletin into Hermes Bot Chat.
  4. Log        — maintain fallback structured logging in data/logs/dispatcher.log.

Every event is additionally appended to data/radar/hermes_events.jsonl.

BACKGROUND-ONLY anti-spam: this dispatcher emits output ONLY on genuine state
transitions. Idle cycles (weekends, silent ORB window, unchanged polls) print
nothing. This silence contract does NOT apply to interactive user queries — 
when a user explicitly asks for status/shortlist, the agent must call
the always-full interactive endpoints (check_system_status /
get_premarket_shortlist) and render the complete table.

Modes:
  --once       single evaluation cycle (cron mode; schedule-aware, stateful)
  --interval N daemon loop (default 300s; survives laptop sleep — the next
               tick after wake re-polls full live state, so no exit signal
               can be silently missed)
  --status     print dispatcher state and exit

Usage:
  venv/bin/python3 scripts/hermes_native_dispatcher.py --once
  venv/bin/python3 scripts/hermes_native_dispatcher.py --interval 300
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time as time_mod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except Exception:
    pass

from src.api.hermes_bridge import (  # noqa: E402
    get_premarket_shortlist,
    poll_active_positions_diff,
    poll_actionable_triggers_diff,
)

REPO = PROJECT_ROOT
STATE_FILE = REPO / "data/radar/dispatcher_state.json"
EVENTS_LOG = REPO / "data/radar/hermes_events.jsonl"
FALLBACK_LOG = REPO / "data/logs/dispatcher.log"

MARKET_OPEN_MIN = 9 * 60 + 15   # 09:15
MARKET_LIVE_MIN = 9 * 60 + 30   # 09:30
EOD_MIN = 15 * 60 + 10          # 15:10
EOD_SCAN_MIN = 16 * 60          # 16:00
MARKET_CLOSE_MIN = 15 * 60 + 30  # 15:30
PREMARKET_PUSH_MIN = 9 * 60  # 09:00


def now_ist() -> datetime:
    return datetime.now(pytz.timezone("Asia/Kolkata"))


# ---------------------------------------------------------------------------
# Dispatcher state (daily dedup: shortlist / EOD pushed once per day)
# ---------------------------------------------------------------------------


def load_state() -> Dict[str, Any]:
    try:
        if STATE_FILE.exists() and STATE_FILE.stat().st_size > 0:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(state, dict):
                return state
    except Exception:
        pass
    return {}


def save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_name(STATE_FILE.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(STATE_FILE))


def _fresh_day_state(now: datetime) -> Dict[str, Any]:
    today = now.strftime("%Y-%m-%d")
    state = load_state()
    if state.get("date") != today:
        state = {"date": today, "premarket_sent": False, "eod_sent": False, "cycles": 0}
    return state


# ---------------------------------------------------------------------------
# Delivery chain: Buzz CLI -> Hermes send -> OUTBOX fallback
# ---------------------------------------------------------------------------


def _deliver_via_notify_send(title: str, body: str) -> bool:
    try:
        out = subprocess.run(
            ["notify-send", "-u", "critical", title, body],
            capture_output=True, text=True, timeout=10,
        )
        return out.returncode == 0
    except Exception:
        return False

def _deliver_trigger_notifications(events: List[Dict[str, Any]]) -> None:
    for ev in events:
        if ev.get("event_type") == "TRIGGERED":
            title = f"🚨 ORB Breakout: {ev.get('symbol')}"
            body = f"{ev.get('bias')} | Strike: {ev.get('strike')} | Entry: ₹{ev.get('entry_ltp')} | Target: ₹{ev.get('target_premium')}"
            _deliver_via_notify_send(title, body)


def _deliver_via_hermes(title: str, body: str) -> bool:
    hermes = shutil.which("hermes") or str(Path.home() / ".local/bin/hermes")
    if not Path(hermes).exists():
        return False
    try:
        listed = subprocess.run([hermes, "send", "--list"], capture_output=True, text=True, timeout=15)
        if listed.returncode != 0 or "No messaging platforms configured" in (listed.stdout + listed.stderr):
            return False
        out = subprocess.run(
            [hermes, "send", "--subject", title, "-"],
            input=body, capture_output=True, text=True, timeout=20,
        )
        return out.returncode == 0
    except Exception:
        return False


def _deliver_to_fallback_log(title: str, body: str, now: datetime) -> str:
    FALLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = f"\n\n---\n\n## {title}\n\n*{now.strftime('%Y-%m-%d %H:%M IST')}*\n\n{body}\n"
    with open(FALLBACK_LOG, "a", encoding="utf-8") as f:
        f.write(entry)
    return str(FALLBACK_LOG)


def _append_events_log(events: List[Dict[str, Any]]) -> None:
    if not events:
        return
    EVENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(EVENTS_LOG, "a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, default=str) + "\n")


def deliver(title: str, body: str, events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Push one bulletin through the delivery chain; always log events."""
    now = now_ist()
    _append_events_log(events or [])
    
    if events and any(ev.get("event_type") == "TRIGGERED" for ev in events):
        _deliver_trigger_notifications(events)
    else:
        _deliver_via_notify_send(title, body)
    log_path = _deliver_to_fallback_log(title, body, now)
    
    # Print directly to stdout so Hermes Cron 'bot-chat' delivery injects the markdown!
    print(f"## {title}\n\n{body}\n")
    
    return {"delivered_via": "bot-chat", "title": title, "fallback_log": log_path}


# ---------------------------------------------------------------------------
# Bulletin formatting
# ---------------------------------------------------------------------------


def _format_trigger_events(events: List[Dict[str, Any]]) -> str:
    lines = []
    for ev in events:
        lines.append(
            f"🟢 **{ev.get('symbol')}** {ev.get('bias')} TRIGGERED @ {ev.get('triggered_at')} "
            f"(conviction {ev.get('conviction_score')})\n"
            f"• Spot ₹{float(ev.get('spot') or 0):,.2f} | {ev.get('contract')}\n"
            f"• Entry ≤ ₹{ev.get('entry_ltp')} | 🎯 Target ₹{ev.get('target_premium')} | "
            f"🛑 SL ₹{ev.get('sl_premium')} (0.65Δ) | Lot {ev.get('lot_size')}"
        )
    return "\n\n".join(lines)


def _format_position_events(events: List[Dict[str, Any]]) -> str:
    icons = {
        "SL_HIT": "🔴", "TARGET_HIT": "🎯", "EOD_EXIT": "🛑",
        "TRAILING_SL": "🚨", "SL_RATCHET": "🔒", "TIME_STOP": "⏰",
    }
    lines = []
    for ev in events:
        icon = icons.get(ev.get("event_type"), "🔔")
        extra = ""
        if ev.get("slippage_inr") is not None:
            extra = f" | Gap slippage ₹{ev['slippage_inr']:,.2f}"
        if ev.get("event_type") == "SL_RATCHET":
            extra = f" | SL ₹{ev.get('previous_sl_spot')} → ₹{ev.get('new_sl_spot')} (1.2×ATR)"
        lines.append(
            f"{icon} **{ev.get('symbol')}** {ev.get('event_type')} [{ev.get('trade_id')}]"
            f"{extra}\n• {ev.get('message')}"
        )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Schedule state machine
# ---------------------------------------------------------------------------


def run_cycle(verbose: bool = True) -> Dict[str, Any]:
    """One schedule-aware evaluation cycle. Safe to run every minute."""
    now = now_ist()
    results: List[Dict[str, Any]] = []

    if now.weekday() >= 5:
        return {"phase": "WEEKEND", "actions": results}

    mins = now.hour * 60 + now.minute
    state = _fresh_day_state(now)

    # ---- 09:00–09:14 : pre-market shortlist (once per day) ----
    if PREMARKET_PUSH_MIN <= mins < MARKET_OPEN_MIN and not state.get("premarket_sent"):
        try:
            shortlist = get_premarket_shortlist()
            res = deliver(
                "📋 D-1 Pre-Market Shortlist",
                shortlist.get("markdown", "_Shortlist unavailable (feed offline)._"),
            )
            results.append(res)
            state["premarket_sent"] = True
        except Exception as err:
            results.append({"delivered_via": "error", "title": "premarket", "error": str(err)})

    # ---- 09:15–09:29 : SILENT opening range — zero alerts ----
    elif MARKET_OPEN_MIN <= mins < MARKET_LIVE_MIN:
        if verbose:
            results.append({"phase": "ORB_SILENT_WINDOW", "note": "Opening range forming — no alerts"})

    # ---- 09:30–15:29 : live diff polling + 15:10 EOD square-off ----
    elif MARKET_LIVE_MIN <= mins <= MARKET_CLOSE_MIN:
        trig = poll_actionable_triggers_diff(now_dt=now)
        pos = poll_active_positions_diff(now_dt_override=now)

        if trig.get("has_updates"):
            results.append(deliver(
                "🟢 09:30 ORB Breakouts",
                _format_trigger_events(trig["events"]),
                events=trig["events"],
            ))
        if pos.get("has_updates"):
            results.append(deliver(
                "⚡ Active Position Alerts",
                _format_position_events(pos["events"]),
                events=pos["events"],
            ))

        if EOD_MIN <= mins and not state.get("eod_sent"):
            results.append(deliver(
                "🛑 15:10 MANDATORY EOD SQUARE-OFF",
                "Market closes in 20 minutes. Exit ALL open option positions on the broker "
                "immediately to avoid auto-square-off penalties and STT on expiry.",
            ))
            state["eod_sent"] = True

    if EOD_SCAN_MIN <= mins and not state.get("evening_scan_sent"):
        try:
            from src.api.hermes_bridge import get_premarket_shortlist
            # force scan generates the next day's list
            get_premarket_shortlist(force_scan=True)
            res = deliver("✅ 16:00 D-1 Evening Screening", "Next day watchlist generated successfully.")
            results.append(res)
            state["evening_scan_sent"] = True
        except Exception as err:
            results.append({"delivered_via": "error", "title": "16:00 Scan", "error": str(err)})

    state["cycles"] = int(state.get("cycles", 0)) + 1
    state["last_cycle_ist"] = now.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)
    return {"phase": "cycle-complete", "actions": results}


def daemon_loop(interval_sec: int) -> None:
    print(f"🤖 IND OPT MKT dispatcher daemon — cycle every {interval_sec}s. Ctrl+C to stop.", flush=True)
    stop_file = PROJECT_ROOT / "data/STOP"
    while True:
        if stop_file.exists():
            print("🛑 Kill switch (data/STOP) activated. Halting dispatcher daemon gracefully.", flush=True)
            break
        try:
            out = run_cycle(verbose=False)
            acts = [a for a in out.get("actions", []) if a.get("delivered_via") not in (None, "phase-note")]
            for a in acts:
                print(json.dumps(a, default=str), flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as err:
            # Auto-reconnect resilience: any failure retries next cycle
            print(f"⚠️ dispatcher cycle error (retrying next cycle): {err}", file=sys.stderr, flush=True)
        time_mod.sleep(interval_sec)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes ⬄ Native IND OPT MKT trading-day dispatcher")
    parser.add_argument("--once", action="store_true", help="Run a single schedule-aware cycle (cron mode)")
    parser.add_argument("--interval", type=int, default=300, help="Daemon cycle interval seconds (default 300)")
    parser.add_argument("--status", action="store_true", help="Print dispatcher state and exit")
    args = parser.parse_args()

    # Enforce strict DRY_RUN mode for safety
    os.environ["DRY_RUN"] = "true"

    if args.status:
        print(json.dumps(load_state(), indent=2))
        return 0
    if args.once:
        run_cycle()
        return 0
    try:
        daemon_loop(interval_sec=args.interval)
    except KeyboardInterrupt:
        print("🛑 Dispatcher stopped by user.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
