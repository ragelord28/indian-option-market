"""
Unit tests for Rate-Limit Safe Batch Quote Ingestion & Live Active Trade Watcher Engine
(src/data/upstox_provider.py & src/radar/trade_watcher.py).
"""

from datetime import datetime
import json
import pytest
from pathlib import Path

from src.data.upstox_provider import fetch_live_quotes_batch, UpstoxProvider
from src.radar.trade_watcher import monitor_active_trades


def test_fetch_live_quotes_batch_fallback():
    """Test fetch_live_quotes_batch returns clean quote structure."""
    quotes = fetch_live_quotes_batch(["RELIANCE", "HAL"])
    assert "RELIANCE" in quotes
    assert "HAL" in quotes
    assert "ltp" in quotes["RELIANCE"]
    assert "close" in quotes["HAL"]


def test_monitor_active_trades_alerts(tmp_path):
    """Test trade_watcher evaluates Target Hit, SL Hit, Trailing SL, Time Stop, and EOD Exit alerts."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": "TRD-2001",
            "symbol": "RELIANCE",
            "strategy": "Bull Call Spread",
            "entry_premium": 50.0,
            "entry_spot": 2500.0,
            "target_spot": 2600.0,
            "sl_spot": 2450.0,
            "current_ltp": 50.0,
            "stop_loss": 2450.0,
            "target": 2600.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 250,
            "margin_blocked": 12500.0,
        },
        {
            "trade_id": "TRD-2002",
            "symbol": "HAL",
            "strategy": "Naked Long CE",
            "entry_premium": 100.0,
            "entry_spot": 4000.0,
            "target_spot": 4200.0,
            "sl_spot": 3900.0,
            "current_ltp": 100.0,
            "stop_loss": 3900.0,
            "target": 4200.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 150,
            "margin_blocked": 15000.0,
        },
    ]

    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    # 1. Mock quotes where RELIANCE hits target (2610 > 2600) and HAL breaches SL (3850 < 3900)
    mock_quotes = {
        "RELIANCE": {"ltp": 2610.0, "volume": 1000.0, "high": 2615.0, "low": 2500.0, "close": 2610.0, "open": 2500.0},
        "HAL": {"ltp": 3850.0, "volume": 500.0, "high": 4010.0, "low": 3840.0, "close": 3850.0, "open": 4000.0},
    }

    test_time = datetime(2026, 8, 17, 10, 30)  # Morning
    alerts = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=test_time)

    assert len(alerts) >= 2
    alert_map = {a["trade_id"]: a for a in alerts}

    assert alert_map["TRD-2001"]["action_type"] == "TARGET_HIT"
    assert "TARGET HIT" in alert_map["TRD-2001"]["action_alert"]

    assert alert_map["TRD-2002"]["action_type"] == "SL_HIT"
    assert "STOP LOSS HIT" in alert_map["TRD-2002"]["action_alert"]


def test_monitor_active_trades_time_stop_and_eod_exit(tmp_path):
    """Test 13:30 Time Stop and 15:10 Square-Off alerts."""
    pos_file = tmp_path / "active_positions.json"
    positions = [
        {
            "trade_id": "TRD-3001",
            "symbol": "INFY",
            "strategy": "Bull Call Spread",
            "entry_premium": 50.0,
            "entry_spot": 1500.0,
            "target_spot": 1550.0,
            "sl_spot": 1450.0,
            "current_ltp": 50.5,  # Stagnant PnL (+1%)
            "stop_loss": 35.0,
            "target": 75.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 400,
            "margin_blocked": 20000.0,
        }
    ]
    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    mock_quotes = {
        "INFY": {"ltp": 1510.0, "volume": 1000.0, "high": 1515.0, "low": 1495.0, "close": 1510.0, "open": 1500.0}
    }

    # Time at 13:45 IST (Time stop trigger)
    t_1345 = datetime(2026, 8, 17, 13, 45)
    alerts_1345 = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=t_1345)
    assert len(alerts_1345) == 1
    assert alerts_1345[0]["action_type"] == "TIME_STOP"

    # Time at 15:15 IST (EOD Exit trigger)
    t_1515 = datetime(2026, 8, 17, 15, 15)
    alerts_1515 = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=t_1515)
    assert len(alerts_1515) == 1
    assert alerts_1515[0]["action_type"] == "EOD_EXIT"
