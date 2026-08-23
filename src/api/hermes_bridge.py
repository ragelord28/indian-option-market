"""
Hermes Agent Bridge API — "IND OPT MKT" autonomous trading workflow agent.

Exposes the platform's daily options workflow as deterministic, tool-callable
functions for a Hermes agent (driven via Buzz Desktop), plus a CLI and a
headless daemon:

  CLI:     python -m src.api.hermes_bridge <command> [--json]
  Daemon:  python -m src.api.hermes_bridge daemon --interval 300

Core contract — ANTI-SPAM DIFF POLLING (BACKGROUND HOOKS ONLY):
    The poll functions compare current market state against the persistent
    tracker at `data/radar/alert_state_tracker.json` and return ONLY genuine
    state changes:
      - AWAITING_ORB -> TRIGGERED breakout transitions (locked trigger time)
      - Trailing SL ratcheted to a new price level (1.2x ATR standard)
      - TARGET_HIT / SL_HIT (with gap slippage) / EOD_EXIT square-off
    Unchanged polling ticks return {"has_updates": false, "events": []}.
    The tracker is updated atomically (tmp file + os.replace) so concurrent
    dashboard / daemon writers never corrupt each other.

INTERACTIVE vs BACKGROUND — never suppress a user's explicit ask:
    check_system_status() and get_premarket_shortlist() are INTERACTIVE
    endpoints: they ALWAYS return the complete human-readable payload (auth
    status, market phase, full shortlist tables) regardless of whether
    anything changed since the last poll. Diff suppression applies ONLY to
    the automated background hooks (poll_actionable_triggers_diff /
    poll_active_positions_diff) so the dispatcher stays silent between state
    transitions. When a user in Buzz asks "check status" or "show the
    shortlist", the agent must render the full table from the interactive
    endpoints — an empty diff is never a valid answer to a direct question.

Sleep & recovery: all network access is guarded; after laptop sleep the next
daemon tick re-polls the live state (SL/target/EOD checks are evaluated
against current spot, so no exit signal can be silently missed).
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import json
import logging
import re
import sys
import time as time_mod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

# Ensure project root is on sys.path (repo-root execution for CLI/daemon)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    DEFAULT_ATR_PCT_OF_SPOT,
    DELTA_ANCHOR,
    TARGET_SPOT_PCT,
    TRAILING_STOP_ATR_MULTIPLIER,
)
from src.data.option_analytics import get_monthly_expiry_date, snap_to_strike_grid
from src.radar.morning_radar import is_market_session_active, run_morning_radar
from src.radar.trade_watcher import DEFAULT_ACTIVE_POS_FILE, _atomic_json_write, monitor_active_trades
from src.scanner.universe import LOT_SIZE_MAP, get_lot_size

logger = logging.getLogger(__name__)

# --- Canonical file locations -------------------------------------------------
WATCHLIST_FILE = Path("data/watchlists/watchlist_latest.json")
RADAR_FILE = Path("data/radar/radar_latest.json")
TRACKER_FILE = Path("data/radar/alert_state_tracker.json")
EVENTS_LOG_FILE = Path("data/radar/hermes_events.jsonl")
ACTIVE_TRADES_FILE = Path("data/paper/active_trades.json")

_MARKET_OPEN_MIN = 9 * 60 + 15
_MARKET_LIVE_MIN = 9 * 60 + 30
_EOD_MIN = 15 * 60 + 10
_MARKET_CLOSE_MIN = 15 * 60 + 30


def _now_ist(now_dt: Optional[datetime] = None) -> datetime:
    """Resolve current IST time (or a test override)."""
    if now_dt is not None:
        return now_dt
    try:
        return datetime.now(pytz.timezone("Asia/Kolkata"))
    except Exception:
        return datetime.now()


def _market_phase(now_ist: datetime) -> str:
    """Classify the current IST time into the daily market lifecycle phase."""
    if now_ist.weekday() >= 5:
        return "CLOSED_WEEKEND"
    mins = now_ist.hour * 60 + now_ist.minute
    if mins < _MARKET_OPEN_MIN:
        return "PRE_MARKET"
    if mins < _MARKET_LIVE_MIN:
        return "ORB_SILENT_WINDOW"
    if mins < _EOD_MIN:
        return "LIVE_TRADING"
    if mins <= _MARKET_CLOSE_MIN:
        return "EOD_SQUAREOFF"
    return "POST_MARKET"


def _load_json(path: Path, default: Any) -> Any:
    """Guarded JSON load — corrupted/missing files degrade to the default."""
    try:
        if path.exists() and path.stat().st_size > 0:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as err:
        logger.warning(f"Corrupted JSON at {path} ({err}); using default")
    return default


# ---------------------------------------------------------------------------
# 1. System status
# ---------------------------------------------------------------------------


def check_system_status(
    provider: Any = None,
    now_dt: Optional[datetime] = None,
    watchlist_path: Path = WATCHLIST_FILE,
) -> Dict[str, Any]:
    """
    INTERACTIVE endpoint — validate Upstox auth, market phase, D-1 freshness.

    Always returns the FULL payload (never diff-suppressed): auth status
    (AUTHENTICATED / TOKEN_EXPIRED with 1-click login URL), current IST
    market phase, and whether the D-1 watchlist was generated today. Safe to
    call on every direct user query.
    """
    now_ist = _now_ist(now_dt)

    authenticated = False
    if provider is None:
        try:
            from src.data.upstox_provider import UpstoxProvider
            provider = UpstoxProvider()
        except Exception as err:
            logger.warning(f"Upstox provider init failed: {err}")
            provider = None
    if provider is not None:
        try:
            authenticated = bool(provider.is_token_valid())
        except Exception:
            authenticated = False

    result: Dict[str, Any] = {
        "server_time_ist": now_ist.strftime("%Y-%m-%d %H:%M IST"),
        "auth_status": "AUTHENTICATED" if authenticated else "TOKEN_EXPIRED",
        "authenticated": authenticated,
        "market_phase": _market_phase(now_ist),
        "market_session_active": is_market_session_active(now_ist),
    }

    if not authenticated:
        try:
            from src.data.upstox_auth import get_login_url
            result["login_url"] = get_login_url()
            result["remedy"] = "Token expired. Open the login URL in a browser, complete Upstox OAuth, and re-run status."
        except Exception:
            result["login_url"] = None
            result["remedy"] = "Token expired and login URL could not be generated (check UPSTOX_API_KEY)."

    wl_path = Path(watchlist_path)
    result["watchlist_fresh"] = False
    result["watchlist_generated_at"] = None
    try:
        if wl_path.exists() and wl_path.stat().st_size > 0:
            gen_dt = datetime.fromtimestamp(wl_path.stat().st_mtime)
            result["watchlist_generated_at"] = gen_dt.strftime("%Y-%m-%d %H:%M")
            result["watchlist_fresh"] = gen_dt.strftime("%Y-%m-%d") == now_ist.strftime("%Y-%m-%d")
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# 2. Pre-market shortlist
# ---------------------------------------------------------------------------


def _shortlist_row(item: Dict[str, Any]) -> Dict[str, Any]:
    """Compact a watchlist item into a Buzz-readable row."""
    return {
        "symbol": item.get("symbol"),
        "regime": item.get("regime"),
        "sector": item.get("sector"),
        "conviction_score": item.get("conviction_score"),
        "close": item.get("close"),
        "entry": item.get("entry"),
        "stop_loss": item.get("stop_loss"),
        "target": item.get("target"),
        "atr_14": item.get("atr_14"),
        "hv_20": item.get("hv_20", item.get("hv20")),
    }


def _fmt_rupee(value: Any) -> str:
    """Format ₹ levels defensively — missing/partial data renders as '—'."""
    try:
        return f"₹{float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _markdown_table(rows: List[Dict[str, Any]]) -> str:
    """Render shortlist rows as a GitHub-flavored Markdown table for Buzz."""
    if not rows:
        return "_None today._"
    headers = ["Symbol", "Conviction", "Close", "Entry", "SL", "Target", "ATR", "HV20"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        lines.append(
            f"| {r.get('symbol', '—')} | {r.get('conviction_score', '—')} "
            f"| {_fmt_rupee(r.get('close'))} | {_fmt_rupee(r.get('entry'))} "
            f"| {_fmt_rupee(r.get('stop_loss'))} | {_fmt_rupee(r.get('target'))} "
            f"| {r.get('atr_14', '—')} | {r.get('hv_20', '—')} |"
        )
    return "\n".join(lines)


def get_premarket_shortlist(
    watchlist_path: Path = WATCHLIST_FILE,
    force_scan: bool = False,
) -> Dict[str, Any]:
    """
    INTERACTIVE endpoint — verify/execute the D-1 EOD scan and format the
    complete pre-market shortlist for Buzz.

    ALWAYS returns the full payload with Top Bullish, Top Bearish, and
    Volatility Harvest candidates (Autopsy conviction, ATR, trigger levels)
    plus a ready-to-render Markdown table — regardless of whether anything
    changed since the last poll. Never suppress on a user's explicit ask.
    """
    wl_path = Path(watchlist_path)
    wl: Dict[str, Any] = _load_json(wl_path, {})

    needs_scan = force_scan or not wl or not any(wl.get(cat) for cat in ("top_bullish", "top_bearish", "top_volatility_harvest"))
    if needs_scan:
        try:
            from src.scanner.eod_scanner import run_eod_scanner

            # Keep downstream prints out of this API's stdout (CLI emits pure JSON)
            with contextlib.redirect_stdout(io.StringIO()):
                run_eod_scanner()
            wl = _load_json(wl_path, wl)
        except Exception as err:
            logger.warning(f"D-1 scan attempt failed (feed offline?): {err}")

    bullish = [_shortlist_row(i) for i in wl.get("top_bullish", [])]
    bearish = [_shortlist_row(i) for i in wl.get("top_bearish", [])]
    harvest = [_shortlist_row(i) for i in wl.get("top_volatility_harvest", [])]

    markdown = (
        "## 📋 D-1 Pre-Market Shortlist\n\n"
        f"**🟢 Top Bullish**\n\n{_markdown_table(bullish)}\n\n"
        f"**🔴 Top Bearish**\n\n{_markdown_table(bearish)}\n\n"
        f"**🟡 Volatility Harvest**\n\n{_markdown_table(harvest)}\n"
    )

    return {
        "generated_at": wl.get("timestamp", datetime.now().isoformat()),
        "total_scanned": wl.get("total_scanned"),
        "total_candidates": len(bullish) + len(bearish) + len(harvest),
        "bullish": bullish,
        "bearish": bearish,
        "volatility_harvest": harvest,
        "markdown": markdown,
    }


# ---------------------------------------------------------------------------
# 3. Anti-spam state tracker
# ---------------------------------------------------------------------------


def _load_tracker(tracker_path: Path) -> Dict[str, Any]:
    tracker = _load_json(Path(tracker_path), {})
    if not isinstance(tracker, dict):
        tracker = {}
    tracker.setdefault("triggers_notified", {})  # {date: {symbol: triggered_at}}
    tracker.setdefault("positions", {})  # {trade_id: {last_action, last_sl_spot}}
    return tracker


def _save_tracker(tracker_path: Path, tracker: Dict[str, Any]) -> None:
    path = Path(tracker_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tracker["updated_at"] = datetime.now().isoformat()
    _atomic_json_write(path, tracker)


def _reset_tracker_if_new_day(tracker: Dict[str, Any], today_str: str) -> Dict[str, Any]:
    """Drop yesterday's trigger notifications so today's breakouts re-alert."""
    if today_str not in tracker["triggers_notified"]:
        tracker["triggers_notified"] = {today_str: {}}
    else:
        tracker["triggers_notified"] = {today_str: tracker["triggers_notified"][today_str]}
    return tracker


# ---------------------------------------------------------------------------
# 4. Trigger diff polling
# ---------------------------------------------------------------------------


def poll_actionable_triggers_diff(
    tracker_path: Path = TRACKER_FILE,
    watchlist_path: Path = WATCHLIST_FILE,
    radar_path: Path = RADAR_FILE,
    now_dt: Optional[datetime] = None,
    force_session_evaluation: bool = False,
) -> Dict[str, Any]:
    """
    BACKGROUND polling hook — run the Morning Radar and return ONLY newly
    triggered breakouts (anti-spam diff).

    Intended for the automated dispatcher/cron; identical repeat polls return
    an empty delta. For interactive user queries about the current shortlist,
    call get_premarket_shortlist() instead (always full payload).

    Each event carries Symbol, Bias, locked Trigger Time, Spot, exchange
    contract, Entry LTP, Target/SL premiums (0.65-delta anchored), and lot size.
    The tracker is updated atomically.
    """
    now_ist = _now_ist(now_dt)
    today_str = now_ist.strftime("%Y-%m-%d")

    try:
        # Keep the radar's progress prints out of this API's stdout (CLI emits pure JSON)
        with contextlib.redirect_stdout(io.StringIO()):
            radar = run_morning_radar(
                watchlist_path=watchlist_path,
                output_path=radar_path,
                force_session_evaluation=force_session_evaluation,
            )
    except Exception as err:
        logger.warning(f"Morning radar poll failed (feed offline?): {err}")
        radar = _load_json(Path(radar_path), {})

    tracker = _reset_tracker_if_new_day(_load_tracker(Path(tracker_path)), today_str)
    notified_today: Dict[str, str] = tracker["triggers_notified"][today_str]

    events: List[Dict[str, Any]] = []
    for item in radar.get("radar_items", []):
        if item.get("status") != "TRIGGERED":
            continue
        sym = item.get("symbol")
        triggered_at = item.get("triggered_at") or "09:30 IST"
        if notified_today.get(sym) == triggered_at:
            continue  # already notified — anti-spam suppression

        ticket = item.get("execution_ticket", {}) or {}
        naked = ticket.get("naked_option", ticket)
        legs = naked.get("legs", []) or [{}]
        primary_leg = legs[0] if legs else {}

        events.append(
            {
                "event_type": "TRIGGERED",
                "timestamp": now_ist.strftime("%Y-%m-%d %H:%M IST"),
                "symbol": sym,
                "bias": item.get("bias"),
                "triggered_at": triggered_at,
                "conviction_score": item.get("conviction_score"),
                "spot": item.get("close"),
                "contract": naked.get("option_symbol") or primary_leg.get("Option Contract"),
                "strike": naked.get("strike"),
                "entry_ltp": naked.get("option_entry_limit"),
                "target_premium": naked.get("option_target_exit"),
                "sl_premium": naked.get("option_sl_exit"),
                "delta": primary_leg.get("Delta", DELTA_ANCHOR),
                "lot_size": naked.get("lot_size"),
                "entry_spot_trigger": item.get("entry"),
            }
        )
        notified_today[sym] = triggered_at

    if events:
        _save_tracker(Path(tracker_path), tracker)

    return {
        "has_updates": bool(events),
        "events": events,
        "poll_time_ist": now_ist.strftime("%Y-%m-%d %H:%M IST"),
        "radar_timestamp": radar.get("timestamp"),
    }


# ---------------------------------------------------------------------------
# 5. Natural-language trade parsing + logging
# ---------------------------------------------------------------------------

_OPT_TYPE_RE = re.compile(r"\b(CE|PE|CALLS?|PUTS?)\b", re.IGNORECASE)
_STRIKE_RE = re.compile(r"(\d{2,6}(?:\.\d+)?)\s*(?:-)?\s*(?:CE|PE|CALLS?|PUTS?)\b", re.IGNORECASE)
_PRICE_RE = re.compile(r"(?:@|at)\s*(?:₹|rs\.?\s*|inr\s*)?(\d+(?:\.\d+)?)", re.IGNORECASE)
_PRICE_AFTER_TYPE_RE = re.compile(r"\b(?:CE|PE|CALLS?|PUTS?)\s*(?:@|at)?\s*(?:₹|rs\.?\s*|inr\s*)?(\d+(?:\.\d+)?)", re.IGNORECASE)
_LOTS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:lots?|qty|quantity)\b", re.IGNORECASE)
_BARE_NUM_RE = re.compile(r"\b(\d+(?:\.\d+)?)\b")
_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9&\-]{1,15}\b")
_NOISE_TOKENS = {"CE", "PE", "CALL", "CALLS", "PUT", "PUTS", "AT", "LOT", "LOTS", "QTY", "RS", "INR", "BOUGHT", "BUY", "SOLD", "SELL"}


def _fuzzy_symbol(text: str) -> Optional[str]:
    """Fuzzy-resolve a ticker token against the full F&O LOT_SIZE_MAP universe."""
    tokens = _TOKEN_RE.findall(text.upper())
    candidates = [t for t in tokens if t not in _NOISE_TOKENS and not t.isdigit()]
    known = set(LOT_SIZE_MAP.keys())
    for tok in candidates:
        if tok in known:
            return tok
    for tok in candidates:
        close = difflib.get_close_matches(tok, known, n=1, cutoff=0.85)
        if close:
            return close[0]
    return None


def parse_trade_text(text: str) -> Dict[str, Any]:
    """
    Extract {symbol, option_type, strike, entry_price, lots} from natural language.

    Example: "Bought HEROMOTOCO 5700 CE at 104.90, 1 lot"
    """
    raw: Dict[str, Any] = {"symbol": None, "option_type": None, "strike": None, "entry_price": None, "lots": None}

    if not text:
        return raw

    m = _OPT_TYPE_RE.search(text)
    if m:
        raw["option_type"] = "CE" if m.group(1).upper().startswith("C") else "PE"

    m = _STRIKE_RE.search(text)
    if m:
        try:
            raw["strike"] = float(m.group(1))
        except ValueError:
            pass

    m = _PRICE_RE.search(text)
    if not m:
        # Fallback: bare price directly after the option keyword ("2500 call 886.20")
        m = _PRICE_AFTER_TYPE_RE.search(text)
    if m:
        try:
            raw["entry_price"] = float(m.group(1))
        except ValueError:
            pass

    m = _LOTS_RE.search(text)
    if m:
        try:
            val = float(m.group(1))
            raw["lots"] = int(val) if val.is_integer() else val
        except ValueError:
            pass

    raw["symbol"] = _fuzzy_symbol(text)
    return raw


def _next_trade_id(existing_positions: List[Dict[str, Any]]) -> str:
    return f"TRD-{1001 + len(existing_positions)}"


def log_user_trade(
    text: Optional[str] = None,
    symbol: Optional[str] = None,
    strike: Optional[float] = None,
    option_type: Optional[str] = None,
    entry_price: Optional[float] = None,
    lots: int = 1,
    live_quotes: Optional[Dict[str, Dict[str, float]]] = None,
    active_file: Path = DEFAULT_ACTIVE_POS_FILE,
    trades_file: Path = ACTIVE_TRADES_FILE,
) -> Dict[str, Any]:
    """
    Log a user-reported fill (natural language from Buzz or explicit args).

    Parses the instruction, resolves the official lot size, derives the
    delta-anchored (0.65) Target premium and the 1.2x-ATR Initial SL, and
    appends the position to active_positions.json / active_trades.json with
    atomic writes. Returns a Buzz-ready trade ticket confirmation.
    """
    parsed = parse_trade_text(text or "")
    symbol = (symbol or parsed["symbol"] or "").replace(".NS", "").replace("^", "").strip().upper()
    if not symbol:
        return {"success": False, "error": "Could not resolve a ticker symbol. Example: 'Bought HEROMOTOCO 5700 CE at 104.90, 1 lot'"}

    opt_type = (option_type or parsed["option_type"] or "").strip().upper()
    if opt_type in ("CALL", "CALLS"):
        opt_type = "CE"
    if opt_type in ("PUT", "PUTS"):
        opt_type = "PE"
    if opt_type not in ("CE", "PE"):
        return {"success": False, "error": f"Could not resolve option type for '{symbol}' (say CE/PE or CALL/PUT)."}

    strike_val = float(strike) if strike is not None else parsed["strike"]
    if strike_val is None:
        return {"success": False, "error": f"Could not resolve strike price for '{symbol}' (e.g. '5700 CE')."}
    strike_val = snap_to_strike_grid(float(strike_val), symbol=symbol)

    price_val = float(entry_price) if entry_price is not None else parsed["entry_price"]
    if price_val is None or price_val <= 0:
        return {"success": False, "error": "Could not resolve entry price (e.g. 'at 104.90' or '@ 105')."}

    lots_val = int(lots) if lots and lots > 0 else (parsed["lots"] or 1)
    lot_size = get_lot_size(symbol)

    # Resolve entry spot (live quote > strike-anchored estimate)
    entry_spot = None
    spot_source = "estimated_from_strike"
    if live_quotes is not None:
        q = live_quotes.get(symbol, {})
        entry_spot = float(q.get("ltp", 0.0)) or None
    else:
        try:
            from src.data.upstox_provider import fetch_live_quotes_batch

            q = fetch_live_quotes_batch([symbol]).get(symbol, {})
            entry_spot = float(q.get("ltp", 0.0)) or None
        except Exception:
            entry_spot = None
    if entry_spot:
        spot_source = "live_quote"
    else:
        entry_spot = float(strike_val)

    is_bullish = opt_type == "CE"
    direction = "BULLISH" if is_bullish else "BEARISH"

    atr = entry_spot * DEFAULT_ATR_PCT_OF_SPOT
    target_spot = round(entry_spot * (1 + TARGET_SPOT_PCT / 100.0) if is_bullish else entry_spot * (1 - TARGET_SPOT_PCT / 100.0), 2)
    sl_spot = round(entry_spot - TRAILING_STOP_ATR_MULTIPLIER * atr if is_bullish else entry_spot + TRAILING_STOP_ATR_MULTIPLIER * atr, 2)

    dist_target = abs(target_spot - entry_spot)
    dist_sl = abs(sl_spot - entry_spot)
    p_target = round(price_val + DELTA_ANCHOR * dist_target, 2)
    p_sl = max(1.0, round(price_val - DELTA_ANCHOR * dist_sl, 2))

    exp_dt = get_monthly_expiry_date()
    expiry_str = exp_dt.strftime("%d%b%y").upper()
    option_symbol = f"{symbol} {expiry_str} {strike_val:g} {opt_type}"

    positions = _load_json(Path(active_file), [])
    if not isinstance(positions, list):
        positions = []
    trade_id = _next_trade_id([p for p in positions if isinstance(p, dict) and p.get("trade_id", "").startswith("TRD-")])

    now_ist = _now_ist()
    new_position = {
        "trade_id": trade_id,
        "symbol": symbol,
        "option_symbol": option_symbol,
        "strategy": f"Naked Long {opt_type} (User Fill)",
        "direction": direction,
        "entry_date": now_ist.strftime("%Y-%m-%d %H:%M IST"),
        "strike": strike_val,
        "option_type": opt_type,
        "entry_spot": entry_spot,
        "target_spot": target_spot,
        "sl_spot": sl_spot,
        "entry_premium": price_val,
        "target": p_target,
        "stop_loss": p_sl,
        "quantity_lots": lots_val,
        "lot_size": lot_size,
        "margin_blocked": round(price_val * lots_val * lot_size, 2),
        "current_ltp": price_val,
        "current_spot": entry_spot,
        "status": "OPEN",
        "trailing_sl_active": False,
        "atr": round(atr, 2),
    }
    positions.append(new_position)

    active_path = Path(active_file)
    active_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(active_path, positions)

    trades_path = Path(trades_file)
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(trades_path, positions)

    ticket_md = (
        f"✅ **{trade_id} logged** — {option_symbol}\n"
        f"• Entry ₹{price_val:,.2f} × {lots_val} lot(s) of {lot_size} (margin ₹{price_val * lots_val * lot_size:,.2f})\n"
        f"• 🎯 Target ₹{p_target:,.2f} (spot ₹{target_spot:,.2f}) | 🛑 SL ₹{p_sl:,.2f} (spot ₹{sl_spot:,.2f}, {TRAILING_STOP_ATR_MULTIPLIER:g}×ATR)\n"
        f"• Spot basis: {spot_source}"
    )

    return {
        "success": True,
        "trade_id": trade_id,
        "position": new_position,
        "spot_source": spot_source,
        "confirmation_markdown": ticket_md,
    }


# ---------------------------------------------------------------------------
# 6. Active position diff polling
# ---------------------------------------------------------------------------


def poll_active_positions_diff(
    active_file: Path = DEFAULT_ACTIVE_POS_FILE,
    tracker_path: Path = TRACKER_FILE,
    quotes_override: Optional[Dict[str, Dict[str, float]]] = None,
    now_dt_override: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    BACKGROUND polling hook — monitor active positions and return ONLY new
    actionable alerts (anti-spam diff).

    Intended for the automated dispatcher/cron; repeated identical states are
    suppressed (e.g. EOD_EXIT fires once, not every tick 15:10-15:30). For an
    interactive "how are my positions doing?" query, read the positions file
    directly or call monitor_active_trades() — never answer a user question
    with an empty diff.

    Also emits a discrete SL_RATCHET event when the trailing stop locks in a
    new price level.
    """
    now_ist = _now_ist(now_dt_override)

    # Capture pre-poll SL levels so first-time ratchets are detectable even
    # before the tracker has seen this trade before.
    pre_positions = _load_json(Path(active_file), [])
    pre_sl_by_trade: Dict[str, float] = {}
    if isinstance(pre_positions, list):
        for pos in pre_positions:
            if isinstance(pos, dict) and pos.get("status") == "OPEN" and pos.get("trailing_sl_active"):
                try:
                    pre_sl_by_trade[pos.get("trade_id", "TRD-???")] = float(pos.get("sl_spot", 0.0) or 0.0)
                except (TypeError, ValueError):
                    pass

    try:
        alerts = monitor_active_trades(
            active_file=active_file,
            quotes_override=quotes_override,
            now_dt_override=now_dt_override,
        )
    except Exception as err:
        logger.warning(f"Position monitor poll failed: {err}")
        alerts = []

    tracker = _load_tracker(Path(tracker_path))
    pos_state: Dict[str, Dict[str, Any]] = tracker["positions"]

    events: List[Dict[str, Any]] = []
    alerted_trade_ids = set()

    for alert in alerts:
        trade_id = alert.get("trade_id", "TRD-???")
        action = alert.get("action_type", "")
        prev = pos_state.setdefault(trade_id, {})
        alerted_trade_ids.add(trade_id)
        if prev.get("last_action") == action:
            continue  # unchanged tick / same state re-alert — anti-spam suppression
        events.append(
            {
                "event_type": action,
                "timestamp": now_ist.strftime("%Y-%m-%d %H:%M IST"),
                "trade_id": trade_id,
                "symbol": alert.get("symbol"),
                "direction": alert.get("direction"),
                "current_spot": alert.get("current_spot"),
                "current_ltp": alert.get("current_ltp"),
                "unrealized_pnl": alert.get("unrealized_pnl"),
                "slippage_inr": alert.get("slippage_inr"),
                "message": alert.get("action_alert"),
            }
        )
        prev["last_action"] = action

    # Detect trailing-SL ratchets that did NOT co-emit an alert this tick.
    # A ratchet is a genuine state change only when the SL level moved THIS poll
    # (vs the pre-poll snapshot) or vs the tracker's last recorded level.
    positions = _load_json(Path(active_file), [])
    if isinstance(positions, list):
        for pos in positions:
            if not isinstance(pos, dict) or pos.get("status") != "OPEN" or not pos.get("trailing_sl_active"):
                continue
            trade_id = pos.get("trade_id", "TRD-???")
            state = pos_state.setdefault(trade_id, {})
            try:
                cur_sl = float(pos.get("sl_spot", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            reference_sl = pre_sl_by_trade.get(trade_id, state.get("last_sl_spot"))
            if cur_sl > 0 and reference_sl is not None and cur_sl != reference_sl and trade_id not in alerted_trade_ids:
                events.append(
                    {
                        "event_type": "SL_RATCHET",
                        "timestamp": now_ist.strftime("%Y-%m-%d %H:%M IST"),
                        "trade_id": trade_id,
                        "symbol": pos.get("symbol", "").upper(),
                        "direction": pos.get("direction", "BULLISH").upper(),
                        "new_sl_spot": cur_sl,
                        "previous_sl_spot": reference_sl,
                        "current_spot": pos.get("current_spot"),
                        "message": f"🔒 Trailing SL ratcheted to ₹{cur_sl:,.2f} ({TRAILING_STOP_ATR_MULTIPLIER:g}×ATR trail).",
                    }
                )
            if cur_sl > 0:
                state["last_sl_spot"] = cur_sl

    if events:
        _save_tracker(Path(tracker_path), tracker)

    return {
        "has_updates": bool(events),
        "events": events,
        "poll_time_ist": now_ist.strftime("%Y-%m-%d %H:%M IST"),
    }


# ---------------------------------------------------------------------------
# 7. Daemon loop
# ---------------------------------------------------------------------------


def _append_event_log(events: List[Dict[str, Any]], log_file: Path = EVENTS_LOG_FILE) -> None:
    """Append structured events as JSON lines for Hermes/Buzz consumption."""
    if not events:
        return
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, default=str) + "\n")


def daemon_loop(interval_sec: int = 300) -> None:
    """
    Headless background polling during market hours (default every 5 minutes).

    Writes discrete diff events to data/radar/hermes_events.jsonl. Survives
    laptop sleep: the loop simply resumes on the next wake tick and re-polls
    full live state (SL/target/EOD evaluate current spot, so nothing is missed).
    """
    logger.info(f"Hermes IND OPT MKT daemon starting (interval={interval_sec}s). Ctrl+C to stop.")
    print(f"🤖 Hermes 'IND OPT MKT' daemon live — polling every {interval_sec}s during market hours. Ctrl+C to stop.", flush=True)
    try:
        while True:
            try:
                now_ist = _now_ist()
                if is_market_session_active(now_ist):
                    trig = poll_actionable_triggers_diff(now_dt=now_ist)
                    pos = poll_active_positions_diff(now_dt_override=now_ist)
                    events = trig["events"] + pos["events"]
                    if events:
                        _append_event_log(events)
                        for ev in events:
                            print(json.dumps(ev, default=str), flush=True)
                else:
                    logger.debug("Market closed — daemon idle.")
            except KeyboardInterrupt:
                raise
            except Exception as err:
                logger.error(f"Daemon tick failed (will retry next cycle): {err}")
            time_mod.sleep(interval_sec)
    except KeyboardInterrupt:
        print("🛑 Hermes daemon stopped by user.", flush=True)


# ---------------------------------------------------------------------------
# CLI entrypoint: python -m src.api.hermes_bridge <command> [--json]
# ---------------------------------------------------------------------------


def _cli() -> int:
    parser = argparse.ArgumentParser(prog="hermes_bridge", description="Hermes 'IND OPT MKT' agent bridge CLI")
    # --json is accepted both before and after the subcommand
    # (SUPPRESS keeps the subparser flag from clobbering a main-level True).
    parser.add_argument("--json", action="store_true", help="Emit raw JSON output")
    json_parent = argparse.ArgumentParser(add_help=False)
    json_parent.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", parents=[json_parent], help="Upstox auth, market phase, watchlist freshness")
    sub.add_parser("premarket", parents=[json_parent], help="D-1 shortlist summary for Buzz")
    sub.add_parser("triggers", parents=[json_parent], help="Diff poll: newly triggered ORB breakouts only")
    sub.add_parser("positions", parents=[json_parent], help="Diff poll: new actionable position alerts only")

    p_log = sub.add_parser("log-trade", parents=[json_parent], help="Log a user fill (NL text or explicit args)")
    p_log.add_argument("--text", default=None, help="e.g. 'Bought HEROMOTOCO 5700 CE at 104.90, 1 lot'")
    p_log.add_argument("--symbol", default=None)
    p_log.add_argument("--strike", type=float, default=None)
    p_log.add_argument("--type", dest="opt_type", default=None, choices=["CE", "PE", "CALL", "PUT"])
    p_log.add_argument("--price", type=float, default=None)
    p_log.add_argument("--lots", type=int, default=1)

    p_daemon = sub.add_parser("daemon", help="Background 5-min diff polling during market hours")
    p_daemon.add_argument("--interval", type=int, default=300)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "status":
        out = check_system_status()
    elif args.command == "premarket":
        out = get_premarket_shortlist()
    elif args.command == "triggers":
        out = poll_actionable_triggers_diff()
    elif args.command == "positions":
        out = poll_active_positions_diff()
    elif args.command == "log-trade":
        out = log_user_trade(
            text=args.text,
            symbol=args.symbol,
            strike=args.strike,
            option_type=args.opt_type,
            entry_price=args.price,
            lots=args.lots,
        )
    elif args.command == "daemon":
        daemon_loop(interval_sec=args.interval)
        return 0
    else:  # pragma: no cover
        parser.error(f"Unknown command: {args.command}")

    print(json.dumps(out, indent=2, default=str))
    return 0 if not isinstance(out, dict) or out.get("success", True) else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
