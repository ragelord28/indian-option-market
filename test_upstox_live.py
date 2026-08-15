"""
Live Upstox API v2 Integration & Token Verification Script.

Tests reading credentials from .env and fetching live 15-minute candle data via UpstoxProvider.
"""

from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

from src.data.upstox_provider import UpstoxProvider


def main():
    load_dotenv(override=True)
    access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()

    print("=" * 80)
    print("                      UPSTOX API V2 LIVE CONNECTIVITY TEST                      ")
    print("=" * 80)

    if not access_token or access_token in ("your_access_token_here", ""):
        print("\n[NOTICE] UPSTOX_ACCESS_TOKEN is not configured or empty in .env.")
        print("\nPlease complete authentication by executing:")
        print("  1. Add your UPSTOX_API_KEY and UPSTOX_API_SECRET to .env")
        print("  2. Run: python src/data/upstox_auth.py\n")
        return

    print(f"\n[OK] UPSTOX_ACCESS_TOKEN detected (Prefix: {access_token[:8]}...)")
    print("Attempting test fetch for RELIANCE 15-minute candles...\n")

    provider = UpstoxProvider()
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=5)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    try:
        df = provider.fetch_data(
            symbol="RELIANCE", start_date=start_date, end_date=end_date, interval="15minute"
        )
        print(f"Successfully fetched {len(df)} candles for RELIANCE.")
        print("\nLast 3 Candles (ADR-005 Schema Compliant):")
        print("-" * 80)
        print(df.tail(3))
        print("-" * 80)
        print("\n[SUCCESS] Upstox Live API v2 connection verified successfully!")
    except Exception as e:
        print(f"[ERROR] Failed to fetch live data from Upstox API: {e}")


if __name__ == "__main__":
    main()
