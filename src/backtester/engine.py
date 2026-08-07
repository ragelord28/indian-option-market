"""
Backtest Engine for offline strategy simulation.

Feeds historical ADR-005 market data to Strategy Engine modules, integrates
RiskManager for position sizing and stop-loss/target exit simulation, and calculates
performance metrics (Win Rate, Total PnL, Final Capital).
"""

from typing import Dict, Any, List, Optional
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Signal
from src.backtester.trade import Trade
from src.backtester.synthetic_options import calculate_option_price
from src.risk.risk_manager import RiskManager


class BacktestEngine:
    """
    Simulates strategy execution against historical market data DataFrames with risk management.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        initial_capital: float = 100000.0,
        risk_manager: Optional[RiskManager] = None,
    ):
        """
        Initialize the BacktestEngine.

        Args:
            strategy: Concrete strategy instance (subclass of BaseStrategy).
            initial_capital: Starting portfolio capital balance (default 100,000.0).
            risk_manager: Optional RiskManager instance. If None, default RiskManager is created.
        """
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.risk_manager = risk_manager or RiskManager(account_capital=initial_capital)

    def run(
        self, df: pd.DataFrame, signals: Optional[List[Signal]] = None
    ) -> Dict[str, Any]:
        """
        Run backtest simulation on an ADR-005 market data DataFrame.

        Args:
            df: Standardized market data DataFrame.
            signals: Optional pre-filtered list of Signals. If None, generated via strategy.

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

        # 1. Use provided signals or generate signals via Strategy Engine
        if signals is None:
            signals = self.strategy.generate_signals(df)

        trades: List[Trade] = []
        timestamps = list(df.index)

        # 2. Simulate trades for each generated signal
        for signal in signals:
            if signal.timestamp not in df.index:
                continue

            entry_idx = timestamps.index(signal.timestamp)
            entry_row = df.iloc[entry_idx]
            entry_spot = float(entry_row["close"])
            entry_time = entry_row.name

            entry_price = float(signal.entry_price) if signal.entry_price else entry_spot
            action = signal.action.upper()

            # Ensure stop_loss and target_price are populated via RiskManager
            if signal.stop_loss is None or signal.target_price is None:
                stop_loss, target_price = self.risk_manager.calculate_stop_and_target(
                    entry_price, action
                )
                signal.stop_loss = stop_loss
                signal.target_price = target_price
            else:
                stop_loss = float(signal.stop_loss)
                target_price = float(signal.target_price)

            # Calculate position size using RiskManager
            quantity = self.risk_manager.calculate_position_size(entry_price, stop_loss)

            # Fix 2: If quantity is 0 (risk or capital limit breached), skip the trade
            if quantity == 0:
                continue

            # Check if signal specifies an option trade
            if signal.metadata.get("type") == "OPTION":
                strike = entry_spot
                # Fix 1: Extract option_type ('c' or 'p') and align for entry and exit
                opt_type = signal.metadata.get("option_type", "c")

                entry_premium = calculate_option_price(opt_type, entry_spot, strike, 30.0)
                trade_type = "OPTION"

                # Simulate exit for option trade
                exit_price = round(entry_premium, 2)
                exit_time = entry_time

                for i in range(entry_idx + 1, len(df)):
                    bar = df.iloc[i]
                    bar_spot = float(bar["close"])

                    # If target or stop hit on underlying, exit option trade
                    if action == "BUY":
                        if bar["high"] >= target_price or bar["low"] <= stop_loss:
                            dte = max(30.0 - (i - entry_idx), 1.0)
                            exit_premium = calculate_option_price(opt_type, bar_spot, strike, dte)
                            exit_price = round(exit_premium, 2)
                            exit_time = bar.name
                            break
                    elif action == "SELL":
                        if bar["low"] <= target_price or bar["high"] >= stop_loss:
                            dte = max(30.0 - (i - entry_idx), 1.0)
                            exit_premium = calculate_option_price(opt_type, bar_spot, strike, dte)
                            exit_price = round(exit_premium, 2)
                            exit_time = bar.name
                            break
                else:
                    # Final bar fallback
                    final_bar = df.iloc[-1]
                    final_spot = float(final_bar["close"])
                    dte = max(30.0 - (len(df) - 1 - entry_idx), 1.0)
                    exit_premium = calculate_option_price(opt_type, final_spot, strike, dte)
                    exit_price = round(exit_premium, 2)
                    exit_time = final_bar.name

                pnl = round((exit_price - entry_premium) * quantity, 2)
                pnl_percent = (
                    round(((exit_price - entry_premium) / entry_premium) * 100.0, 2)
                    if entry_premium > 0
                    else 0.0
                )

                trade = Trade(
                    symbol=signal.symbol,
                    entry_time=entry_time,
                    exit_time=exit_time,
                    entry_price=round(entry_premium, 2),
                    exit_price=exit_price,
                    quantity=quantity,
                    pnl=pnl,
                    pnl_percent=pnl_percent,
                    trade_type=trade_type,
                    metadata={
                        "strike": strike,
                        "entry_spot": entry_spot,
                        "option_type": opt_type,
                        "strategy": signal.strategy_name,
                        "confidence": signal.confidence,
                    },
                )
            else:
                # Standard Stock Trade with Risk-Based Exit Simulation
                exit_price = float(df.iloc[-1]["close"])
                exit_time = df.iloc[-1].name

                for i in range(entry_idx + 1, len(df)):
                    bar = df.iloc[i]
                    high = float(bar["high"])
                    low = float(bar["low"])

                    if action == "BUY":
                        # Check Stop Loss first for conservatism
                        if low <= stop_loss:
                            exit_price = stop_loss
                            exit_time = bar.name
                            break
                        elif high >= target_price:
                            exit_price = target_price
                            exit_time = bar.name
                            break
                    elif action == "SELL":
                        if high >= stop_loss:
                            exit_price = stop_loss
                            exit_time = bar.name
                            break
                        elif low <= target_price:
                            exit_price = target_price
                            exit_time = bar.name
                            break

                pnl = round(
                    (exit_price - entry_price) * quantity
                    if action == "BUY"
                    else (entry_price - exit_price) * quantity,
                    2,
                )
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
                    trade_type="STOCK",
                    metadata={
                        "strategy": signal.strategy_name,
                        "confidence": signal.confidence,
                        "stop_loss": stop_loss,
                        "target_price": target_price,
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
