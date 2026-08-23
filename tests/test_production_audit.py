"""
Production Audit Regression Tests (A-to-Z Audit, Aug 2026).

Locks in the edge-case hardening verified during the full production audit:
- Zero-division guards: lot_size=0 sizing, strike_step=0 grid snapping.
- None-input safety: Black-Scholes kernel and best-strike target pricing.
- UI-thread resilience: corrupted watchlist / positions JSON degrades gracefully.
- Atomic persistence: no leftover tmp artifacts, valid JSON after writes.
- Mathematical invariants: put-call parity and 5-component NSE F&O cost model.
"""

import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from src.backtester.engine import calculate_fno_transaction_cost
from src.backtester.synthetic_options import (
    calculate_option_delta,
    calculate_option_price,
    find_strike_for_delta,
)
from src.data.option_analytics import get_best_strike, snap_to_strike_grid
from src.radar.morning_radar import run_morning_radar
from src.radar.trade_watcher import _atomic_json_write, monitor_active_trades
from src.risk.risk_manager import calculate_position_size


# ---------------------------------------------------------------------------
# Phase 1: Zero-division guards
# ---------------------------------------------------------------------------


def test_position_size_zero_lot_returns_zero():
    """lot_size=0 must return 0 (no capital risk), never raise ZeroDivisionError."""
    assert calculate_position_size(100000.0, 2.0, 100.0, 95.0, lot_size=0) == 0
    assert calculate_position_size(100000.0, 2.0, 100.0, 95.0, lot_size=-50) == 0


def test_snap_to_strike_grid_zero_step_does_not_divide_by_zero():
    """strike_step=0 / negative must fall back to the official step grid."""
    assert snap_to_strike_grid(1023.0, strike_step=0) == 1020.0  # 2500>spot>1000 -> step 10... 1023->1020
    assert snap_to_strike_grid(1023.0, strike_step=-5) == 1020.0


# ---------------------------------------------------------------------------
# Phase 1/3: None-input safety in pricing kernels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["c", "p"])
def test_black_scholes_none_inputs_return_zero(flag: str):
    """None S/K must degrade to 0.0 premium/delta instead of raising TypeError."""
    assert calculate_option_price(flag, None, 2500.0, 30) == 0.0
    assert calculate_option_price(flag, 2500.0, None, 30) == 0.0
    assert calculate_option_delta(flag, None, 2500.0, 30) == 0.0
    assert calculate_option_delta(flag, 2500.0, None, 30) == 0.0


def test_get_best_strike_none_target_falls_back_to_spot():
    """Default underlying_target=None must price off current spot, not crash."""
    df = pd.DataFrame(
        [
            {"strike_price": 2400.0, "call_ltp": 110.0, "call_iv": 0.20, "call_oi": 50000, "call_delta": 0.75, "put_ltp": 12.0, "put_iv": 0.22, "put_oi": 150000, "put_delta": -0.25},
            {"strike_price": 2450.0, "call_ltp": 70.0, "call_iv": 0.21, "call_oi": 80000, "call_delta": 0.62, "put_ltp": 22.0, "put_iv": 0.21, "put_oi": 120000, "put_delta": -0.38},
            {"strike_price": 2500.0, "call_ltp": 45.0, "call_iv": 0.22, "call_oi": 150000, "call_delta": 0.50, "put_ltp": 42.0, "put_iv": 0.22, "put_oi": 180000, "put_delta": -0.50},
        ]
    )
    result = get_best_strike(df, spot_price=2450.0, underlying_target=None, bias="BULLISH")
    assert isinstance(result["option_target_price"], float)
    assert result["underlying_target"] == 2450.0  # spot fallback applied


# ---------------------------------------------------------------------------
# Phase 2: Mathematical invariants
# ---------------------------------------------------------------------------


def test_put_call_parity_exact():
    """C - P == S - K*exp(-rT) must hold to float precision for the analytical kernel."""
    S, K, dte, r, sigma = 2500.0, 2500.0, 20.0, 0.065, 0.22
    call = calculate_option_price("c", S, K, dte, r, sigma)
    put = calculate_option_price("p", S, K, dte, r, sigma)
    parity_rhs = S - K * math.exp(-r * (dte / 365.0))
    assert abs((call - put) - parity_rhs) < 1e-9


def test_fno_transaction_cost_matches_sebi_nse_schedule():
    """All 5 statutory components must match the hand-computed NSE/SEBI schedule."""
    entry_premium, exit_premium, quantity = 100.0, 150.0, 750
    brokerage = 40.0  # Rs.20 buy + Rs.20 sell
    stt = exit_premium * quantity * 0.001  # 0.1% on sell turnover
    exchange_txn = (entry_premium + exit_premium) * quantity * 0.0005  # 0.05% turnover
    gst = (brokerage + exchange_txn) * 0.18  # 18% on brokerage + exchange
    stamp_duty = entry_premium * quantity * 0.00003  # 0.003% on buy turnover
    expected = round(brokerage + stt + exchange_txn + gst + stamp_duty, 2)

    assert calculate_fno_transaction_cost(entry_premium, exit_premium, quantity) == expected


def test_delta_strike_solver_lands_near_target():
    """Solved strike's realized delta must be within grid granularity of the target."""
    strike = find_strike_for_delta("c", 2500.0, 0.65, days_to_expiry=30, sigma=0.22)
    realized = calculate_option_delta("c", 2500.0, strike, days_to_expiry=30, sigma=0.22)
    assert abs(realized - 0.65) <= 0.05


# ---------------------------------------------------------------------------
# Phase 3/4: Resilience & atomic persistence
# ---------------------------------------------------------------------------


def test_morning_radar_corrupted_watchlist_degrades_gracefully(tmp_path: Path):
    """A corrupted watchlist JSON must produce an empty radar state, not a UI crash."""
    bad_watchlist = tmp_path / "watchlist_latest.json"
    bad_watchlist.write_text("{not-valid-json!!", encoding="utf-8")
    out_path = tmp_path / "radar_latest.json"

    result = run_morning_radar(watchlist_path=bad_watchlist, output_path=out_path)

    assert result["total_shortlisted"] == 0
    assert result["radar_items"] == []
    assert out_path.exists()  # clean empty state persisted atomically
    json.loads(out_path.read_text(encoding="utf-8"))  # and is valid JSON


def test_monitor_trades_corrupted_positions_file_returns_empty(tmp_path: Path):
    """A corrupted active positions file must yield no alerts instead of crashing."""
    bad_pos = tmp_path / "active_positions.json"
    bad_pos.write_text("[broken json", encoding="utf-8")

    alerts = monitor_active_trades(active_file=bad_pos, quotes_override={}, now_dt_override=datetime(2026, 8, 17, 10, 0))
    assert alerts == []


def test_atomic_json_write_leaves_no_tmp_artifacts(tmp_path: Path):
    """Atomic write must produce valid JSON and clean up its temp file."""
    target = tmp_path / "state.json"
    payload = [{"trade_id": "TRD-1", "status": "OPEN"}]

    _atomic_json_write(target, payload)

    assert json.loads(target.read_text(encoding="utf-8")) == payload
    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert leftovers == []


def test_monitor_trades_missing_file_returns_empty(tmp_path: Path):
    """Missing positions file must be a no-op (empty alert list)."""
    alerts = monitor_active_trades(
        active_file=tmp_path / "does_not_exist.json",
        quotes_override={},
        now_dt_override=datetime(2026, 8, 17, 10, 0),
    )
    assert alerts == []
