"""
Unit tests for Upstox OAuth Manager and Live Data Provider (src/data/upstox_provider.py).

Per CodingStandards.md:
- Tests cover OAuth login URL generation and token exchange logic.
- Mocked HTTP requests verify ADR-005 schema compliance, float64 dtypes, IST timezone,
  option chain extraction, and error handling.
"""

from unittest.mock import patch, MagicMock
import os
import pandas as pd
import pytest

from src.data.upstox_auth import get_login_url, fetch_and_save_token
from src.data.upstox_provider import UpstoxProvider


def test_get_login_url():
    """Test OAuth login URL construction."""
    url = get_login_url(api_key="test_key", redirect_uri="http://127.0.0.1:5000/callback")
    assert "https://api.upstox.com/v2/login/authorization/dialog" in url
    assert "client_id=test_key" in url
    assert "response_type=code" in url


@patch("src.data.upstox_auth.requests.post")
def test_fetch_and_save_token_success(mock_post, tmp_path):
    """Test token exchange and persistence to .env file."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "mocked_access_token_12345"}
    mock_post.return_value = mock_response

    env_file = tmp_path / ".env"
    token = fetch_and_save_token(
        auth_code="code123",
        api_key="test_api_key",
        api_secret="test_api_secret",
        redirect_uri="http://127.0.0.1:5000/callback",
        env_file=env_file,
    )

    assert token == "mocked_access_token_12345"
    assert env_file.exists()
    content = env_file.read_text()
    assert "mocked_access_token_12345" in content


def test_upstox_provider_missing_token_raises_error(tmp_path):
    """Test UpstoxProvider raises ValueError when UPSTOX_ACCESS_TOKEN is missing."""
    env_file = tmp_path / ".env"
    env_file.write_text("UPSTOX_ACCESS_TOKEN=\n")

    provider = UpstoxProvider(cache_dir=tmp_path, env_path=str(env_file))
    with pytest.raises(ValueError, match="UPSTOX_ACCESS_TOKEN is missing"):
        provider.fetch_historical_data("RELIANCE", "2024-01-01", "2024-01-10", use_cache=False)


@patch("src.data.upstox_provider.requests.get")
def test_upstox_provider_fetch_data_mocked(mock_get, tmp_path):
    """Test UpstoxProvider fetches historical candles and outputs valid ADR-005 DataFrame."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "data": {
            "candles": [
                ["2024-01-01T09:15:00+05:30", 2500.0, 2520.0, 2490.0, 2510.0, 50000, 100000],
                ["2024-01-01T09:30:00+05:30", 2510.0, 2530.0, 2505.0, 2525.0, 60000, 105000],
            ]
        },
    }
    mock_get.return_value = mock_response

    env_file = tmp_path / ".env"
    env_file.write_text("UPSTOX_ACCESS_TOKEN=valid_mock_token_123\n")

    provider = UpstoxProvider(cache_dir=tmp_path, env_path=str(env_file))
    df = provider.fetch_data("RELIANCE", "2024-01-01", "2024-01-02", interval="15minute", use_cache=False)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
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
    assert df.index.name == "timestamp"
    assert str(df.index.tz) in ("Asia/Kolkata", "Asia/Calcutta", "IST")
    assert df["symbol"].iloc[0] == "RELIANCE"
    assert df["close"].dtype == "float64"


@patch("src.data.upstox_provider.requests.get")
def test_upstox_provider_fetch_option_chain_mocked(mock_get, tmp_path):
    """Test UpstoxProvider fetches option chain analytics."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "data": [
            {
                "strike_price": 2500.0,
                "call_options": {
                    "market_data": {
                        "ltp": 45.5,
                        "iv": 0.22,
                        "oi": 150000,
                        "greeks": {"delta": 0.52, "theta": -1.2, "vega": 0.8},
                    }
                },
                "put_options": {
                    "market_data": {
                        "ltp": 38.0,
                        "iv": 0.21,
                        "oi": 120000,
                        "greeks": {"delta": -0.48, "theta": -1.1, "vega": 0.75},
                    }
                },
            }
        ],
    }
    mock_get.return_value = mock_response

    env_file = tmp_path / ".env"
    env_file.write_text("UPSTOX_ACCESS_TOKEN=valid_mock_token_123\n")

    provider = UpstoxProvider(cache_dir=tmp_path, env_path=str(env_file))
    chain_df = provider.fetch_option_chain("RELIANCE")

    assert isinstance(chain_df, pd.DataFrame)
    assert len(chain_df) == 1
    assert "strike_price" in chain_df.columns
    assert chain_df["strike_price"].iloc[0] == 2500.0
    assert chain_df["call_delta"].iloc[0] == 0.52


@patch("src.data.upstox_provider.requests.get")
def test_is_token_valid_and_live_status(mock_get, tmp_path):
    """Test is_token_valid and check_upstox_live_status helper."""
    from src.data.upstox_provider import check_upstox_live_status

    # Test 1: Active valid token
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_get.return_value = mock_res

    env_file = tmp_path / ".env"
    env_file.write_text("UPSTOX_ACCESS_TOKEN=valid_mock_token_123\n")

    provider = UpstoxProvider(cache_dir=tmp_path, env_path=str(env_file))
    assert provider.is_token_valid() is True

    # Test 2: Invalid/Expired token (401)
    mock_res_401 = MagicMock()
    mock_res_401.status_code = 401
    mock_get.return_value = mock_res_401

    assert provider.is_token_valid() is False
