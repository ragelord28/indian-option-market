"""
Real Historical Data Benchmark Runner across Top 50 F&O Stocks.

Phase 9 execution: Downloads 3 years of historical daily market data via YahooFinanceProvider
for the TOP_50_FNO universe, runs all 5 strategy modules through BacktestEngine,
aggregates cross-portfolio metrics (Total Trades, Win Rate %, Total PnL, Max Drawdown),
and outputs a formatted ASCII comparison table.
"""

from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from src.scanner.universe import TOP_50_FNO
from src.data.yahoo_provider import YahooFinanceProvider
from src.strategies.orb_momentum import ORBMomentumStrategy
from src.strategies.hedged_vol_premium import HedgedVolPremiumStrategy
from src.strategies.oi_swing import OISwingStrategy
from src.strategies.custom_research_strategy import RelativeStrengthVWAPReversionStrategy
from src.strategies.composite_holy_grail import CompositeHolyGrailStrategy
from src.backtester.engine import BacktestEngine
from src.backtester.benchmark import calculate_max_drawdown


def main():
    print("=" * 95)
    print(f"{'PHASE 9: REAL HISTORICAL DATA BENCHMARK (TOP 50 F&O UNIVERSE)':^95}")
    print("=" * 95)

    provider = YahooFinanceProvider()

    # 3-year lookback period
    end_dt = datetime.now() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=3 * 365)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    print(f"Fetch Period: {start_date} to {end_date}")
    print(f"Target Universe: {len(TOP_50_FNO)} liquid FnO equities\n")

    # Instantiate strategies
    strategies = [
        ORBMomentumStrategy(),
        HedgedVolPremiumStrategy(percentile_threshold=50.0),
        OISwingStrategy(),
        RelativeStrengthVWAPReversionStrategy(vwap_dist_threshold=0.01),
        CompositeHolyGrailStrategy(),
    ]

    # Data collection for Top 50 universe
    stock_dfs = {}
    successful_downloads = 0

    print("Fetching historical market data for Top 50 F&O stocks...")
    for symbol in TOP_50_FNO:
        try:
            df = provider.fetch_historical_data(
                symbol=symbol, start_date=start_date, end_date=end_date
            )
            if df is not None and not df.empty:
                stock_dfs[symbol] = df
                successful_downloads += 1
        except Exception as e:
            print(f"  [WARN] Failed to fetch data for {symbol}: {e}")

    print(f"Data ingestion complete. Successfully loaded {successful_downloads}/{len(TOP_50_FNO)} stocks.\n")

    # Aggregated results per strategy
    strategy_results = {}

    for strat in strategies:
        strat_name = strat.name
        all_trades = []
        total_pnl_sum = 0.0

        for symbol, df in stock_dfs.items():
            engine = BacktestEngine(strategy=strat, initial_capital=100000.0)
            res = engine.run(df)

            trades = res["trades"]
            all_trades.extend(trades)
            total_pnl_sum += res["metrics"]["total_pnl"]

        total_trades = len(all_trades)
        winning_trades = sum(1 for t in all_trades if t.pnl > 0)
        win_rate = (winning_trades / total_trades) if total_trades > 0 else 0.0
        win_rate_pct = f"{win_rate * 100:.1f}%"

        # Portfolio-level max drawdown calculation
        max_dd = calculate_max_drawdown(all_trades, initial_capital=100000.0)

        strategy_results[strat_name] = {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "win_rate_pct": win_rate_pct,
            "total_pnl": round(total_pnl_sum, 2),
            "max_drawdown": max_dd,
        }

    # Print ASCII summary table
    print("=" * 95)
    print(f"{'REAL HISTORICAL DATA BENCHMARK RESULTS (AGGREGATED TOP 50 F&O)':^95}")
    print("=" * 95)
    header = f"{'Strategy Name':<42} | {'Trades':<8} | {'Win Rate':<10} | {'Total PnL (₹)':<14} | {'Max DD (₹)':<12}"
    print(header)
    print("-" * 95)

    for strat_name, metrics in strategy_results.items():
        t_trades = metrics["total_trades"]
        w_rate = metrics["win_rate_pct"]
        pnl_str = f"₹{metrics['total_pnl']:,.2f}"
        dd_str = f"₹{metrics['max_drawdown']:,.2f}"

        row_str = f"{strat_name:<42} | {t_trades:<8} | {w_rate:<10} | {pnl_str:<14} | {dd_str:<12}"
        print(row_str)

    print("=" * 95 + "\n")


if __name__ == "__main__":
    main()
