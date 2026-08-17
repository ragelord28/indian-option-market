"""
Base Data Provider & Standard Market Data Schema Validation (ADR-005).

This module defines:
1. BaseDataProvider: An abstract base class for all market data sources (Yahoo, Upstox, etc.).
2. validate_schema: A standard validator ensuring market DataFrames adhere strictly to ADR-005 rules.
"""

from abc import ABC, abstractmethod
import re
import pandas as pd


# Required standard column names per ADR-005
STANDARD_COLUMNS = [
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "open_interest",
]

# Regex pattern for valid internal symbols (uppercase alphanumeric, underscores, ampersands, hyphens, no suffixes)
VALID_SYMBOL_REGEX = re.compile(r"^[A-Z0-9_&\-]+$")


def validate_schema(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validate that a market data DataFrame strictly complies with ADR-005.

    Rules enforced:
    - Index must be a DatetimeIndex named 'timestamp'.
    - Index timezone must be timezone-aware IST ('Asia/Kolkata').
    - Columns must exactly match STANDARD_COLUMNS in order:
      ['symbol', 'open', 'high', 'low', 'close', 'adj_close', 'volume', 'open_interest']
    - 'symbol' column values must be valid internal symbols (uppercase alphanumeric, underscores, &, -, no suffixes).
    - Price columns ('open', 'high', 'low', 'close', 'adj_close') must be explicitly float64.

    Args:
        df: The pandas DataFrame to validate.

    Returns:
        The validated DataFrame if compliant.

    Raises:
        ValueError: If any ADR-005 schema requirement is violated.
    """
    if df is None or not isinstance(df, pd.DataFrame):
        raise ValueError("Input must be a valid pandas DataFrame.")

    if df.empty:
        raise ValueError("DataFrame is empty. Cannot validate schema.")

    # 1. Validate index type and name
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(
            f"DataFrame index must be a DatetimeIndex, got '{type(df.index).__name__}'."
        )

    if df.index.name != "timestamp":
        raise ValueError(
            f"DataFrame index must be named 'timestamp', got '{df.index.name}'."
        )

    # 2. Validate IST timezone
    if df.index.tz is None:
        raise ValueError(
            "DataFrame index 'timestamp' must be timezone-aware (Asia/Kolkata)."
        )

    tz_str = str(df.index.tz)
    if tz_str not in ("Asia/Kolkata", "Asia/Calcutta", "IST"):
        raise ValueError(
            f"DataFrame timestamp index must be in Asia/Kolkata timezone, got '{tz_str}'."
        )

    # 3. Validate columns
    actual_cols = list(df.columns)
    if actual_cols != STANDARD_COLUMNS:
        raise ValueError(
            f"DataFrame columns do not match ADR-005 standard.\n"
            f"Expected: {STANDARD_COLUMNS}\n"
            f"Got:      {actual_cols}"
        )

    # 4. Validate symbol column values
    symbols = df["symbol"].dropna().unique()
    if len(symbols) == 0:
        raise ValueError("DataFrame 'symbol' column contains no valid symbol strings.")

    for sym in symbols:
        if not isinstance(sym, str) or not VALID_SYMBOL_REGEX.match(sym):
            raise ValueError(
                f"Invalid internal symbol '{sym}' in 'symbol' column. "
                "Per ADR-005, internal symbols must be uppercase alphanumeric (with optional _, &, -) without suffixes (e.g. 'RELIANCE', 'M&M', 'BAJAJ-AUTO')."
            )

    # 5. Validate dtypes for price columns (must be float64)
    price_cols = ["open", "high", "low", "close", "adj_close"]
    for col in price_cols:
        if df[col].dtype != "float64":
            raise ValueError(
                f"Column '{col}' must be of dtype float64, got '{df[col].dtype}'."
            )

    return df


class BaseDataProvider(ABC):
    """
    Abstract Base Class for all market data provider adapters.

    Every data provider (e.g. YahooFinanceProvider, UpstoxProvider) must inherit
    from this class and implement `fetch_historical_data`.
    """

    @abstractmethod
    def fetch_historical_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = "1d",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """
        Fetch historical market data for a given symbol and date range.

        Args:
            symbol: Standardized internal symbol string (e.g. 'RELIANCE', 'NIFTY50').
            start_date: Start date string formatted as 'YYYY-MM-DD'.
            end_date: End date string formatted as 'YYYY-MM-DD'.
            timeframe: Data resolution (e.g. '1d' for daily, '1m' for 1-minute). Default is '1d'.
            use_cache: Whether to read from/write to local disk cache. Default is True.

        Returns:
            A pandas DataFrame complying strictly with ADR-005.
        """
        pass
