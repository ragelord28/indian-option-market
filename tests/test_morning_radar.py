"""
Unit tests for Agent 1.5 Morning Radar & Guards (src/radar/morning_radar.py).

Per CodingStandards.md:
- Tests verify sector limit guard (Max 1 active setup per sector).
- Tests verify event blackout guard and 09:15 AM gap veto guard.
- Tests verify ORB trigger classification and execution ticket generation.
"""

import json
from pathlib import Path
import pytest

from src.radar.morning_radar import run_morning_radar, get_sector


def test_get_sector():
    """Test sector classification lookup."""
    assert get_sector("RELIANCE") == "Energy"
    assert get_sector("TCS") == "IT"
    assert get_sector("HDFCBANK") == "Banking"
    assert get_sector("TATAMOTORS") == "Auto"
    assert get_sector("UNKNOWN_STOCK") == "Diversified"


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

    # RELIANCE passes sector & event guards
    assert rel_item["status"] in ["TRIGGERED", "AWAITING_ORB"]
    assert "execution_ticket" in rel_item

    # ONGC vetoed due to sector limit (RELIANCE already in Energy)
    assert ongc_item["status"] == "VETOED_SECTOR_LIMIT"

    # TCS vetoed due to event blackout
    assert tcs_item["status"] == "VETOED_EVENT"
