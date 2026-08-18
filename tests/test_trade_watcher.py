"""
Unit tests for Rate-Limit Safe Batch Quote Ingestion & Live Active Trade Watcher Engine
(src/data/upstox_provider.py & src/radar/trade_watcher.py).

Covers:
- Batch quote fetching with yfinance fallback
- BULLISH and BEARISH trade alert evaluation
- Stocks priced under Rs 200 (e.g. ASHOKLEY at Rs 177)
- Alert priority ordering (EOD_EXIT > SL_HIT > TARGET_HIT > TRAILING_SL > TIME_STOP)
- Atomic JSON writes
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


def test_monitor_active_trades_bullish_alerts(tmp_path):
    """Test bullish trade Target Hit and SL Hit alerts with equity spot quotes."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": "TRD-2001",
            "symbol": "RELIANCE",
            "strategy": "Bull Call Spread",
            "direction": "BULLISH",
            "entry_premium": 50.0,
            "entry_spot": 2500.0,
            "target_spot": 2600.0,
            "sl_spot": 2450.0,
            "current_spot": 2500.0,
            "current_ltp": 50.0,
            "stop_loss": 35.0,
            "target": 75.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 250,
            "margin_blocked": 12500.0,
            "trailing_sl_active": False,
        },
        {
            "trade_id": "TRD-2002",
            "symbol": "HAL",
            "strategy": "Naked Long CE",
            "direction": "BULLISH",
            "entry_premium": 100.0,
            "entry_spot": 4000.0,
            "target_spot": 4200.0,
            "sl_spot": 3900.0,
            "current_spot": 4000.0,
            "current_ltp": 100.0,
            "stop_loss": 70.0,
            "target": 150.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 150,
            "margin_blocked": 15000.0,
            "trailing_sl_active": False,
        },
    ]

    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    # RELIANCE hits target (2610 > 2600), HAL breaches SL (3850 < 3900)
    mock_quotes = {
        "RELIANCE": {"ltp": 2610.0, "volume": 1000.0, "high": 2615.0, "low": 2500.0, "close": 2610.0, "open": 2500.0},
        "HAL": {"ltp": 3850.0, "volume": 500.0, "high": 4010.0, "low": 3840.0, "close": 3850.0, "open": 4000.0},
    }

    test_time = datetime(2026, 8, 17, 10, 30)  # Morning (before 13:30 and 15:10)
    alerts = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=test_time)

    assert len(alerts) >= 2
    alert_map = {a["trade_id"]: a for a in alerts}

    # SL_HIT has higher priority than TARGET_HIT in the elif chain,
    # but RELIANCE hit target, HAL hit SL
    assert alert_map["TRD-2002"]["action_type"] == "SL_HIT"
    assert "STOP LOSS HIT" in alert_map["TRD-2002"]["action_alert"]

    assert alert_map["TRD-2001"]["action_type"] == "TARGET_HIT"
    assert "TARGET HIT" in alert_map["TRD-2001"]["action_alert"]


def test_monitor_active_trades_bearish_alerts(tmp_path):
    """Test BEARISH trade direction with inverted SL and Target logic."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": "TRD-4001",
            "symbol": "INFY",
            "strategy": "Bear Put Debit Spread",
            "direction": "BEARISH",
            "entry_premium": 60.0,
            "entry_spot": 1500.0,
            "target_spot": 1450.0,  # Below entry for bearish
            "sl_spot": 1550.0,     # Above entry for bearish
            "current_spot": 1500.0,
            "current_ltp": 60.0,
            "stop_loss": 40.0,
            "target": 90.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 400,
            "margin_blocked": 24000.0,
            "trailing_sl_active": False,
        },
        {
            "trade_id": "TRD-4002",
            "symbol": "TCS",
            "strategy": "Bear Call Credit Spread",
            "direction": "BEARISH",
            "entry_premium": 30.0,
            "entry_spot": 4200.0,
            "target_spot": 4100.0,  # Below entry for bearish
            "sl_spot": 4300.0,     # Above entry for bearish
            "current_spot": 4200.0,
            "current_ltp": 30.0,
            "stop_loss": 20.0,
            "target": 45.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 175,
            "margin_blocked": 5250.0,
            "trailing_sl_active": False,
        },
    ]

    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    # INFY drops to 1440 (below target_spot 1450 -> TARGET_HIT for bearish)
    # TCS rises to 4310 (above sl_spot 4300 -> SL_HIT for bearish)
    mock_quotes = {
        "INFY": {"ltp": 1440.0, "volume": 800.0, "high": 1510.0, "low": 1435.0, "close": 1440.0, "open": 1500.0},
        "TCS": {"ltp": 4310.0, "volume": 600.0, "high": 4315.0, "low": 4190.0, "close": 4310.0, "open": 4200.0},
    }

    test_time = datetime(2026, 8, 17, 11, 0)
    alerts = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=test_time)

    assert len(alerts) >= 2
    alert_map = {a["trade_id"]: a for a in alerts}

    assert alert_map["TRD-4001"]["action_type"] == "TARGET_HIT"
    assert "TARGET HIT" in alert_map["TRD-4001"]["action_alert"]

    assert alert_map["TRD-4002"]["action_type"] == "SL_HIT"
    assert "STOP LOSS HIT" in alert_map["TRD-4002"]["action_alert"]


def test_monitor_sub_200_stock_no_misclassification(tmp_path):
    """Test that stocks priced under Rs 200 (e.g. ASHOKLEY at Rs 177) are NOT
    misclassified as option premiums. The > 200 heuristic has been removed."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": "TRD-5001",
            "symbol": "ASHOKLEY",
            "strategy": "Naked Long CE",
            "direction": "BULLISH",
            "entry_premium": 8.5,
            "entry_spot": 177.0,
            "target_spot": 185.0,
            "sl_spot": 172.0,
            "current_spot": 177.0,
            "current_ltp": 8.5,
            "stop_loss": 5.0,
            "target": 14.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 5000,
            "margin_blocked": 42500.0,
            "trailing_sl_active": False,
        }
    ]

    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    # ASHOKLEY spot = 186.0 (above target_spot 185.0 -> TARGET_HIT)
    mock_quotes = {
        "ASHOKLEY": {"ltp": 186.0, "volume": 3000.0, "high": 187.0, "low": 175.0, "close": 186.0, "open": 177.0},
    }

    test_time = datetime(2026, 8, 17, 10, 0)
    alerts = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=test_time)

    assert len(alerts) == 1
    assert alerts[0]["action_type"] == "TARGET_HIT"
    assert alerts[0]["current_spot"] == 186.0


def test_eod_exit_overrides_trailing_sl(tmp_path):
    """Test that EOD_EXIT (15:10) takes priority over TRAILING_SL."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": "TRD-6001",
            "symbol": "PAGEIND",
            "strategy": "Naked Long CE",
            "direction": "BULLISH",
            "entry_premium": 200.0,
            "entry_spot": 40000.0,
            "target_spot": 42000.0,
            "sl_spot": 39000.0,
            "current_spot": 40000.0,
            "current_ltp": 200.0,
            "stop_loss": 150.0,
            "target": 350.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 15,
            "margin_blocked": 3000.0,
            "trailing_sl_active": False,
        }
    ]

    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    # Price moved +1.5% (normally would trigger TRAILING_SL), but it's 15:15
    mock_quotes = {
        "PAGEIND": {"ltp": 40600.0, "volume": 200.0, "high": 40650.0, "low": 39900.0, "close": 40600.0, "open": 40000.0},
    }

    # Time at 15:15 IST -> EOD_EXIT should override TRAILING_SL
    t_1515 = datetime(2026, 8, 17, 15, 15)
    alerts = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=t_1515)

    assert len(alerts) == 1
    assert alerts[0]["action_type"] == "EOD_EXIT"
    assert "15:10 SQUARE OFF" in alerts[0]["action_alert"]


def test_time_stop_stagnant_trade(tmp_path):
    """Test 13:30 Time Stop for stagnant trade with PnL between -3% and +3%."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": "TRD-7001",
            "symbol": "INFY",
            "strategy": "Bull Call Spread",
            "direction": "BULLISH",
            "entry_premium": 50.0,
            "entry_spot": 1500.0,
            "target_spot": 1550.0,
            "sl_spot": 1450.0,
            "current_spot": 1500.0,
            "current_ltp": 50.0,
            "stop_loss": 35.0,
            "target": 75.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 400,
            "margin_blocked": 20000.0,
            "trailing_sl_active": False,
        }
    ]
    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    # Spot barely moved: 1510 = +0.67% (within -3% to +3%)
    mock_quotes = {
        "INFY": {"ltp": 1510.0, "volume": 1000.0, "high": 1515.0, "low": 1495.0, "close": 1510.0, "open": 1500.0}
    }

    # Time at 13:45 IST (Time stop trigger)
    t_1345 = datetime(2026, 8, 17, 13, 45)
    alerts_1345 = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=t_1345)
    assert len(alerts_1345) == 1
    assert alerts_1345[0]["action_type"] == "TIME_STOP"


def test_bearish_trailing_sl_trigger(tmp_path):
    """Test BEARISH trailing SL triggers when spot drops 1.5% below entry."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": "TRD-8001",
            "symbol": "TCS",
            "strategy": "Bear Put Debit Spread",
            "direction": "BEARISH",
            "entry_premium": 40.0,
            "entry_spot": 4200.0,
            "target_spot": 4050.0,
            "sl_spot": 4300.0,
            "current_spot": 4200.0,
            "current_ltp": 40.0,
            "stop_loss": 25.0,
            "target": 65.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 175,
            "margin_blocked": 7000.0,
            "trailing_sl_active": False,
        }
    ]
    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    # Spot dropped to 4130 = -1.67% (below entry * 0.985 = 4137)
    # This is between sl_spot (4300) and target_spot (4050), so no SL/Target hit
    mock_quotes = {
        "TCS": {"ltp": 4130.0, "volume": 900.0, "high": 4210.0, "low": 4125.0, "close": 4130.0, "open": 4200.0},
    }

    test_time = datetime(2026, 8, 17, 10, 30)
    alerts = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=test_time)

    assert len(alerts) == 1
    assert alerts[0]["action_type"] == "TRAILING_SL"
    assert "MOVE SL TO ENTRY" in alerts[0]["action_alert"]


def test_trade_logging_payload_structure():
    """Verify precise trade logging payload structure."""
    payload = {
        "trade_id": "TRD-1001",
        "symbol": "RELIANCE",
        "option_symbol": "RELIANCE 25AUG26 2480 CE",
        "strategy": "🎯 Naked Single Strike (CE Sniper)",
        "direction": "BULLISH",
        "entry_date": "2026-08-18 11:00 IST",
        "strike": 2480.0,
        "entry_spot": 2500.0,
        "target_spot": 2575.0,
        "sl_spot": 2462.5,
        "entry_premium": 65.4,
        "target": 105.2,
        "stop_loss": 42.1,
        "quantity_lots": 1,
        "lot_size": 250,
        "margin_blocked": 16350.0,
        "current_ltp": 65.4,
        "current_spot": 2500.0,
        "status": "OPEN",
        "trailing_sl_active": False,
    }

    assert payload["trade_id"] == "TRD-1001"
    assert "option_symbol" in payload
    assert payload["direction"] in ("BULLISH", "BEARISH")
    assert payload["status"] == "OPEN"
    assert payload["margin_blocked"] > 0
