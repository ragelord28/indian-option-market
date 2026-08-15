"""
Unit tests for D-1 Nightly Scanner (src/scanner/eod_scanner.py).

Per CodingStandards.md:
- Tests verify indicator calculation (ADX, ATR, HV, EMA, RSI, ROC).
- Tests verify gap veto logic and watchlist export structure.
"""

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.scanner.eod_scanner import calculate_indicators, run_eod_scanner, check_morning_gap_veto


@pytest.fixture
def mock_daily_df() -> pd.DataFrame:
    """Fixture returning 60 days of mock daily price data for indicator testing."""
    dates = pd.date_range("2024-01-01", periods=60, freq="D", tz="Asia/Kolkata")
    prices = [100.0 + (i * 0.5) for i in range(60)]
    df = pd.DataFrame(
        {
            "symbol": ["RELIANCE"] * 60,
            "open": prices,
            "high": [p + 2.0 for p in prices],
            "low": [p - 1.0 for p in prices],
            "close": prices,
            "adj_close": prices,
            "volume": [100000] * 60,
            "open_interest": [500000] * 60,
        },
        index=dates,
    )
    df.index.name = "timestamp"
    return df


def test_calculate_indicators(mock_daily_df: pd.DataFrame):
    """Test indicators calculation (ema_20, ema_50, atr_14, adx_14, rsi_14, roc_12, hv_20)."""
    ind_df = calculate_indicators(mock_daily_df)

    assert "ema_20" in ind_df.columns
    assert "ema_50" in ind_df.columns
    assert "atr_14" in ind_df.columns
    assert "adx_14" in ind_df.columns
    assert "rsi_14" in ind_df.columns
    assert "roc_12" in ind_df.columns
    assert "hv_20" in ind_df.columns
    assert ind_df["ema_20"].iloc[-1] > 0.0
    assert ind_df["atr_14"].iloc[-1] > 0.0


def test_check_morning_gap_veto():
    """Test 09:15 AM morning opening gap veto logic."""
    # Gap = 2.0, max_allowed = 1.5 * 1.0 = 1.5 -> VETO
    is_vetoed, msg = check_morning_gap_veto(open_price=102.0, prev_close=100.0, atr_14=1.0)
    assert is_vetoed is True
    assert "VETO" in msg

    # Gap = 0.5, max_allowed = 1.5 * 1.0 = 1.5 -> PASS
    is_vetoed, msg = check_morning_gap_veto(open_price=100.5, prev_close=100.0, atr_14=1.0)
    assert is_vetoed is False
    assert "PASS" in msg


def test_run_eod_scanner_exports_valid_files(tmp_path):
    """Test scanner execution over a small universe exports valid JSON and Markdown files."""
    test_universe = ["RELIANCE", "TCS"]
    res = run_eod_scanner(universe=test_universe, output_dir=tmp_path, min_conviction_score=0.0)

    assert isinstance(res, dict)
    assert "top_bullish" in res
    assert "top_bearish" in res
    assert "top_volatility_harvest" in res

    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")

    json_file = tmp_path / "watchlist_latest.json"
    md_file = tmp_path / "watchlist_latest.md"
    archive_json_file = tmp_path / f"watchlist_{today_str}.json"
    archive_md_file = tmp_path / f"watchlist_{today_str}.md"

    assert json_file.exists()
    assert md_file.exists()
    assert archive_json_file.exists()
    assert archive_md_file.exists()

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert "timestamp" in data
        assert "total_scanned" in data
        assert data["total_scanned"] == 2

    md_content = md_file.read_text(encoding="utf-8")
    assert "# D-1 Actionable Nightly Watchlist Briefing" in md_content
