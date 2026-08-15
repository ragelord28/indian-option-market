"""
Real Historical Intraday Data Benchmark Runner across Full NSE F&O Universe.

Phase 9.9 Engine Rebuild: Downloads 60 days of 15-minute intraday market data via YahooFinanceProvider
for the FULL_FNO_UNIVERSE (~160+ stocks), passes all stock DataFrames in bulk to PortfolioEngine,
enforces single-pass chronological portfolio margin tracking (₹10 Lakhs starting capital, 5 max concurrent trades),
calculates full financial metrics (Ending Capital, ROI %, CAGR %, Max Drawdown %, Win Rate %, Total Trades),
and outputs a formatted ASCII benchmark comparison table.
"""

from datetime import datetime, timedelta
import time
import pandas as pd
import numpy as np

from src.scanner.universe import FULL_FNO_UNIVERSE
from src.data.yahoo_provider import YahooFinanceProvider
from src.strategies.orb_momentum import ORBMomentumStrategy
from src.strategies.hedged_vol_premium import HedgedVolPremiumStrategy
from src.strategies.oi_swing import OISwingStrategy
from src.strategies.custom_research_strategy import RelativeStrengthVWAPReversionStrategy
from src.strategies.composite_holy_grail import CompositeHolyGrailStrategy
from src.strategies.avpc_afternoon import AVPCAfternoonStrategy
from src.backtester.engine import PortfolioEngine
from src.backtester.benchmark import calculate_max_drawdown_pct


STARTING_CAPITAL = 1000000.0  # ₹10 Lakhs
MAX_CONCURRENT_TRADES = 5


def main():
    print("=" * 125)
    print(f"{'REAL 60-DAY 15-MIN INTRADAY PORTFOLIO BENCHMARK (FULL NSE F&O UNIVERSE)':^125}")
    print("=" * 125)

    provider = YahooFinanceProvider()

    # 60-day lookback period for 15-minute intraday data
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=59)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    print(f"Fetch Period: {start_date} to {end_date} (Interval: 15m)")
    print(f"Target Universe: {len(FULL_FNO_UNIVERSE)} F&O equities")
    print(f"Starting Capital: ₹{STARTING_CAPITAL:,.2f} | Max Concurrent Trades: {MAX_CONCURRENT_TRADES}\n")

    # Instantiate strategies
    strategies = [
        ORBMomentumStrategy(),
        HedgedVolPremiumStrategy(percentile_threshold=50.0),
        OISwingStrategy(),
        RelativeStrengthVWAPReversionStrategy(vwap_dist_threshold=0.01),
        CompositeHolyGrailStrategy(),
        AVPCAfternoonStrategy(),
    ]

    # Data collection for Full Universe
    stock_dfs = {}
    successful_downloads = 0

    print("Fetching 15m intraday market data for Full F&O universe...")
    for symbol in FULL_FNO_UNIVERSE:
        try:
            df = provider.fetch_data(
                symbol=symbol, start_date=start_date, end_date=end_date, interval="15m"
            )
            if df is not None and not df.empty:
                stock_dfs[symbol] = df
                successful_downloads += 1
        except Exception as e:
            print(f"  [WARN] Failed to fetch data for {symbol}: {e}")
        time.sleep(0.1)  # Rate limiting safety delay

    print(
        f"\nData ingestion complete. Successfully loaded {successful_downloads}/{len(FULL_FNO_UNIVERSE)} stocks.\n"
    )

    # Aggregated results per strategy
    strategy_results = {}
    lookback_years = 60.0 / 365.0

    for strat in strategies:
        strat_name = strat.name
        engine = PortfolioEngine(
            strategy=strat,
            initial_capital=STARTING_CAPITAL,
            max_concurrent_trades=MAX_CONCURRENT_TRADES,
            lot_size=50,
        )
        res = engine.run(stock_dfs)

        metrics = res["metrics"]
        portfolio_trades = res["trades"]

        total_trades = metrics["total_trades"]
        win_rate_pct = f"{metrics['win_rate'] * 100:.1f}%"
        ending_capital = metrics["final_capital"]

        roi_pct = ((ending_capital - STARTING_CAPITAL) / STARTING_CAPITAL) * 100.0

        if ending_capital > 0:
            cagr_pct = (((ending_capital / STARTING_CAPITAL) ** (1.0 / lookback_years)) - 1.0) * 100.0
        else:
            cagr_pct = -100.0

        max_dd_pct = calculate_max_drawdown_pct(
            portfolio_trades, initial_capital=STARTING_CAPITAL
        )

        strategy_results[strat_name] = {
            "starting_capital": STARTING_CAPITAL,
            "ending_capital": ending_capital,
            "roi_pct": roi_pct,
            "cagr_pct": cagr_pct,
            "max_dd_pct": max_dd_pct,
            "win_rate_pct": win_rate_pct,
            "total_trades": total_trades,
        }

    # Print ASCII summary table
    print("=" * 125)
    print(f"{'FULL NSE F&O UNIVERSE 60-DAY 15M INTRADAY PORTFOLIO BENCHMARK RESULTS':^125}")
    print("=" * 125)
    header = (
        f"{'Strategy Name':<38} | {'Start Cap (₹)':<14} | {'End Cap (₹)':<15} | "
        f"{'ROI (%)':<9} | {'CAGR (%)':<9} | {'Max DD (%)':<10} | {'Win Rate':<9} | {'Trades':<7}"
    )
    print(header)
    print("-" * 125)

    for strat_name, metrics in strategy_results.items():
        start_cap_str = f"₹{metrics['starting_capital']:,.2f}"
        end_cap_str = f"₹{metrics['ending_capital']:,.2f}"
        roi_str = f"{metrics['roi_pct']:+.1f}%"
        cagr_str = f"{metrics['cagr_pct']:+.1f}%"
        dd_str = f"{metrics['max_dd_pct']:.1f}%"
        w_rate = metrics["win_rate_pct"]
        t_trades = metrics["total_trades"]

        row_str = (
            f"{strat_name:<38} | {start_cap_str:<14} | {end_cap_str:<15} | "
            f"{roi_str:<9} | {cagr_str:<9} | {dd_str:<10} | {w_rate:<9} | {t_trades:<7}"
        )
        print(row_str)

    print("=" * 125 + "\n")


if __name__ == "__main__":
    main()
