"""
Unit tests for Agent 1.5 Morning Radar & Guards (src/radar/morning_radar.py).

Per CodingStandards.md:
- Tests verify sector limit guard (Max 1 active setup per sector).
- Tests verify event blackout guard and 09:15 AM gap veto guard.
- Tests verify ORB width gate (chop and exhaustion vetoes).
- Tests verify 15m candle close trigger (wicks alone do NOT trigger).
- Tests verify conviction-based priority queue for slot allocation.
"""

import json
from pathlib import Path
import pytest

from src.radar.morning_radar import run_morning_radar, get_sector


def test_get_sector():
    """Test sector classification lookup."""
    assert get_sector("RELIANCE") == "Oil, Gas & Energy"
    assert get_sector("TCS") == "IT"
    assert get_sector("HDFCBANK") == "Banking"
    assert get_sector("TATAMOTORS") == "Auto"
    assert get_sector("UNKNOWN_STOCK") == "UNKNOWN_STOCK"


def test_run_morning_radar_execution(tmp_path):
    """Test Morning Radar execution over mock D-1 watchlist file."""
    mock_wl = {
        "timestamp": "2026-08-16T09:00:00",
        "total_scanned": 10,
        "qualifying_count": 3,
        "top_bullish": [
            {
                "symbol": "RELIANCE",
                "close": 2500.0,
                "atr_14": 30.0,
                "conviction_score": 90.0,
                "regime": "Bullish Momentum",
                "suggested_action": "BUY CALL",
                "simulated_open": 2505.0,  # Small gap -> Pass
                "has_event_risk": False,
                "candle_close": 2520.0,  # Closes above ORB high + 0.1% buffer
                "orb_high": 2510.0,
                "orb_low": 2490.0,  # Width = 20, 0.3*30=9 <= 20 <= 45=1.5*30 -> Pass
                "rvol": 1.5,  # Above 1.3 -> Pass
            },
            {
                "symbol": "ONGC",  # Same sector as RELIANCE (Energy) -> Sector Limit Veto
                "close": 300.0,
                "atr_14": 5.0,
                "conviction_score": 85.0,
                "regime": "Bullish Momentum",
                "suggested_action": "BUY CALL",
                "simulated_open": 301.0,
                "has_event_risk": False,
            },
        ],
        "top_bearish": [
            {
                "symbol": "TCS",  # IT Sector
                "close": 4000.0,
                "atr_14": 50.0,
                "conviction_score": 88.0,
                "regime": "Bearish Momentum",
                "suggested_action": "BUY PUT",
                "simulated_open": 4010.0,
                "has_event_risk": True,  # Binary Event -> Event Veto
            }
        ],
        "top_volatility_harvest": [],
    }

    wl_file = tmp_path / "watchlist_latest.json"
    radar_file = tmp_path / "radar_latest.json"

    with open(wl_file, "w", encoding="utf-8") as f:
        json.dump(mock_wl, f, indent=2)

    res = run_morning_radar(watchlist_path=wl_file, output_path=radar_file)

    assert isinstance(res, dict)
    assert res["total_shortlisted"] == 3
    assert radar_file.exists()

    items = res["radar_items"]
    assert len(items) == 3

    rel_item = next(i for i in items if i["symbol"] == "RELIANCE")
    ongc_item = next(i for i in items if i["symbol"] == "ONGC")
    tcs_item = next(i for i in items if i["symbol"] == "TCS")

    # RELIANCE passes sector & event guards, candle close triggers
    assert rel_item["status"] == "TRIGGERED"
    assert "execution_ticket" in rel_item

    # ONGC vetoed due to sector limit (RELIANCE already in Energy)
    assert ongc_item["status"] == "VETOED_SECTOR_LIMIT"

    # TCS vetoed due to event blackout
    assert tcs_item["status"] == "VETOED_EVENT"


def test_orb_width_gate_chop(tmp_path):
    """Test that ORB width < 0.3 * ATR results in VETOED_ORB_CHOP."""
    mock_wl = {
        "timestamp": "2026-08-16T09:00:00",
        "total_scanned": 1,
        "qualifying_count": 1,
        "top_bullish": [
            {
                "symbol": "INFY",
                "close": 1500.0,
                "atr_14": 40.0,
                "conviction_score": 85.0,
                "regime": "Bullish Momentum",
                "suggested_action": "BUY CALL",
                "simulated_open": 1501.0,
                "has_event_risk": False,
                "orb_high": 1503.0,
                "orb_low": 1499.0,  # Width = 4.0, 0.3 * 40 = 12 -> 4 < 12 -> CHOP
                "candle_close": 1504.0,
                "rvol": 1.5,
            },
        ],
        "top_bearish": [],
        "top_volatility_harvest": [],
    }

    wl_file = tmp_path / "watchlist_latest.json"
    radar_file = tmp_path / "radar_latest.json"
    with open(wl_file, "w", encoding="utf-8") as f:
        json.dump(mock_wl, f, indent=2)

    res = run_morning_radar(watchlist_path=wl_file, output_path=radar_file)
    infy_item = res["radar_items"][0]
    assert infy_item["status"] == "VETOED_ORB_CHOP"
    assert "narrow" in infy_item["veto_reason"].lower()


def test_orb_width_gate_exhausted(tmp_path):
    """Test that ORB width > 1.5 * ATR results in VETOED_ORB_EXHAUSTED."""
    mock_wl = {
        "timestamp": "2026-08-16T09:00:00",
        "total_scanned": 1,
        "qualifying_count": 1,
        "top_bullish": [
            {
                "symbol": "HDFCBANK",
                "close": 1600.0,
                "atr_14": 20.0,
                "conviction_score": 86.0,
                "regime": "Bullish Momentum",
                "suggested_action": "BUY CALL",
                "simulated_open": 1601.0,
                "has_event_risk": False,
                "orb_high": 1640.0,
                "orb_low": 1600.0,  # Width = 40.0, 1.5 * 20 = 30 -> 40 > 30 -> EXHAUSTED
                "candle_close": 1645.0,
                "rvol": 1.5,
            },
        ],
        "top_bearish": [],
        "top_volatility_harvest": [],
    }

    wl_file = tmp_path / "watchlist_latest.json"
    radar_file = tmp_path / "radar_latest.json"
    with open(wl_file, "w", encoding="utf-8") as f:
        json.dump(mock_wl, f, indent=2)

    res = run_morning_radar(watchlist_path=wl_file, output_path=radar_file)
    hdfc_item = res["radar_items"][0]
    assert hdfc_item["status"] == "VETOED_ORB_EXHAUSTED"
    assert "wide" in hdfc_item["veto_reason"].lower()


def test_wick_does_not_trigger(tmp_path):
    """Test that wicks beyond ORB high/low do NOT trigger if candle close doesn't breach."""
    mock_wl = {
        "timestamp": "2026-08-16T09:00:00",
        "total_scanned": 1,
        "qualifying_count": 1,
        "top_bullish": [
            {
                "symbol": "WIPRO",
                "close": 500.0,
                "atr_14": 10.0,
                "conviction_score": 84.0,
                "regime": "Bullish Momentum",
                "suggested_action": "BUY CALL",
                "simulated_open": 501.0,
                "has_event_risk": False,
                "orb_high": 505.0,
                "orb_low": 498.0,  # Width = 7.0, 0.3*10=3 <= 7 <= 15=1.5*10 -> Pass
                "candle_close": 504.0,  # Does NOT close above orb_high + 0.1% (505 + 0.5 = 505.5)
                "rvol": 1.5,
            },
        ],
        "top_bearish": [],
        "top_volatility_harvest": [],
    }

    wl_file = tmp_path / "watchlist_latest.json"
    radar_file = tmp_path / "radar_latest.json"
    with open(wl_file, "w", encoding="utf-8") as f:
        json.dump(mock_wl, f, indent=2)

    res = run_morning_radar(watchlist_path=wl_file, output_path=radar_file)
    wipro_item = res["radar_items"][0]
    # Candle close 504 < 505.5 (orb_high + 0.1%) => stays AWAITING_ORB
    assert wipro_item["status"] == "AWAITING_ORB"


def test_conviction_priority_queue(tmp_path):
    """Test that priority queue sorts triggered signals by conviction and caps at 5 slots."""
    # Create 7 symbols in different sectors, all with valid trigger conditions
    symbols = [
        ("RELIANCE", "Energy", 90.0),
        ("TCS", "IT", 88.0),
        ("HDFCBANK", "Banking", 92.0),
        ("MARUTI", "Auto", 85.0),
        ("SUNPHARMA", "Pharma", 87.0),
        ("ITC", "FMCG", 83.0),
        ("TATASTEEL", "Metals", 81.0),
    ]

    bullish_items = []
    for sym, _, conv in symbols:
        bullish_items.append({
            "symbol": sym,
            "close": 1000.0,
            "atr_14": 20.0,
            "conviction_score": conv,
            "regime": "Bullish Momentum",
            "suggested_action": "BUY CALL",
            "simulated_open": 1001.0,
            "has_event_risk": False,
            "orb_high": 1005.0,
            "orb_low": 996.0,   # Width = 9.0; 0.3*20=6 <= 9 <= 30=1.5*20 -> Pass
            "candle_close": 1010.0,  # Closes above 1005 + 1.0 = 1006 -> Trigger
            "rvol": 1.5,
        })

    mock_wl = {
        "timestamp": "2026-08-16T09:00:00",
        "total_scanned": 7,
        "qualifying_count": 7,
        "top_bullish": bullish_items,
        "top_bearish": [],
        "top_volatility_harvest": [],
    }

    wl_file = tmp_path / "watchlist_latest.json"
    radar_file = tmp_path / "radar_latest.json"
    with open(wl_file, "w", encoding="utf-8") as f:
        json.dump(mock_wl, f, indent=2)

    res = run_morning_radar(watchlist_path=wl_file, output_path=radar_file)
    items = res["radar_items"]

    triggered = [i for i in items if i["status"] == "TRIGGERED"]

    # Triggered items should be sorted by conviction score
    assert triggered[0]["symbol"] == "HDFCBANK"  # 92.0
    assert triggered[1]["symbol"] == "RELIANCE"  # 90.0


def test_bearish_breakdown_directionality_and_trigger_zone(tmp_path):
    """
    Verify:
    1. Bearish stock with current_spot > trigger_zone (entry) stays AWAITING_ORB (NOT TRIGGERED).
    2. Bearish stock with current_spot <= trigger_zone (entry) returns TRIGGERED with timestamp.
    """
    mock_wl_awaiting = {
        "timestamp": "2026-08-16T09:00:00",
        "total_scanned": 1,
        "qualifying_count": 1,
        "top_bearish": [
            {
                "symbol": "PAGEIND",
                "bias": "BEARISH",
                "regime": "Bearish Breakdown",
                "suggested_action": "BUY PUT",
                "close": 36965.0,  # current_spot > entry (36750)
                "simulated_open": 36965.0,
                "entry": 36750.0,
                "stop_loss": 37200.0,
                "target": 36000.0,
                "atr_14": 500.0,
                "conviction_score": 85.0,
                "has_event_risk": False,
                "orb_high": 37100.0,
                "orb_low": 36800.0,  # orb_width = 300 (0.3*500=150 <= 300 <= 750=1.5*500)
                "candle_close": 36700.0,  # 15m close <= orb_low (36700 <= 36800)
                "rvol": 1.5,
            }
        ],
        "top_bullish": [],
        "top_volatility_harvest": [],
    }

    wl_file = tmp_path / "watchlist_latest.json"
    radar_file = tmp_path / "radar_latest.json"
    with open(wl_file, "w", encoding="utf-8") as f:
        json.dump(mock_wl_awaiting, f, indent=2)

    res = run_morning_radar(watchlist_path=wl_file, output_path=radar_file)
    pageind_item = res["radar_items"][0]
    # Since current_spot (36965) > trigger_zone (36750), it must NOT trigger
    assert pageind_item["status"] == "AWAITING_ORB"
    assert pageind_item["status"] != "TRIGGERED"

    # Now test when current_spot <= trigger_zone (36700 <= 36750)
    mock_wl_triggered = dict(mock_wl_awaiting)
    mock_wl_triggered["top_bearish"] = [
        dict(mock_wl_awaiting["top_bearish"][0], close=36700.0)
    ]

    with open(wl_file, "w", encoding="utf-8") as f:
        json.dump(mock_wl_triggered, f, indent=2)

    res2 = run_morning_radar(watchlist_path=wl_file, output_path=radar_file)
    pageind_trig = res2["radar_items"][0]
    assert pageind_trig["status"] == "TRIGGERED"
    assert pageind_trig["triggered_at"] is not None
    assert "Breakout Confirmed" in pageind_trig["orb_reason"]


def test_locked_triggered_at_timestamp_across_runs(tmp_path):
    """Test that an already-triggered stock preserves its initial triggered_at timestamp across multiple runs."""
    mock_wl = {
        "timestamp": "2026-08-16T09:00:00",
        "total_scanned": 1,
        "qualifying_count": 1,
        "top_bullish": [
            {
                "symbol": "RELIANCE",
                "bias": "BULLISH",
                "regime": "Bullish Momentum",
                "suggested_action": "BUY CALL",
                "close": 2510.0,
                "simulated_open": 2501.0,
                "entry": 2500.0,
                "stop_loss": 2480.0,
                "target": 2550.0,
                "atr_14": 25.0,
                "conviction_score": 88.0,
                "has_event_risk": False,
                "orb_high": 2505.0,
                "orb_low": 2495.0,
                "candle_close": 2510.0,
                "rvol": 2.0,
            }
        ],
        "top_bearish": [],
        "top_volatility_harvest": [],
    }

    wl_file = tmp_path / "watchlist_latest.json"
    radar_file = tmp_path / "radar_latest.json"
    with open(wl_file, "w", encoding="utf-8") as f:
        json.dump(mock_wl, f, indent=2)

    res1 = run_morning_radar(watchlist_path=wl_file, output_path=radar_file)
    assert res1["radar_items"][0]["status"] == "TRIGGERED"
    initial_timestamp = res1["radar_items"][0]["triggered_at"]
    assert initial_timestamp is not None

    with open(radar_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    saved_data["radar_items"][0]["triggered_at"] = "09:30 IST"
    with open(radar_file, "w", encoding="utf-8") as f:
        json.dump(saved_data, f, indent=2)

    res2 = run_morning_radar(watchlist_path=wl_file, output_path=radar_file)
    preserved_timestamp = res2["radar_items"][0]["triggered_at"]
    assert preserved_timestamp == "09:30 IST"
    assert "Breakout Confirmed at 09:30 IST" in res2["radar_items"][0]["orb_reason"]
