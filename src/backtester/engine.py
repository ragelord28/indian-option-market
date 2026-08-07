"""
Backtest Engine for offline strategy simulation.

Feeds historical ADR-005 market data to Strategy Engine modules, simulates trade
entries and exits (including Black-Scholes synthetic option pricing), and calculates
performance metrics (Win Rate, Total PnL, Final Capital).
"""

from typing import Dict, Any, List
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Signal
from src.backtester.trade import Trade
from src.backtester.synthetic_options import calculate_option_price


class BacktestEngine:
    """
    Simulates strategy execution against historical market data DataFrames.
    """

    def __init__(self, strategy: BaseStrategy, initial_capital: float = 100000.0):
        """
        Initialize the BacktestEngine.

        Args:
            strategy: Concrete strategy instance (subclass of BaseStrategy).
            initial_capital: Starting portfolio capital balance (default 100,000.0).
        """
        self.strategy = strategy
        self.initial_capital = initial_capital

    def run(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Run backtest simulation on an ADR-005 market data DataFrame.

        Args:
            df: Standardized market data DataFrame.

        Returns:
            Dictionary containing performance metrics and list of executed Trades:
            {
                "metrics": {
                    "total_trades": int,
                    "winning_trades": int,
                    "win_rate": float,
                    "total_pnl": float,
                    "final_capital": float,
                },
                "trades": List[Trade]
            }
        """
        if df is None or df.empty:
            return {
                "metrics": {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "final_capital": self.initial_capital,
                },
                "trades": [],
            }

        # 1. Generate signals using Strategy Engine
        signals: List[Signal] = self.strategy.generate_signals(df)

        trades: List[Trade] = []
        timestamps = list(df.index)

        # 2. Simulate trades for each generated signal
        for signal in signals:
            if signal.timestamp not in df.index:
                continue

            entry_idx = timestamps.index(signal.timestamp)
            # Exit 5 rows after entry (or at final row if 5 days exceeds DataFrame)
            exit_idx = min(entry_idx + 5, len(df) - 1)

            entry_row = df.iloc[entry_idx]
            exit_row = df.iloc[exit_idx]

            entry_spot = float(entry_row["close"])
            exit_spot = float(exit_row["close"])
            entry_time = entry_row.name
            exit_time = exit_row.name

            # Check if signal specifies an option trade
            if signal.metadata.get("type") == "OPTION":
                strike = entry_spot
                # Calculate synthetic ATM Call premium (30 DTE at entry, 25 DTE at exit)
                entry_premium = calculate_option_price("c", entry_spot, strike, 30.0)
                exit_premium = calculate_option_price("c", exit_spot, strike, 25.0)

                quantity = 100  # Standard lot size
                trade_type = "OPTION"
                entry_price = round(entry_premium, 2)
                exit_price = round(exit_premium, 2)
                pnl = round((exit_price - entry_price) * quantity, 2)
                pnl_percent = (
                    round(((exit_price - entry_price) / entry_price) * 100.0, 2)
                    if entry_price > 0
                    else 0.0
                )

                trade = Trade(
                    symbol=signal.symbol,
                    entry_time=entry_time,
                    exit_time=exit_time,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    quantity=quantity,
                    pnl=pnl,
                    pnl_percent=pnl_percent,
                    trade_type=trade_type,
                    metadata={
                        "strike": strike,
                        "entry_spot": entry_spot,
                        "exit_spot": exit_spot,
                        "strategy": signal.strategy_name,
                        "confidence": signal.confidence,
                    },
                )
            else:
                # Standard equity stock trade simulation
                entry_price = float(signal.entry_price) if signal.entry_price else entry_spot
                exit_price = exit_spot

                # Allocate ~10% capital per trade
                allocated_capital = self.initial_capital * 0.10
                quantity = max(int(allocated_capital / entry_price), 1) if entry_price > 0 else 1
                trade_type = "STOCK"

                pnl = round((exit_price - entry_price) * quantity, 2)
                pnl_percent = (
                    round(((exit_price - entry_price) / entry_price) * 100.0, 2)
                    if entry_price > 0
                    else 0.0
                )

                trade = Trade(
                    symbol=signal.symbol,
                    entry_time=entry_time,
                    exit_time=exit_time,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    quantity=quantity,
                    pnl=pnl,
                    pnl_percent=pnl_percent,
                    trade_type=trade_type,
                    metadata={
                        "strategy": signal.strategy_name,
                        "confidence": signal.confidence,
                    },
                )

            trades.append(trade)

        # 3. Calculate summary metrics
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.pnl > 0)
        win_rate = round(winning_trades / total_trades, 4) if total_trades > 0 else 0.0
        total_pnl = round(sum(t.pnl for t in trades), 2)
        final_capital = round(self.initial_capital + total_pnl, 2)

        return {
            "metrics": {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "final_capital": final_capital,
            },
            "trades": trades,
        }
