#!/usr/bin/env python3
"""
Hermes ⬄ Buzz Autonomous Trading-Day Dispatcher ("IND OPT MKT").

Background runner that walks the IST trading-day schedule and pushes discrete
Markdown bulletins into Buzz Desktop:

  08:45 IST        D-1 pre-market shortlist table
  09:15–09:29      SILENT — opening range forming, zero alerts
  09:30–15:10      every cycle: ORB trigger diffs + position diffs
                   (breakouts, 1.2×ATR SL ratchets, targets, SL breach with
                   gap slippage INR) — only genuine state transitions
  15:10–15:30      mandatory EOD square-off alert (once)

Delivery chain (first healthy channel wins, auto-reconnect each cycle):
  1. Buzz CLI   — `buzz messages send --channel <uuid>` against the local
                  relay (http://localhost:3000), channel auto-discovered.
  2. Hermes send — `hermes send` when messaging platforms are configured.
  3. OUTBOX     — append Markdown bulletin to ~/.buzz/OUTBOX/ (visible in the
                  Buzz desktop workspace) — always-on durable fallback.

Every event is additionally appended to data/radar/hermes_events.jsonl.

BACKGROUND-ONLY anti-spam: this dispatcher emits output ONLY on genuine state
transitions. Idle cycles (weekends, silent ORB window, unchanged polls) print
nothing. This silence contract does NOT apply to interactive user queries in
Buzz — when a user explicitly asks for status/shortlist, the agent must call
the always-full interactive endpoints (check_system_status /
get_premarket_shortlist) and render the complete table.

Modes:
  --once       single evaluation cycle (cron mode; schedule-aware, stateful)
  --interval N daemon loop (default 300s; survives laptop sleep — the next
               tick after wake re-polls full live state, so no exit signal
               can be silently missed)
  --status     print dispatcher state and exit

Usage:
  venv/bin/python3 scripts/hermes_buzz_dispatcher.py --once
  venv/bin/python3 scripts/hermes_buzz_dispatcher.py --interval 300
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

from src.api.hermes_bridge import (  # noqa: E402
    get_premarket_shortlist,
    poll_active_positions_diff,
    poll_actionable_triggers_diff,
)

REPO = PROJECT_ROOT
STATE_FILE = REPO / "data/radar/dispatcher_state.json"
EVENTS_LOG = REPO / "data/radar/hermes_events.jsonl"
BUZZ_OUTBOX = Path.home() / ".buzz/OUTBOX"
BUZZ_CLI_CANDIDATES = ["buzz", str(Path.home() / ".local/bin/buzz")]

MARKET_OPEN_MIN = 9 * 60 + 15   # 09:15
MARKET_LIVE_MIN = 9 * 60 + 30   # 09:30
EOD_MIN = 15 * 60 + 10          # 15:10
MARKET_CLOSE_MIN = 15 * 60 + 30  # 15:30
PREMARKET_PUSH_MIN = 8 * 60 + 45  # 08:45


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


def _buzz_cli() -> Optional[str]:
    for cand in BUZZ_CLI_CANDIDATES:
        path = shutil.which(cand) or (cand if Path(cand).exists() else None)
        if path and Path(path).exists():
            return path
    return None


def _buzz_channel(cli: str) -> Optional[str]:
    """Auto-discover a Buzz channel UUID for message delivery."""
    try:
        out = subprocess.run(
            [cli, "--format", "compact", "channels", "list"],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode == 0 and out.stdout.strip():
            channels = json.loads(out.stdout)
            for ch in channels:
                name = str(ch.get("name", "")).lower()
                if "ind" in name and "opt" in name:
                    return ch.get("channel_id")
            if channels:
                return channels[0].get("channel_id")
    except Exception:
        pass
    return None


def _deliver_via_buzz(title: str, body: str) -> bool:
    cli = _buzz_cli()
    if not cli or not os.environ.get("BUZZ_PRIVATE_KEY"):
        return False
    channel = _buzz_channel(cli)
    if not channel:
        return False
    try:
        out = subprocess.run(
            [cli, "messages", "send", "--channel", channel, "--content", f"**{title}**\n\n{body}"],
            capture_output=True, text=True, timeout=20,
        )
        return out.returncode == 0
    except Exception:
        return False


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


def _deliver_to_outbox(title: str, body: str, now: datetime) -> str:
    BUZZ_OUTBOX.mkdir(parents=True, exist_ok=True)
    path = BUZZ_OUTBOX / f"IND_OPT_MKT_{now.strftime('%Y%m%d')}.md"
    entry = f"\n\n---\n\n## {title}\n\n*{now.strftime('%Y-%m-%d %H:%M IST')}*\n\n{body}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)
    return str(path)


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
    if _deliver_via_buzz(title, body):
        return {"delivered_via": "buzz-relay", "title": title}
    if _deliver_via_hermes(title, body):
        return {"delivered_via": "hermes-send", "title": title}
    outbox_path = _deliver_to_outbox(title, body, now)
    return {"delivered_via": "buzz-outbox", "title": title, "outbox_file": outbox_path}


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

    # ---- 08:45–09:14 : pre-market shortlist (once per day) ----
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

    state["cycles"] = int(state.get("cycles", 0)) + 1
    state["last_cycle_ist"] = now.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)
    return {"phase": "cycle-complete", "actions": results}


def daemon_loop(interval_sec: int) -> None:
    print(f"🤖 IND OPT MKT dispatcher daemon — cycle every {interval_sec}s. Ctrl+C to stop.", flush=True)
    while True:
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
    parser = argparse.ArgumentParser(description="Hermes ⬄ Buzz IND OPT MKT trading-day dispatcher")
    parser.add_argument("--once", action="store_true", help="Run a single schedule-aware cycle (cron mode)")
    parser.add_argument("--interval", type=int, default=300, help="Daemon cycle interval seconds (default 300)")
    parser.add_argument("--status", action="store_true", help="Print dispatcher state and exit")
    args = parser.parse_args()

    if args.status:
        print(json.dumps(load_state(), indent=2))
        return 0
    if args.once:
        out = run_cycle()
        # Hermes cron delivers stdout verbatim (empty stdout = silent), so
        # idle cycles (weekends, silent ORB window, no diffs) print nothing.
        delivered = [a for a in out.get("actions", []) if a.get("delivered_via")]
        if delivered:
            print(json.dumps({"phase": out.get("phase"), "actions": delivered}, indent=2, default=str))
        return 0
    try:
        daemon_loop(interval_sec=args.interval)
    except KeyboardInterrupt:
        print("🛑 Dispatcher stopped by user.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
