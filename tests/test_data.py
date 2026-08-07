"""
Unit tests for Data Ingestion Layer (src/data/).

Per CodingStandards.md:
- Tests mirror src/ structure (src/data/ -> tests/test_data.py).
- Tests cover schema validation, YahooFinanceProvider data fetching,
  IST timezone handling, internal symbol enforcement, and Parquet caching.
"""

from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd
import pytest

from src.data.base_provider import validate_schema, BaseDataProvider
from src.data.yahoo_provider import YahooFinanceProvider, DEFAULT_CACHE_DIR


@pytest.fixture
def sample_valid_df() -> pd.DataFrame:
    """Fixture returning a valid ADR-005 compliant DataFrame."""
    dates = pd.date_range(start="2024-01-01", periods=5, freq="D", tz="Asia/Kolkata")
    df = pd.DataFrame(
        {
            "symbol": ["RELIANCE"] * 5,
            "open": [2500.0, 2510.0, 2505.0, 2520.0, 2530.0],
            "high": [2520.0, 2530.0, 2525.0, 2540.0, 2550.0],
            "low": [2490.0, 2500.0, 2495.0, 2510.0, 2520.0],
            "close": [2515.0, 2505.0, 2520.0, 2535.0, 2545.0],
            "adj_close": [2510.0, 2500.0, 2515.0, 2530.0, 2540.0],
            "volume": [1000000, 1200000, 1100000, 1300000, 1400000],
            "open_interest": [np.nan] * 5,
        },
        index=dates,
    )
    df.index.name = "timestamp"
    return df


def test_validate_schema_valid(sample_valid_df: pd.DataFrame):
    """Test that a compliant DataFrame passes schema validation."""
    res = validate_schema(sample_valid_df)
    assert isinstance(res, pd.DataFrame)
    assert res.index.name == "timestamp"
    assert str(res.index.tz) == "Asia/Kolkata"


def test_validate_schema_naive_timezone_fails(sample_valid_df: pd.DataFrame):
    """Test that a naive timestamp index fails schema validation."""
    df = sample_valid_df.copy()
    df.index = df.index.tz_localize(None)  # Remove timezone info
    with pytest.raises(ValueError, match="must be timezone-aware"):
        validate_schema(df)


def test_validate_schema_wrong_timezone_fails(sample_valid_df: pd.DataFrame):
    """Test that a non-IST timezone index fails schema validation."""
    df = sample_valid_df.copy()
    df.index = df.index.tz_convert("UTC")
    with pytest.raises(ValueError, match="must be in Asia/Kolkata timezone"):
        validate_schema(df)


def test_validate_schema_missing_column_fails(sample_valid_df: pd.DataFrame):
    """Test that missing required columns fail schema validation."""
    df = sample_valid_df.drop(columns=["adj_close"])
    with pytest.raises(ValueError, match="columns do not match ADR-005 standard"):
        validate_schema(df)


def test_validate_schema_invalid_symbol_suffix_fails(sample_valid_df: pd.DataFrame):
    """Test that provider-specific symbol suffixes fail schema validation."""
    df = sample_valid_df.copy()
    df["symbol"] = "RELIANCE.NS"
    with pytest.raises(ValueError, match="Invalid internal symbol 'RELIANCE.NS'"):
        validate_schema(df)


def test_validate_schema_lowercase_symbol_fails(sample_valid_df: pd.DataFrame):
    """Test that lowercase symbols fail schema validation."""
    df = sample_valid_df.copy()
    df["symbol"] = "reliance"
    with pytest.raises(ValueError, match="Invalid internal symbol 'reliance'"):
        validate_schema(df)


def test_validate_schema_special_symbols_valid(sample_valid_df: pd.DataFrame):
    """Test that Indian stock symbols with & and - (M&M, BAJAJ-AUTO) pass schema validation."""
    df_mm = sample_valid_df.copy()
    df_mm["symbol"] = "M&M"
    assert validate_schema(df_mm) is not None

    df_bajaj = sample_valid_df.copy()
    df_bajaj["symbol"] = "BAJAJ-AUTO"
    assert validate_schema(df_bajaj) is not None


def test_validate_schema_non_float64_price_dtype_fails(sample_valid_df: pd.DataFrame):
    """Test that price columns of non-float64 dtype (e.g. int64, float32) fail schema validation."""
    df_int = sample_valid_df.copy()
    df_int["close"] = df_int["close"].astype("int64")
    with pytest.raises(ValueError, match="Column 'close' must be of dtype float64"):
        validate_schema(df_int)

    df_f32 = sample_valid_df.copy()
    df_f32["open"] = df_f32["open"].astype("float32")
    with pytest.raises(ValueError, match="Column 'open' must be of dtype float64"):
        validate_schema(df_f32)


def test_yahoo_provider_symbol_mapping():
    """Test mapping from internal symbols to Yahoo Finance tickers."""
    provider = YahooFinanceProvider()
    assert provider._get_provider_ticker("RELIANCE") == "RELIANCE.NS"
    assert provider._get_provider_ticker("M&M") == "M&M.NS"
    assert provider._get_provider_ticker("BAJAJ-AUTO") == "BAJAJ-AUTO.NS"
    assert provider._get_provider_ticker("TCS") == "TCS.NS"
    assert provider._get_provider_ticker("NIFTY50") == "^NSEI"
    assert provider._get_provider_ticker("BANKNIFTY") == "^NSEBANK"
    assert provider._get_provider_ticker("RELIANCE.NS") == "RELIANCE.NS"
    assert provider._get_provider_ticker("^NSEI") == "^NSEI"


def test_yahoo_provider_cache_filename_format():
    """Test cache filename formatting with exact date range."""
    provider = YahooFinanceProvider(cache_dir="data/cache")
    path = provider.get_cache_filepath("RELIANCE", "2024-01-01", "2024-06-01", "1d")
    assert path.name == "RELIANCE_1d_20240101_20240601.parquet"


@patch("yfinance.download")
def test_yahoo_provider_fetch_data_mocked(mock_download: MagicMock):
    """Test YahooFinanceProvider fetching and transforming raw data correctly."""
    # Setup mock yfinance response
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    raw_df = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [105.0, 106.0, 107.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [104.0, 105.0, 106.0],
            "Adj Close": [103.5, 104.5, 105.5],
            "Volume": [5000, 6000, 7000],
        },
        index=dates,
    )
    mock_download.return_value = raw_df

    with tempfile.TemporaryDirectory() as tmp_dir:
        provider = YahooFinanceProvider(cache_dir=tmp_dir)
        df = provider.fetch_historical_data(
            symbol="RELIANCE",
            start_date="2024-01-01",
            end_date="2024-01-03",
            timeframe="1d",
            use_cache=True,
        )

        # Verify yfinance download argument
        mock_download.assert_called_once_with(
            "RELIANCE.NS",
            start="2024-01-01",
            end="2024-01-03",
            interval="1d",
            auto_adjust=False,
            progress=False,
        )

        # Verify schema compliance
        assert list(df.columns) == [
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "adj_close",
            "volume",
            "open_interest",
        ]
        assert df["symbol"].iloc[0] == "RELIANCE"
        assert str(df.index.tz) == "Asia/Kolkata"
        assert np.isnan(df["open_interest"].iloc[0])

        # Verify cache file creation
        expected_cache_file = (
            Path(tmp_dir) / "RELIANCE_1d_20240101_20240103.parquet"
        )
        assert expected_cache_file.exists()


@patch("yfinance.download")
def test_yahoo_provider_cache_hit(mock_download: MagicMock):
    """Test that subsequent calls use the local cache file and do not call yfinance."""
    dates = pd.date_range("2024-01-01", periods=2, freq="D")
    raw_df = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [105.0, 106.0],
            "Low": [99.0, 100.0],
            "Close": [104.0, 105.0],
            "Adj Close": [104.0, 105.0],
            "Volume": [5000, 6000],
        },
        index=dates,
    )
    mock_download.return_value = raw_df

    with tempfile.TemporaryDirectory() as tmp_dir:
        provider = YahooFinanceProvider(cache_dir=tmp_dir)

        # First call downloads and populates cache
        df1 = provider.fetch_historical_data(
            "TCS", "2024-01-01", "2024-01-02", use_cache=True
        )
        assert mock_download.call_count == 1

        # Second call should read directly from parquet cache without re-downloading
        df2 = provider.fetch_historical_data(
            "TCS", "2024-01-01", "2024-01-02", use_cache=True
        )
        assert mock_download.call_count == 1  # Still 1 call!

        pd.testing.assert_frame_equal(df1, df2)


@patch("yfinance.download")
def test_yahoo_provider_empty_data_raises_error(mock_download: MagicMock):
    """Test that empty response from provider raises ValueError."""
    mock_download.return_value = pd.DataFrame()  # Empty dataframe

    with tempfile.TemporaryDirectory() as tmp_dir:
        provider = YahooFinanceProvider(cache_dir=tmp_dir)
        with pytest.raises(ValueError, match="No data returned from Yahoo Finance"):
            provider.fetch_historical_data("INVALID_STOCK", "2024-01-01", "2024-01-02")
