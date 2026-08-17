"""
Yahoo Finance Data Provider Adapter.

Implements BaseDataProvider to fetch historical stock and index OHLCV data from
Yahoo Finance via the `yfinance` Python library, applying ADR-005 schema formatting
and local Parquet disk caching.
"""

from pathlib import Path
import logging
import re
import numpy as np
import pandas as pd
import yfinance as yf

from src.data.base_provider import BaseDataProvider, validate_schema

logger = logging.getLogger(__name__)

# Standard directory for local data caching
DEFAULT_CACHE_DIR = Path("data/cache")

# Default mapping for popular Indian market index symbols
INDEX_SYMBOL_MAP = {
    "NIFTY50": "^NSEI",
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
}


class YahooFinanceProvider(BaseDataProvider):
    """
    Adapter for fetching historical market data from Yahoo Finance.

    Transforms raw Yahoo Finance data into the standard ADR-005 internal format:
    - Timezone: IST ('Asia/Kolkata')
    - Columns: ['symbol', 'open', 'high', 'low', 'close', 'adj_close', 'volume', 'open_interest']
    - Caching: Local Parquet files stored in `data/cache/`
    """

    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR):
        """
        Initialize the YahooFinanceProvider adapter.

        Args:
            cache_dir: Directory path for saving and reading Parquet cache files.
        """
        self.cache_dir = Path(cache_dir)

    def _get_provider_ticker(self, symbol: str) -> str:
        """
        Map an internal standard symbol to its Yahoo Finance provider ticker.

        Examples:
            'RELIANCE'   -> 'RELIANCE.NS'
            'NIFTY50'    -> '^NSEI'
            'BANKNIFTY'  -> '^NSEBANK'

        Args:
            symbol: Clean internal symbol string (e.g. 'RELIANCE').

        Returns:
            Yahoo Finance ticker string (e.g. 'RELIANCE.NS').
        """
        clean_symbol = symbol.strip().upper()

        if clean_symbol in INDEX_SYMBOL_MAP:
            return INDEX_SYMBOL_MAP[clean_symbol]

        # If already formatted with .NS or ^, return as is; otherwise append .NS for Indian equities
        if clean_symbol.endswith(".NS") or clean_symbol.startswith("^"):
            return clean_symbol

        return f"{clean_symbol}.NS"

    def _format_date_for_filename(self, date_str: str) -> str:
        """
        Convert a date string ('YYYY-MM-DD') into compact filename format ('YYYYMMDD').
        """
        return date_str.replace("-", "").replace("/", "")

    def get_cache_filepath(
        self, symbol: str, start_date: str, end_date: str, timeframe: str
    ) -> Path:
        """
        Generate the exact Parquet cache filepath for a given query.

        Format: data/cache/{symbol}_{timeframe}_{start_date}_{end_date}.parquet
        Example: data/cache/RELIANCE_1d_20240101_20240601.parquet

        Note: Keying cache files by exact requested date range is a deliberate Phase 1 simplification.
        """
        start_str = self._format_date_for_filename(start_date)
        end_str = self._format_date_for_filename(end_date)
        filename = f"{symbol.upper()}_{timeframe}_{start_str}_{end_str}.parquet"
        return self.cache_dir / filename

    def fetch_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str = "1d",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Fetch market data accepting interval parameter."""
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
        timeframe: str = "1d",
        use_cache: bool = True,
        **kwargs,
    ) -> pd.DataFrame:
        if "interval" in kwargs:
            timeframe = kwargs["interval"]
        """
        Fetch historical market data from Yahoo Finance or local Parquet cache.

        Args:
            symbol: Standardized internal symbol string (e.g. 'RELIANCE', 'NIFTY50').
            start_date: Start date string ('YYYY-MM-DD').
            end_date: End date string ('YYYY-MM-DD').
            timeframe: Data resolution (e.g. '1d'). Default is '1d'.
            use_cache: If True, check and save to local Parquet cache. Default is True.

        Returns:
            A pandas DataFrame complying strictly with ADR-005 schema.

        Raises:
            ValueError: If symbol format is invalid, data download fails, or data is empty.
        """
        clean_symbol = symbol.strip().upper()

        # Check local cache first if enabled
        cache_path = self.get_cache_filepath(
            clean_symbol, start_date, end_date, timeframe
        )
        if use_cache and cache_path.exists():
            logger.info(f"Loading cached data for {clean_symbol} from {cache_path}")
            cached_df = pd.read_parquet(cache_path)

            # Ensure index timezone is IST upon reading parquet
            if cached_df.index.tz is None:
                cached_df.index = cached_df.index.tz_localize("Asia/Kolkata")
            else:
                cached_df.index = cached_df.index.tz_convert("Asia/Kolkata")

            return validate_schema(cached_df)

        # Map symbol to Yahoo Finance ticker
        provider_ticker = self._get_provider_ticker(clean_symbol)
        logger.info(
            f"Fetching data for '{clean_symbol}' (Yahoo ticker: '{provider_ticker}') from {start_date} to {end_date}"
        )

        try:
            raw_df = yf.download(
                provider_ticker,
                start=start_date,
                end=end_date,
                interval=timeframe,
                auto_adjust=False,  # Retain separate Close and Adj Close
                progress=False,
            )
        except Exception as e:
            raise ValueError(
                f"Network or API failure downloading data for '{clean_symbol}' ({provider_ticker}): {e}"
            ) from e

        if raw_df is None or raw_df.empty:
            raise ValueError(
                f"No data returned from Yahoo Finance for symbol '{clean_symbol}' ({provider_ticker}) "
                f"between {start_date} and {end_date}."
            )

        # Flatten MultiIndex columns if present (yfinance return format)
        if isinstance(raw_df.columns, pd.MultiIndex):
            raw_df.columns = raw_df.columns.get_level_values(0)

        # Normalize column names
        col_rename_map = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
        df = raw_df.rename(columns=col_rename_map).copy()

        # Fallback if adj_close is not provided
        if "adj_close" not in df.columns and "close" in df.columns:
            df["adj_close"] = df["close"]

        # Populate internal symbol column (never use raw provider ticker string)
        df["symbol"] = clean_symbol

        # Populate open_interest column (NaN for Yahoo Finance)
        df["open_interest"] = np.nan

        # Format timestamp index
        df.index.name = "timestamp"

        # Localize or convert index timezone to IST ('Asia/Kolkata')
        if df.index.tz is None:
            df.index = df.index.tz_localize("Asia/Kolkata")
        else:
            df.index = df.index.tz_convert("Asia/Kolkata")

        # Sort chronologically by timestamp
        df = df.sort_index()

        # Reorder columns to match ADR-005 standard
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
        df = df[standard_cols]

        # Ensure correct numeric data types
        numeric_cols = ["open", "high", "low", "close", "adj_close", "volume", "open_interest"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Validate final DataFrame against ADR-005 schema
        validated_df = validate_schema(df)

        # Save to local Parquet cache if caching enabled
        if use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            validated_df.to_parquet(cache_path)
            logger.info(f"Saved data to local cache: {cache_path}")

        return validated_df
