"""
Unit & Integration Tests — Hermes "IND OPT MKT" Agent Bridge (src/api/hermes_bridge.py).

Covers:
- System status check (mock authenticated vs token expired).
- Pre-market shortlist formatting.
- Trigger diff anti-spam deduplication (notified on first trigger, suppressed on identical re-poll).
- Natural-language trade parsing and atomic persistence into active_positions.json.
- Dynamic trailing stop ratcheting (1.2x ATR) and gap slippage in position diffs.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.api.hermes_bridge import (
    check_system_status,
    get_premarket_shortlist,
    log_user_trade,
    parse_trade_text,
    poll_active_positions_diff,
    poll_actionable_triggers_diff,
)


MONDAY_1000 = datetime(2026, 8, 17, 10, 0)  # weekday, live session


# ---------------------------------------------------------------------------
# System status
# ---------------------------------------------------------------------------


class _MockProvider:
    def __init__(self, valid: bool):
        self._valid = valid

    def is_token_valid(self) -> bool:
        return self._valid
        
    def get_user_profile(self) -> dict | None:
        if self._valid:
            return {"user_name": "TEST USER"}
        return None


def test_check_system_status_authenticated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.data.upstox_auth.get_login_url", lambda *a, **k: "https://login.upstox.com/test")
    wl = tmp_path / "watchlist_latest.json"
    wl.write_text(json.dumps({"top_bullish": [{"symbol": "RELIANCE"}]}), encoding="utf-8")

    # Today's date so the tmp file's mtime (written now) counts as fresh
    now_today = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)

    status = check_system_status(provider=_MockProvider(valid=True), now_dt=now_today, watchlist_path=wl)
    res = status["result"]

    assert res["status"] == "CONNECTED"
    assert res["user"] == "TEST USER"
    assert res["ready"] is True
    assert "login_url" not in res  # no nag when healthy
    assert res["market_phase"] in {"LIVE_TRADING", "EOD_SQUAREOFF", "CLOSED_WEEKEND"}
    assert res["watchlist_fresh"] is True  # tmp file mtime is today


def test_check_system_status_token_expired_returns_login_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.data.upstox_auth.get_login_url", lambda *a, **k: "https://login.upstox.com/authorize?x=1")
    wl = tmp_path / "watchlist_latest.json"
    wl.write_text(json.dumps({}), encoding="utf-8")

    status = check_system_status(provider=_MockProvider(valid=False), now_dt=MONDAY_1000, watchlist_path=wl)
    res = status["result"]

    assert res["status"] == "DISCONNECTED"
    assert res["auth_url"] == "https://login.upstox.com/authorize?x=1"
    assert res["listener_port"] == 8501


@pytest.mark.parametrize(
    "dt, expected_phase",
    [
        (datetime(2026, 8, 17, 8, 50), "PRE_MARKET"),
        (datetime(2026, 8, 17, 9, 20), "ORB_SILENT_WINDOW"),
        (datetime(2026, 8, 17, 10, 0), "LIVE_TRADING"),
        (datetime(2026, 8, 17, 15, 15), "EOD_SQUAREOFF"),
        (datetime(2026, 8, 17, 16, 0), "POST_MARKET"),
        (datetime(2026, 8, 22, 10, 0), "CLOSED_WEEKEND"),
    ],
)
def test_market_phase_lifecycle(tmp_path: Path, dt: datetime, expected_phase: str):
    status = check_system_status(provider=_MockProvider(valid=True), now_dt=dt, watchlist_path=tmp_path / "missing.json")
    res = status["result"]
    assert res["market_phase"] == expected_phase
    assert res["watchlist_fresh"] is False  # missing watchlist


# ---------------------------------------------------------------------------
# Pre-market shortlist
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_watchlist(tmp_path: Path) -> Path:
    wl = {
        "timestamp": "2026-08-16T18:00:00",
        "total_scanned": 208,
        "top_bullish": [
            {"symbol": "RELIANCE", "regime": "Bullish Momentum", "sector": "Oil, Gas & Energy",
             "conviction_score": 91.5, "close": 2500.0, "entry": 2510.0, "stop_loss": 2460.0,
             "target": 2600.0, "atr_14": 30.0, "hv_20": 22.4, "status": "WATCHING"},
        ],
        "top_bearish": [
            {"symbol": "TCS", "regime": "Bearish Momentum", "sector": "IT",
             "conviction_score": 88.0, "close": 4200.0, "entry": 4180.0, "stop_loss": 4260.0,
             "target": 4050.0, "atr_14": 63.0, "hv_20": 19.1, "status": "WATCHING"},
        ],
        "top_volatility_harvest": [],
        "vetoed_candidates": [],
    }
    path = tmp_path / "watchlist_latest.json"
    path.write_text(json.dumps(wl), encoding="utf-8")
    return path


def test_get_premarket_shortlist_formats_for_buzz(mock_watchlist: Path):
    out = get_premarket_shortlist(watchlist_path=mock_watchlist)
    res = out["result"]

    assert res["total_candidates"] == 2
    assert res["bullish"][0]["symbol"] == "RELIANCE"
    assert res["bullish"][0]["conviction"] == 91.5
    assert res["bearish"][0]["symbol"] == "TCS"
    assert res["volatility_harvest"] == []
    # Buzz markdown contract: header + per-category tables
    assert "📋 D-1 Pre-Market Shortlist" in res["markdown"]
    assert "| RELIANCE | 91.5 | 30.0 | 22.4 | Oil, Gas & Energy | WATCHING | — |" in res["markdown"]
    assert "| TCS | 88.0 |" in res["markdown"]
    assert "_None today._" in res["markdown"]  # empty harvest category rendered gracefully


# ---------------------------------------------------------------------------
# Trigger diff anti-spam state machine
# ---------------------------------------------------------------------------


@pytest.fixture
def triggered_watchlist(tmp_path: Path) -> Path:
    """D-1 watchlist whose RELIANCE candidate breaks out on the radar pass."""
    wl = {
        "timestamp": "2026-08-16T18:00:00",
        "top_bullish": [
            {
                "symbol": "RELIANCE",
                "close": 2500.0,
                "atr_14": 30.0,
                "conviction_score": 90.0,
                "regime": "Bullish Momentum",
                "suggested_action": "BUY CALL",
                "simulated_open": 2505.0,
                "has_event_risk": False,
                "candle_close": 2520.0,
                "orb_high": 2510.0,
                "orb_low": 2490.0,
                "rvol": 1.5,
            },
        ],
        "top_bearish": [],
        "top_volatility_harvest": [],
    }
    path = tmp_path / "watchlist_latest.json"
    path.write_text(json.dumps(wl), encoding="utf-8")
    return path


def _poll_triggers(tmp_path: Path, watchlist: Path, now: datetime) -> dict:
    return poll_actionable_triggers_diff(
        tracker_path=tmp_path / "alert_state_tracker.json",
        watchlist_path=watchlist,
        radar_path=tmp_path / "radar_latest.json",
        now_dt=now,
        force_session_evaluation=True,
    )


def test_trigger_diff_notifies_once_then_suppresses(tmp_path: Path, triggered_watchlist: Path):
    first = _poll_triggers(tmp_path, triggered_watchlist, MONDAY_1000)
    res = first["result"]

    assert len(res["new_breakouts"]) == 1
    ev = res["new_breakouts"][0]
    assert ev["symbol"] == "RELIANCE"
    assert ev["bias"] == "BULLISH"
    assert ev["trigger_time"]  # locked trigger timestamp
    assert ev["contract"]
    assert ev["lot_size"] > 0
    assert ev["ltp"] is not None and ev["ltp"] > 0
    assert ev["target_premium"] is not None and ev["trailing_sl"] is not None
    assert ev["delta"] is not None

    # Anti-spam: identical re-poll must return an EMPTY delta
    second = _poll_triggers(tmp_path, triggered_watchlist, datetime(2026, 8, 17, 10, 5))
    assert len(second["result"]["new_breakouts"]) == 0

    # Tracker persisted atomically and is valid JSON
    tracker = json.loads((tmp_path / "alert_state_tracker.json").read_text(encoding="utf-8"))
    assert "RELIANCE" in tracker["triggers_notified"]["2026-08-17"]


def test_trigger_diff_resets_next_day(tmp_path: Path, triggered_watchlist: Path):
    _poll_triggers(tmp_path, triggered_watchlist, MONDAY_1000)  # day 1 notified

    # Next trading day: same breakout re-notifies (stale suppression dropped)
    next_day = _poll_triggers(tmp_path, triggered_watchlist, datetime(2026, 8, 18, 10, 0))
    assert len(next_day["result"]["new_breakouts"]) == 1
    assert next_day["result"]["new_breakouts"][0]["symbol"] == "RELIANCE"


# ---------------------------------------------------------------------------
# Natural language trade parsing
# ---------------------------------------------------------------------------


def test_parse_trade_text_full_sentence():
    parsed = parse_trade_text("Bought HEROMOTOCO 5700 CE at 104.90, 1 lot")
    assert parsed == {"symbol": "HEROMOTOCO", "option_type": "CE", "strike": 5700.0, "entry_price": 104.9, "lots": 1}


def test_parse_trade_text_put_at_price_qty():
    parsed = parse_trade_text("sell idea 20 PE @ 12.35 4000 qty")  # fuzzy IDEA, PE, @-price, qty
    assert parsed["symbol"] == "IDEA"
    assert parsed["option_type"] == "PE"
    assert parsed["entry_price"] == 12.35
    assert parsed["lots"] == 4000


def test_parse_trade_text_call_keyword_and_fuzzy_symbol():
    parsed = parse_trade_text("bought relance 2500 call 886.20 2 lots")
    assert parsed["symbol"] == "RELIANCE"  # fuzzy-resolved typo
    assert parsed["option_type"] == "CE"
    assert parsed["strike"] == 2500.0
    assert parsed["entry_price"] == 886.2
    assert parsed["lots"] == 2


def test_parse_trade_text_garbage_returns_nones():
    parsed = parse_trade_text("good morning india")
    assert parsed["symbol"] is None
    assert parsed["option_type"] is None


def test_log_user_trade_nl_full_ticket(tmp_path: Path):
    active = tmp_path / "active_positions.json"
    trades = tmp_path / "active_trades.json"

    result = log_user_trade(
        text="Bought HEROMOTOCO 5700 CE at 104.90, 1 lot",
        live_quotes={"HEROMOTOCO": {"ltp": 5600.0}},
        active_file=active,
        trades_file=trades,
    )

    assert result["success"] is True, result.get("error")
    ticket = result["position"]
    assert result["spot_source"] == "live_quote"
    assert ticket["trade_id"] == "TRD-1001"
    assert ticket["symbol"] == "HEROMOTOCO"
    assert ticket["strike"] == 5700.0  # snapped to real exchange strike
    assert ticket["lot_size"] == 150  # official NSE lot from LOT_SIZE_MAP
    assert ticket["direction"] == "BULLISH"

    # 1.2x ATR initial SL (ATR = 1.5% of 5600 = 84.0 -> trail = 100.8)
    assert ticket["atr"] == 84.0
    assert ticket["sl_spot"] == pytest.approx(5600.0 - 1.2 * 84.0, abs=0.01)
    assert ticket["target_spot"] == pytest.approx(5600.0 * 1.03, abs=0.01)

    # Delta-anchored premiums: 0.65 x spot distance
    dist_t = ticket["target_spot"] - 5600.0
    dist_s = 5600.0 - ticket["sl_spot"]
    assert ticket["target"] == pytest.approx(104.90 + 0.65 * dist_t, abs=0.01)
    assert ticket["stop_loss"] == pytest.approx(104.90 - 0.65 * dist_s, abs=0.01)

    # Persisted atomically to BOTH journals
    persisted = json.loads(active.read_text(encoding="utf-8"))
    assert len(persisted) == 1 and persisted[0]["trade_id"] == "TRD-1001"
    assert json.loads(trades.read_text(encoding="utf-8")) == persisted

    # Second log gets an incrementing trade id
    second = log_user_trade(
        symbol="TCS", strike=4200.0, option_type="PE", entry_price=80.0, lots=2,
        live_quotes={"TCS": {"ltp": 4180.0}},
        active_file=active, trades_file=trades,
    )
    assert second["success"] is True
    assert second["position"]["trade_id"] == "TRD-1002"
    assert second["position"]["direction"] == "BEARISH"
    assert len(json.loads(active.read_text(encoding="utf-8"))) == 2


def test_log_user_trade_missing_fields_fails_clean(tmp_path: Path):
    result = log_user_trade(
        text="bought something random",
        active_file=tmp_path / "active_positions.json",
        trades_file=tmp_path / "active_trades.json",
    )
    assert result["success"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# Position diff: 1.2x ATR ratchet + gap slippage + anti-spam
# ---------------------------------------------------------------------------


def _write_position(tmp_path: Path, **overrides) -> Path:
    pos_file = tmp_path / "active_positions.json"
    pos = {
        "trade_id": "TRD-1001",
        "symbol": "RELIANCE",
        "strategy": "Naked Long CE",
        "direction": "BULLISH",
        "entry_premium": 50.0,
        "entry_spot": 2500.0,
        "target_spot": 2650.0,
        "sl_spot": 2450.0,
        "current_spot": 2500.0,
        "current_ltp": 50.0,
        "status": "OPEN",
        "quantity_lots": 1,
        "lot_size": 250,
        "atr": 37.5,
        "trailing_sl_active": True,
    }
    pos.update(overrides)
    pos_file.write_text(json.dumps([pos]), encoding="utf-8")
    return pos_file


def _poll_positions(tmp_path: Path, pos_file: Path, quotes: dict, now: datetime) -> dict:
    return poll_active_positions_diff(
        active_file=pos_file,
        tracker_path=tmp_path / "alert_state_tracker.json",
        quotes_override=quotes,
        now_dt_override=now,
    )


def test_position_diff_emits_1_2x_atr_ratchet_then_suppresses(tmp_path: Path):
    pos_file = _write_position(tmp_path)

    first = _poll_positions(tmp_path, pos_file, {"RELIANCE": {"ltp": 2550.0}}, MONDAY_1000)

    assert first["has_updates"] is True
    ratchets = [e for e in first["events"] if e["event_type"] == "SL_RATCHET"]
    assert len(ratchets) == 1
    assert ratchets[0]["new_sl_spot"] == 2505.0  # 2550 - 1.2*37.5 = 2550 - 45.0
    assert ratchets[0]["previous_sl_spot"] == 2450.0

    # Identical re-poll: SL unchanged -> empty delta (anti-spam)
    second = _poll_positions(tmp_path, pos_file, {"RELIANCE": {"ltp": 2550.0}}, datetime(2026, 8, 17, 10, 5))
    assert second["has_updates"] is False
    assert second["events"] == []

    # Spot advances: SL ratchets UP again to 2580 - 45 = 2535
    third = _poll_positions(tmp_path, pos_file, {"RELIANCE": {"ltp": 2580.0}}, datetime(2026, 8, 17, 10, 10))
    ratchets = [e for e in third["events"] if e["event_type"] == "SL_RATCHET"]
    assert len(ratchets) == 1
    assert ratchets[0]["new_sl_spot"] == 2535.0

    # Spot pulls back: SL must NOT ratchet down (max() invariant), no event
    fourth = _poll_positions(tmp_path, pos_file, {"RELIANCE": {"ltp": 2560.0}}, datetime(2026, 8, 17, 10, 15))
    assert fourth["has_updates"] is False
    saved_sl = json.loads(pos_file.read_text(encoding="utf-8"))[0]["sl_spot"]
    assert saved_sl == 2535.0


def test_position_diff_gap_slippage_on_sl_hit_and_dedup(tmp_path: Path):
    pos_file = _write_position(tmp_path, sl_spot=2450.0, trailing_sl_active=False)

    # Spot gaps down through SL: 2400 vs SL 2450 -> slippage = 50 * 250 units = 12,500
    first = _poll_positions(tmp_path, pos_file, {"RELIANCE": {"ltp": 2400.0}}, MONDAY_1000)
    sl_hits = [e for e in first["events"] if e["event_type"] == "SL_HIT"]
    assert len(sl_hits) == 1
    assert sl_hits[0]["slippage_inr"] == 12500.0

    # Unchanged re-poll: suppressed (genuine state change already reported)
    second = _poll_positions(tmp_path, pos_file, {"RELIANCE": {"ltp": 2400.0}}, datetime(2026, 8, 17, 10, 5))
    assert second["has_updates"] is False


def test_position_diff_target_then_sl_state_change_both_emit(tmp_path: Path):
    pos_file = _write_position(tmp_path, target_spot=2570.0, trailing_sl_active=False)

    first = _poll_positions(tmp_path, pos_file, {"RELIANCE": {"ltp": 2575.0}}, MONDAY_1000)
    assert [e["event_type"] for e in first["events"]] == ["TARGET_HIT"]

    # Market reverses hard through the stop: action CHANGES -> re-alert allowed
    second = _poll_positions(tmp_path, pos_file, {"RELIANCE": {"ltp": 2440.0}}, datetime(2026, 8, 17, 10, 5))
    types = [e["event_type"] for e in second["events"]]
    assert "SL_HIT" in types
