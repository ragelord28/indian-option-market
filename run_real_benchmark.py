"""
Real Historical Data Benchmark Runner across Full NSE F&O Universe.

Enforces portfolio capital constraints (₹10 Lakhs starting capital, 5 max concurrent margin trades),
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
from src.backtester.engine import BacktestEngine
from src.backtester.benchmark import calculate_max_drawdown_pct


STARTING_CAPITAL = 1000000.0  # ₹10 Lakhs
MAX_CONCURRENT_TRADES = 5


def main():
    print("=" * 125)
    print(f"{'REAL HISTORICAL DATA BENCHMARK (FULL NSE F&O UNIVERSE)':^125}")
    print("=" * 125)

    provider = YahooFinanceProvider()

    # 3-year lookback period
    end_dt = datetime.now() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=3 * 365)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    print(f"Fetch Period: {start_date} to {end_date}")
    print(f"Target Universe: {len(FULL_FNO_UNIVERSE)} F&O equities")
    print(f"Starting Capital: ₹{STARTING_CAPITAL:,.2f} | Max Concurrent Trades: {MAX_CONCURRENT_TRADES}\n")

    # Instantiate strategies
    strategies = [
        ORBMomentumStrategy(),
        HedgedVolPremiumStrategy(percentile_threshold=50.0),
        OISwingStrategy(),
        RelativeStrengthVWAPReversionStrategy(vwap_dist_threshold=0.01),
        CompositeHolyGrailStrategy(),
    ]

    # Data collection for Full Universe
    stock_dfs = {}
    successful_downloads = 0

    print("Fetching historical market data for Full F&O universe...")
    for symbol in FULL_FNO_UNIVERSE:
        try:
            df = provider.fetch_historical_data(
                symbol=symbol, start_date=start_date, end_date=end_date
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

    for strat in strategies:
        strat_name = strat.name
        candidate_trades = []

        for symbol, df in stock_dfs.items():
            engine = BacktestEngine(
                strategy=strat,
                initial_capital=STARTING_CAPITAL,
                max_concurrent_trades=MAX_CONCURRENT_TRADES,
            )
            res = engine.run(df)
            candidate_trades.extend(res["trades"])

        # Sort candidate trades chronologically by entry_time
        candidate_trades.sort(key=lambda t: t.entry_time)

        # Portfolio-level max concurrent trades filter
        portfolio_trades = []
        for t in candidate_trades:
            active_count = sum(
                1 for pt in portfolio_trades if pt.entry_time <= t.entry_time < pt.exit_time
            )
            if active_count < MAX_CONCURRENT_TRADES:
                portfolio_trades.append(t)

        total_trades = len(portfolio_trades)
        winning_trades = sum(1 for t in portfolio_trades if t.pnl > 0)
        win_rate = (winning_trades / total_trades) if total_trades > 0 else 0.0
        win_rate_pct = f"{win_rate * 100:.1f}%"

        total_pnl = sum(t.pnl for t in portfolio_trades)
        ending_capital = round(STARTING_CAPITAL + total_pnl, 2)
        roi_pct = ((ending_capital - STARTING_CAPITAL) / STARTING_CAPITAL) * 100.0

        if ending_capital > 0:
            cagr_pct = (((ending_capital / STARTING_CAPITAL) ** (1.0 / 3.0)) - 1.0) * 100.0
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
    print(f"{'FULL NSE F&O UNIVERSE FINANCIAL BENCHMARK RESULTS':^125}")
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
