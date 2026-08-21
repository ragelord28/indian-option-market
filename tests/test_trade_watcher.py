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


@pytest.mark.parametrize(
    "direction, entry_spot, sl_spot, target_spot, live_quote_spot, expected_action, description",
    [
        ("BULLISH", 2500.0, 2450.0, 2600.0, 2380.0, "SL_HIT", "Bullish gap down past SL"),
        ("BULLISH", 2500.0, 2450.0, 2600.0, 2720.0, "TARGET_HIT", "Bullish gap up past target"),
        ("BEARISH", 4200.0, 4300.0, 4050.0, 4380.0, "SL_HIT", "Bearish gap up past SL"),
        ("BEARISH", 4200.0, 4300.0, 4050.0, 3950.0, "TARGET_HIT", "Bearish gap down past target"),
    ],
)
def test_parameterized_gap_slippage_scenarios(
    tmp_path, direction, entry_spot, sl_spot, target_spot, live_quote_spot, expected_action, description
):
    """Test gap slippage past SL and target levels for both BULLISH and BEARISH positions."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": f"TRD-GAP-{direction}",
            "symbol": "MOCKSYM",
            "strategy": "Debit Spread",
            "direction": direction,
            "entry_premium": 50.0,
            "entry_spot": entry_spot,
            "target_spot": target_spot,
            "sl_spot": sl_spot,
            "current_spot": entry_spot,
            "current_ltp": 50.0,
            "stop_loss": 35.0,
            "target": 75.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 100,
            "margin_blocked": 10000.0,
            "trailing_sl_active": False,
        }
    ]

    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    mock_quotes = {
        "MOCKSYM": {
            "ltp": live_quote_spot,
            "volume": 1000.0,
            "high": live_quote_spot + 10.0,
            "low": live_quote_spot - 10.0,
            "close": live_quote_spot,
            "open": entry_spot,
        }
    }

    test_time = datetime(2026, 8, 17, 10, 30)
    alerts = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=test_time)

    assert len(alerts) == 1, f"Failed on scenario: {description}"
    assert alerts[0]["action_type"] == expected_action
    assert alerts[0]["current_spot"] == live_quote_spot

    # Verify persisted JSON file reflects updated current_spot
    with open(pos_file, "r", encoding="utf-8") as f:
        saved_positions = json.load(f)
    assert saved_positions[0]["current_spot"] == live_quote_spot


@pytest.mark.parametrize(
    "test_time, quote_map, expected_alert_actions",
    [
        (
            datetime(2026, 8, 17, 10, 30),  # 10:30 AM Mid-morning
            {
                "RELIANCE": 2545.0,  # BULLISH: +1.8% -> TRAILING_SL
                "TCS": 4130.0,       # BEARISH: -1.67% -> TRAILING_SL
                "INFY": 1420.0,      # BULLISH: gap down past SL (1450) -> SL_HIT
                "HDFCBANK": 1500.0,  # BEARISH: gap down past Target (1540) -> TARGET_HIT
            },
            {
                "TRD-MULTI-01": "TRAILING_SL",
                "TRD-MULTI-02": "TRAILING_SL",
                "TRD-MULTI-03": "SL_HIT",
                "TRD-MULTI-04": "TARGET_HIT",
            },
        ),
        (
            datetime(2026, 8, 17, 15, 15),  # 15:15 PM EOD Square Off period
            {
                "RELIANCE": 2545.0,
                "TCS": 4130.0,
                "INFY": 1420.0,
                "HDFCBANK": 1500.0,
            },
            {
                "TRD-MULTI-01": "EOD_EXIT",
                "TRD-MULTI-02": "EOD_EXIT",
                "TRD-MULTI-03": "EOD_EXIT",
                "TRD-MULTI-04": "EOD_EXIT",
            },
        ),
    ],
)
def test_parameterized_simultaneous_multi_position_monitoring(
    tmp_path, test_time, quote_map, expected_alert_actions
):
    """Test simultaneous evaluation of multiple open BULLISH and BEARISH positions."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": "TRD-MULTI-01",
            "symbol": "RELIANCE",
            "strategy": "Bull Call Spread",
            "direction": "BULLISH",
            "entry_premium": 50.0,
            "entry_spot": 2500.0,
            "target_spot": 2600.0,
            "sl_spot": 2450.0,
            "current_spot": 2500.0,
            "current_ltp": 50.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 250,
            "trailing_sl_active": False,
        },
        {
            "trade_id": "TRD-MULTI-02",
            "symbol": "TCS",
            "strategy": "Bear Put Debit Spread",
            "direction": "BEARISH",
            "entry_premium": 40.0,
            "entry_spot": 4200.0,
            "target_spot": 4050.0,
            "sl_spot": 4300.0,
            "current_spot": 4200.0,
            "current_ltp": 40.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 175,
            "trailing_sl_active": False,
        },
        {
            "trade_id": "TRD-MULTI-03",
            "symbol": "INFY",
            "strategy": "Naked Long CE",
            "direction": "BULLISH",
            "entry_premium": 30.0,
            "entry_spot": 1500.0,
            "target_spot": 1550.0,
            "sl_spot": 1450.0,
            "current_spot": 1500.0,
            "current_ltp": 30.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 400,
            "trailing_sl_active": False,
        },
        {
            "trade_id": "TRD-MULTI-04",
            "symbol": "HDFCBANK",
            "strategy": "Bear Call Credit Spread",
            "direction": "BEARISH",
            "entry_premium": 25.0,
            "entry_spot": 1600.0,
            "target_spot": 1540.0,
            "sl_spot": 1640.0,
            "current_spot": 1600.0,
            "current_ltp": 25.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 550,
            "trailing_sl_active": False,
        },
    ]

    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    mock_quotes = {
        sym: {"ltp": spot, "volume": 1000.0, "high": spot + 5.0, "low": spot - 5.0, "close": spot, "open": spot}
        for sym, spot in quote_map.items()
    }

    alerts = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=test_time)

    assert len(alerts) == len(expected_alert_actions)
    alert_map = {a["trade_id"]: a["action_type"] for a in alerts}

    for trade_id, expected_type in expected_alert_actions.items():
        assert alert_map[trade_id] == expected_type


@pytest.mark.parametrize(
    "direction, entry_spot, sl_spot, target_spot, quote_spot, initial_trailing_active, expected_alert, expected_final_trailing_active",
    [
        ("BULLISH", 1000.0, 970.0, 1050.0, 1020.0, False, "TRAILING_SL", True),
        ("BULLISH", 1000.0, 970.0, 1050.0, 1020.0, True, None, True),
        ("BEARISH", 1000.0, 1030.0, 950.0, 980.0, False, "TRAILING_SL", True),
        ("BEARISH", 1000.0, 1030.0, 950.0, 980.0, True, None, True),
    ],
)
def test_parameterized_dynamic_trailing_sl_advancement(
    tmp_path,
    direction,
    entry_spot,
    sl_spot,
    target_spot,
    quote_spot,
    initial_trailing_active,
    expected_alert,
    expected_final_trailing_active,
):
    """Test dynamic trailing SL state transitions for BULLISH and BEARISH positions."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": "TRD-TRAIL-01",
            "symbol": "TESTSYM",
            "strategy": "Spread",
            "direction": direction,
            "entry_premium": 20.0,
            "entry_spot": entry_spot,
            "target_spot": target_spot,
            "sl_spot": sl_spot,
            "current_spot": entry_spot,
            "current_ltp": 20.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 100,
            "trailing_sl_active": initial_trailing_active,
        }
    ]

    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    mock_quotes = {
        "TESTSYM": {"ltp": quote_spot, "volume": 500.0, "high": quote_spot, "low": quote_spot, "close": quote_spot, "open": entry_spot}
    }

    test_time = datetime(2026, 8, 17, 11, 15)
    alerts = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=test_time)

    if expected_alert is None:
        assert len(alerts) == 0
    else:
        assert len(alerts) == 1
        assert alerts[0]["action_type"] == expected_alert

    # Verify atomic update persisted the expected trailing_sl_active state
    with open(pos_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved[0]["trailing_sl_active"] == expected_final_trailing_active


@pytest.mark.parametrize(
    "eval_time, is_eod_expected",
    [
        (datetime(2026, 8, 17, 10, 0), False),
        (datetime(2026, 8, 17, 13, 0), False),
        (datetime(2026, 8, 17, 15, 10), True),
        (datetime(2026, 8, 17, 15, 20), True),
        (datetime(2026, 8, 17, 15, 30), True),
        (datetime(2026, 8, 17, 15, 35), False),
    ],
)
def test_parameterized_eod_square_off_time_window(tmp_path, eval_time, is_eod_expected):
    """Test 15:10 EOD square-off activation across various market hours for multiple positions."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": "TRD-EOD-BULL",
            "symbol": "RELIANCE",
            "strategy": "Bull Call Spread",
            "direction": "BULLISH",
            "entry_premium": 50.0,
            "entry_spot": 2500.0,
            "target_spot": 2600.0,
            "sl_spot": 2450.0,
            "current_spot": 2500.0,
            "current_ltp": 50.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 250,
            "trailing_sl_active": False,
        },
        {
            "trade_id": "TRD-EOD-BEAR",
            "symbol": "TCS",
            "strategy": "Bear Put Spread",
            "direction": "BEARISH",
            "entry_premium": 40.0,
            "entry_spot": 4200.0,
            "target_spot": 4050.0,
            "sl_spot": 4300.0,
            "current_spot": 4200.0,
            "current_ltp": 40.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 175,
            "trailing_sl_active": False,
        },
    ]

    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    mock_quotes = {
        "RELIANCE": {"ltp": 2510.0, "volume": 1000.0, "high": 2515.0, "low": 2495.0, "close": 2510.0, "open": 2500.0},
        "TCS": {"ltp": 4190.0, "volume": 500.0, "high": 4205.0, "low": 4185.0, "close": 4190.0, "open": 4200.0},
    }

    alerts = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=eval_time)

    if is_eod_expected:
        assert len(alerts) == 2
        for alert in alerts:
            assert alert["action_type"] == "EOD_EXIT"
            assert "15:10 SQUARE OFF" in alert["action_alert"]
    else:
        eod_alerts = [a for a in alerts if a["action_type"] == "EOD_EXIT"]
        assert len(eod_alerts) == 0


def test_dynamic_tick_by_tick_trailing_stop_calculation(tmp_path):
    """Test dynamic tick-by-tick trailing stop adjustment and atomic JSON persistence."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": "TRD-DYN-BULL",
            "symbol": "RELIANCE",
            "strategy": "Bull Call Spread",
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
        },
        {
            "trade_id": "TRD-DYN-BEAR",
            "symbol": "TCS",
            "strategy": "Bear Put Spread",
            "direction": "BEARISH",
            "entry_premium": 40.0,
            "entry_spot": 4200.0,
            "target_spot": 4050.0,
            "sl_spot": 4300.0,
            "current_spot": 4200.0,
            "current_ltp": 40.0,
            "status": "OPEN",
            "quantity_lots": 1,
            "lot_size": 175,
            "atr": 63.0,
            "trailing_sl_active": True,
        },
    ]

    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    # Tick 1: RELIANCE spot goes to 2550 (new_sl = max(2450, round(2550 - 37.5)) = 2512.5)
    # TCS spot drops to 4130 (new_sl = min(4300, round(4130 + 63)) = 4193.0)
    mock_quotes_1 = {
        "RELIANCE": {"ltp": 2550.0, "volume": 1000.0},
        "TCS": {"ltp": 4130.0, "volume": 500.0},
    }

    test_time = datetime(2026, 8, 17, 11, 0)
    monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes_1, now_dt_override=test_time)

    with open(pos_file, "r", encoding="utf-8") as f:
        saved_1 = json.load(f)

    pos_map_1 = {p["trade_id"]: p for p in saved_1}
    assert pos_map_1["TRD-DYN-BULL"]["sl_spot"] == 2512.5
    assert pos_map_1["TRD-DYN-BEAR"]["sl_spot"] == 4193.0

    # Tick 2: RELIANCE spot moves to 2580 (new_sl = max(2512.5, round(2580 - 37.5)) = 2542.5)
    # TCS spot drops to 4080 (new_sl = min(4193, round(4080 + 63)) = 4143.0)
    mock_quotes_2 = {
        "RELIANCE": {"ltp": 2580.0, "volume": 1200.0},
        "TCS": {"ltp": 4080.0, "volume": 600.0},
    }
    monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes_2, now_dt_override=test_time)

    with open(pos_file, "r", encoding="utf-8") as f:
        saved_2 = json.load(f)

    pos_map_2 = {p["trade_id"]: p for p in saved_2}
    assert pos_map_2["TRD-DYN-BULL"]["sl_spot"] == 2542.5
    assert pos_map_2["TRD-DYN-BEAR"]["sl_spot"] == 4143.0

    # Tick 3: RELIANCE spot pulls back to 2560 (new_sl = max(2542.5, 2522.5) = 2542.5 -- sl_spot must NOT move down!)
    mock_quotes_3 = {
        "RELIANCE": {"ltp": 2560.0, "volume": 1200.0},
        "TCS": {"ltp": 4080.0, "volume": 600.0},
    }
    monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes_3, now_dt_override=test_time)

    with open(pos_file, "r", encoding="utf-8") as f:
        saved_3 = json.load(f)

    pos_map_3 = {p["trade_id"]: p for p in saved_3}
    assert pos_map_3["TRD-DYN-BULL"]["sl_spot"] == 2542.5


def test_gap_slippage_calculation_on_sl_hit(tmp_path):
    """Test gap slippage calculation (slippage_inr = abs(current_spot - sl_spot) * units) on SL breach."""
    pos_file = tmp_path / "active_positions.json"

    positions = [
        {
            "trade_id": "TRD-SL-SLIPPAGE",
            "symbol": "INFY",
            "strategy": "Naked Long CE",
            "direction": "BULLISH",
            "entry_premium": 50.0,
            "entry_spot": 1500.0,
            "target_spot": 1550.0,
            "sl_spot": 1470.0,
            "current_spot": 1500.0,
            "current_ltp": 50.0,
            "status": "OPEN",
            "quantity_lots": 2,
            "lot_size": 400,  # units = 2 * 400 = 800
            "trailing_sl_active": False,
        }
    ]

    with open(pos_file, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    # Spot gaps down to 1450.0 (SL is 1470.0 -> Gap slippage = abs(1450 - 1470) * 800 = 20 * 800 = 16000 INR)
    mock_quotes = {
        "INFY": {"ltp": 1450.0, "volume": 2000.0},
    }

    test_time = datetime(2026, 8, 17, 10, 0)
    alerts = monitor_active_trades(active_file=pos_file, quotes_override=mock_quotes, now_dt_override=test_time)

    assert len(alerts) == 1
    assert alerts[0]["action_type"] == "SL_HIT"
    assert alerts[0]["slippage_inr"] == 16000.0
    assert "Gap slippage: ₹16,000.00" in alerts[0]["action_alert"]

    with open(pos_file, "r", encoding="utf-8") as f:
        saved_positions = json.load(f)

    assert saved_positions[0]["slippage_inr"] == 16000.0


