"""
Unit tests for D-1 Nightly Scanner (src/scanner/eod_scanner.py).

Per CodingStandards.md:
- Tests verify indicator calculation (ADX, ATR, HV, SMA).
- Tests verify JSON and Markdown export structure under data/watchlists/.
"""

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.scanner.eod_scanner import calculate_indicators, run_eod_scanner


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
    """Test indicators calculation (sma_20, sma_50, atr_14, adx_14, hv_20)."""
    ind_df = calculate_indicators(mock_daily_df)

    assert "sma_20" in ind_df.columns
    assert "sma_50" in ind_df.columns
    assert "atr_14" in ind_df.columns
    assert "adx_14" in ind_df.columns
    assert "hv_20" in ind_df.columns
    assert ind_df["sma_20"].iloc[-1] > 0.0
    assert ind_df["atr_14"].iloc[-1] > 0.0


def test_run_eod_scanner_exports_valid_files(tmp_path):
    """Test scanner execution over a small universe exports valid JSON and Markdown files."""
    test_universe = ["RELIANCE", "TCS"]
    res = run_eod_scanner(universe=test_universe, output_dir=tmp_path)

    assert isinstance(res, dict)
    assert "top_bullish" in res
    assert "top_bearish" in res
    assert "top_volatility_harvest" in res

    json_file = tmp_path / "watchlist_latest.json"
    md_file = tmp_path / "watchlist_latest.md"

    assert json_file.exists()
    assert md_file.exists()

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert "timestamp" in data
        assert "total_scanned" in data
        assert data["total_scanned"] == 2

    md_content = md_file.read_text(encoding="utf-8")
    assert "# D-1 Actionable Nightly Watchlist Briefing" in md_content
