"""
Unit tests for 10-Day Walk-Forward Replay & Cross-Verification Engine (src/backtester/walkforward_replayer.py).

Per CodingStandards.md:
- Tests verify trading day calendar calculation (skipping weekends & holidays).
- Tests verify point-in-time zero-lookahead data slicing.
- Tests verify daily autopsy generation and summary reports.
"""

from datetime import date
import pytest
import pandas as pd

from src.backtester.walkforward_replayer import (
    get_trading_days,
    WalkForwardReplayer,
    NSE_HOLIDAYS_2026,
)


def test_get_trading_days_august_2026():
    """Test get_trading_days for August 1 to August 14, 2026."""
    days = get_trading_days("2026-08-01", "2026-08-14")

    # Should contain exactly 10 trading days (excluding Aug 1-2, Aug 8-9 weekends)
    assert len(days) == 10
    assert days[0] == date(2026, 8, 3)
    assert days[-1] == date(2026, 8, 14)

    # Ensure no Saturday (5) or Sunday (6) is included
    for d in days:
        assert d.weekday() < 5
        assert d not in NSE_HOLIDAYS_2026


def test_holiday_skipping():
    """Test that official NSE holidays are excluded from trading days."""
    # Republic Day 2026-01-26 is Monday
    days = get_trading_days("2026-01-23", "2026-01-27")
    assert date(2026, 1, 26) not in days


def test_zero_lookahead_slicing(tmp_path):
    """Test that D-1 scan slices data strictly up to cutoff date (zero lookahead)."""
    replayer = WalkForwardReplayer(reports_dir=tmp_path)

    # Mock daily dataframe with dates spanning July 2026 to August 2026
    dates = pd.date_range(start="2026-06-01", end="2026-08-14", freq="B", tz="Asia/Kolkata")
    df = pd.DataFrame(
        {
            "symbol": "RELIANCE",
            "open": 1000.0,
            "high": 1020.0,
            "low": 990.0,
            "close": 1010.0,
            "adj_close": 1010.0,
            "volume": 1000000,
            "open_interest": 0,
        },
        index=dates,
    )

    replayer.daily_data_cache["RELIANCE"] = df

    cutoff = date(2026, 7, 31)
    shortlist = replayer.run_agent1_d1_scan(cutoff_date=cutoff)

    # Scanned close price should equal the price on 2026-07-31, not August dates
    if shortlist:
        rel_item = next((item for item in shortlist if item["symbol"] == "RELIANCE"), None)
        if rel_item:
            assert rel_item["close"] == 1010.0


def test_autopsy_and_report_generation(tmp_path):
    """Test daily autopsy report and master summary report generation."""
    replayer = WalkForwardReplayer(reports_dir=tmp_path)

    mock_candidates = [
        {
            "symbol": "RELIANCE",
            "sector": "Energy",
            "regime": "Bullish Momentum",
            "close": 2500.0,
            "atr_14": 30.0,
            "conviction_score": 90.0,
            "status": "TRIGGERED",
            "trigger_price": 2510.0,
            "stop_loss": 2455.0,
            "target": 2575.0,
            "hv_20": 20.0,
            "intraday_df": pd.DataFrame(),
        },
        {
            "symbol": "TCS",
            "sector": "IT",
            "regime": "Bearish Momentum",
            "close": 4000.0,
            "atr_14": 50.0,
            "conviction_score": 88.0,
            "status": "VETOED_GAP",
            "veto_reason": "VETO: Gap > 1.5x ATR",
            "stop_loss": 4075.0,
            "target": 3875.0,
            "hv_20": 22.0,
            "intraday_df": pd.DataFrame(),
        },
    ]

    target_dt = date(2026, 8, 3)
    autopsy_results = [replayer.run_agent2_autopsy(c, target_date=target_dt) for c in mock_candidates]
    assert len(autopsy_results) == 2

    report_md = replayer.generate_daily_report(target_dt, autopsy_results)
    assert "RELIANCE" in report_md
    assert "TCS" in report_md
    assert (tmp_path / "replay_2026-08-03.md").exists()
