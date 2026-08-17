"""
Upstox API v2 Live Data Provider Adapter.

Implements BaseDataProvider to fetch real-time and historical OHLCV market data,
intraday candles, and option chain analytics from Upstox API v2, strictly enforcing
ADR-005 schema validation and local Parquet disk caching.
"""

from pathlib import Path
import os
import logging
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

from src.data.base_provider import BaseDataProvider, validate_schema

logger = logging.getLogger(__name__)

# Standard cache directory for Upstox provider
DEFAULT_CACHE_DIR = Path("data/cache")

# Upstox API v2 Base Endpoints
UPSTOX_BASE_URL = "https://api.upstox.com/v2"

# Standard mapping for index and popular equity instrument keys
INSTRUMENT_KEY_MAP = {
    "NIFTY50": "NSE_INDEX|Nifty 50",
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "RELIANCE": "NSE_EQ|INE002A01018",
    "TCS": "NSE_EQ|INE467B01029",
    "HDFCBANK": "NSE_EQ|INE040A01034",
    "INFY": "NSE_EQ|INE009A01021",
    "ICICIBANK": "NSE_EQ|INE090A01021",
    "SBIN": "NSE_EQ|INE062A01020",
    "BHARATFORG": "NSE_EQ|INE465A01025",
}


class UpstoxProvider(BaseDataProvider):
    """
    Adapter for fetching live intraday candles and option chains from Upstox API v2.
    """

    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR, env_path: str = ".env"):
        """
        Initialize the UpstoxProvider adapter.

        Args:
            cache_dir: Directory path for saving and reading Parquet cache files.
            env_path: Environment file path.
        """
        self.cache_dir = Path(cache_dir)
        load_dotenv(dotenv_path=env_path, override=True)
        self.access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
        self.api_key = os.getenv("UPSTOX_API_KEY", "").strip()

    def _get_instrument_key(self, symbol: str) -> str:
        """
        Map internal symbol to Upstox instrument key.
        """
        clean_symbol = symbol.strip().upper()
        if clean_symbol in INSTRUMENT_KEY_MAP:
            return INSTRUMENT_KEY_MAP[clean_symbol]

        # Standard equity instrument key fallback
        return f"NSE_EQ|{clean_symbol}"

    def get_cache_filepath(
        self, symbol: str, start_date: str, end_date: str, timeframe: str
    ) -> Path:
        """
        Generate Parquet cache filepath.
        """
        start_str = start_date.replace("-", "").replace("/", "")
        end_str = end_date.replace("-", "").replace("/", "")
        filename = f"UPSTOX_{symbol.upper()}_{timeframe}_{start_str}_{end_str}.parquet"
        return self.cache_dir / filename

    def fetch_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str = "15minute",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Alias for fetch_historical_data accepting interval argument."""
        return self.fetch_historical_data(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            timeframe=interval,
            use_cache=use_cache,
        )

    def fetch_historical_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = "15minute",
        use_cache: bool = True,
        **kwargs,
    ) -> pd.DataFrame:
        """
        Fetch historical candle data from Upstox API v2 or local cache.

        Args:
            symbol: Standardized symbol (e.g. 'RELIANCE', 'NIFTY50').
            start_date: Start date string ('YYYY-MM-DD').
            end_date: End date string ('YYYY-MM-DD').
            timeframe: Candle interval ('15minute', '1day', '1minute', etc.).
            use_cache: Whether to read/write Parquet disk cache.

        Returns:
            DataFrame adhering strictly to ADR-005.

        Raises:
            ValueError: If UPSTOX_ACCESS_TOKEN is missing or request fails.
        """
        if "interval" in kwargs:
            timeframe = kwargs["interval"]

        clean_symbol = symbol.strip().upper()
        norm_tf = timeframe.lower()

        # Map to valid Upstox API v2 interval strings: (1minute, 30minute, day, week, month)
        need_resample_15m = norm_tf in ("15m", "15minute")
        if need_resample_15m or norm_tf in ("1m", "1minute"):
            upstox_interval = "1minute"
        elif norm_tf in ("30m", "30minute"):
            upstox_interval = "30minute"
        elif norm_tf in ("1d", "day", "daily"):
            upstox_interval = "day"
        else:
            upstox_interval = norm_tf

        # Check local Parquet cache first
        cache_path = self.get_cache_filepath(
            clean_symbol, start_date, end_date, norm_tf
        )
        if use_cache and cache_path.exists():
            logger.info(f"Loading cached Upstox data for {clean_symbol} from {cache_path}")
            cached_df = pd.read_parquet(cache_path)
            if cached_df.index.tz is None:
                cached_df.index = cached_df.index.tz_localize("Asia/Kolkata")
            else:
                cached_df.index = cached_df.index.tz_convert("Asia/Kolkata")
            return validate_schema(cached_df)

        if not self.access_token or self.access_token in ("your_access_token_here", ""):
            raise ValueError(
                "UPSTOX_ACCESS_TOKEN is missing in .env. Run src/data/upstox_auth.py first."
            )

        instrument_key = self._get_instrument_key(clean_symbol)

        # Cap end_date to yesterday/today date format
        to_date_str = end_date
        from_date_str = start_date

        url = f"{UPSTOX_BASE_URL}/historical-candle/{instrument_key}/{upstox_interval}/{to_date_str}/{from_date_str}"

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            res_data = response.json()
        except Exception as e:
            raise ValueError(
                f"Upstox API request failed for symbol '{clean_symbol}' ({instrument_key}): {e}"
            ) from e

        candles = res_data.get("data", {}).get("candles", [])
        if not candles:
            raise ValueError(
                f"No candlestick data returned from Upstox for symbol '{clean_symbol}' between {start_date} and {end_date}."
            )

        # Raw candle structure: [timestamp, open, high, low, close, volume, open_interest]
        raw_df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume", "open_interest"],
        )

        raw_df["timestamp"] = pd.to_datetime(raw_df["timestamp"])
        raw_df.set_index("timestamp", inplace=True)

        if raw_df.index.tz is None:
            raw_df.index = raw_df.index.tz_localize("Asia/Kolkata")
        else:
            raw_df.index = raw_df.index.tz_convert("Asia/Kolkata")

        raw_df.sort_index(inplace=True)
        raw_df["symbol"] = clean_symbol
        raw_df["adj_close"] = raw_df["close"]

        # Resample to 15-minute bars if 15m resolution requested
        if need_resample_15m and len(raw_df) > 1:
            resampled = (
                raw_df.resample("15min")
                .agg(
                    {
                        "symbol": "first",
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "adj_close": "last",
                        "volume": "sum",
                        "open_interest": "last",
                    }
                )
                .dropna(subset=["close"])
            )
            df = resampled.copy()
        else:
            df = raw_df.copy()

        # Format column order matching ADR-005
        standard_cols = [
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "adj_close",
            "volume",
            "open_interest",
        ]
        df = df[standard_cols].copy()

        numeric_cols = ["open", "high", "low", "close", "adj_close", "volume", "open_interest"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        validated_df = validate_schema(df)

        if use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            validated_df.to_parquet(cache_path)
            logger.info(f"Saved Upstox data to cache: {cache_path}")

        return validated_df

    def fetch_option_chain(
        self, symbol: str, expiry_date: str = None
    ) -> pd.DataFrame:
        """
        Fetch Option Chain analytics (Strikes, Call/Put LTP, IV, Greeks, OI) from Upstox API v2.

        Args:
            symbol: Target underlying symbol (e.g. 'NIFTY50', 'BANKNIFTY', 'RELIANCE').
            expiry_date: Optional expiry date string ('YYYY-MM-DD').

        Returns:
            Structured pandas DataFrame containing option chain details.
        """
        if not self.access_token or self.access_token in ("your_access_token_here", ""):
            raise ValueError(
                "UPSTOX_ACCESS_TOKEN is missing in .env. Run src/data/upstox_auth.py first."
            )

        clean_symbol = symbol.strip().upper()
        instrument_key = self._get_instrument_key(clean_symbol)

        url = f"{UPSTOX_BASE_URL}/option/chain"
        params = {"instrument_key": instrument_key}
        if expiry_date:
            params["expiry_date"] = expiry_date

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            res_data = response.json()
        except Exception as e:
            raise ValueError(
                f"Failed to fetch option chain for symbol '{clean_symbol}': {e}"
            ) from e

        chain_data = res_data.get("data", [])
        if not chain_data:
            return pd.DataFrame()

        rows = []
        for item in chain_data:
            strike = item.get("strike_price")
            call_opt = item.get("call_options", {})
            put_opt = item.get("put_options", {})

            call_greeks = call_opt.get("market_data", {}).get("greeks", {})
            put_greeks = put_opt.get("market_data", {}).get("greeks", {})

            rows.append(
                {
                    "underlying_symbol": clean_symbol,
                    "strike_price": float(strike) if strike else np.nan,
                    "call_ltp": float(call_opt.get("market_data", {}).get("ltp", 0.0)),
                    "call_iv": float(call_opt.get("market_data", {}).get("iv", 0.0)),
                    "call_oi": float(call_opt.get("market_data", {}).get("oi", 0.0)),
                    "call_delta": float(call_greeks.get("delta", 0.0)),
                    "call_theta": float(call_greeks.get("theta", 0.0)),
                    "call_vega": float(call_greeks.get("vega", 0.0)),
                    "put_ltp": float(put_opt.get("market_data", {}).get("ltp", 0.0)),
                    "put_iv": float(put_opt.get("market_data", {}).get("iv", 0.0)),
                    "put_oi": float(put_opt.get("market_data", {}).get("oi", 0.0)),
                    "put_delta": float(put_greeks.get("delta", 0.0)),
                    "put_theta": float(put_greeks.get("theta", 0.0)),
                    "put_vega": float(put_greeks.get("vega", 0.0)),
                }
            )

        df = pd.DataFrame(rows)
        return df
