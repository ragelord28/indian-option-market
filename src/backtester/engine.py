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


def _get_sigma(row: pd.Series) -> float:
    """Extract hv_20 volatility or fallback to default 0.20."""
    val = row.get("hv_20") if "hv_20" in row.index else None
    if val is None or pd.isna(val) or val <= 0:
        return 0.20
    return float(val)


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

        # 1. Use provided signals or generate & filter signals via Strategy Engine
        if signals is None:
            raw_signals = self.strategy.generate_signals(df)
            signals = [s for s in raw_signals if self.strategy.filter_signal_rule_8(s)]

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

            # 1. Directional Mapping: is_bullish = target_price > entry_spot
            is_bullish = target_price > entry_spot

            # Check if signal specifies an option trade
            if signal.metadata.get("type") == "OPTION":
                strike = entry_spot
                opt_type = signal.metadata.get("option_type", "c")
                entry_sigma = _get_sigma(entry_row)

                # 2. Option Sizing based on option premium risk
                entry_premium = calculate_option_price(
                    opt_type, S=entry_spot, K=strike, days_to_expiry=30.0, sigma=entry_sigma
                )
                stop_premium = calculate_option_price(
                    opt_type, S=stop_loss, K=strike, days_to_expiry=30.0, sigma=entry_sigma
                )

                quantity = self.risk_manager.calculate_position_size(
                    entry_price=entry_premium, stop_loss=stop_premium
                )

                if quantity == 0:
                    continue

                trade_type = "OPTION"
                exit_time = entry_time
                trigger_price = entry_spot
                exit_bar_idx = entry_idx

                # 3. Pessimistic Exits
                for i in range(entry_idx + 1, len(df)):
                    bar = df.iloc[i]
                    low = float(bar["low"])
                    high = float(bar["high"])

                    if is_bullish:
                        if low <= stop_loss:
                            trigger_price = stop_loss
                            exit_time = bar.name
                            exit_bar_idx = i
                            break
                        elif high >= target_price:
                            trigger_price = target_price
                            exit_time = bar.name
                            exit_bar_idx = i
                            break
                    else:
                        if high >= stop_loss:
                            trigger_price = stop_loss
                            exit_time = bar.name
                            exit_bar_idx = i
                            break
                        elif low <= target_price:
                            trigger_price = target_price
                            exit_time = bar.name
                            exit_bar_idx = i
                            break
                else:
                    # Final bar fallback
                    final_bar = df.iloc[-1]
                    trigger_price = float(final_bar["close"])
                    exit_time = final_bar.name
                    exit_bar_idx = len(df) - 1

                # 4. Accurate Option Exit Pricing using trigger_price & actual bar sigma
                exit_bar = df.iloc[exit_bar_idx]
                exit_sigma = _get_sigma(exit_bar)
                dte = max(30.0 - (exit_bar_idx - entry_idx), 1.0)
                exit_premium = calculate_option_price(
                    opt_type, S=trigger_price, K=strike, days_to_expiry=dte, sigma=exit_sigma
                )
                exit_price = round(exit_premium, 2)

                # 5. Fix Option SELL PnL & 6. Transaction Costs (-₹50)
                if action == "SELL":
                    raw_pnl = (entry_premium - exit_premium) * quantity
                    pnl_pct = (
                        ((entry_premium - exit_premium) / entry_premium) * 100.0
                        if entry_premium > 0
                        else 0.0
                    )
                else:
                    raw_pnl = (exit_premium - entry_premium) * quantity
                    pnl_pct = (
                        ((exit_premium - entry_premium) / entry_premium) * 100.0
                        if entry_premium > 0
                        else 0.0
                    )

                pnl = round(raw_pnl - 50.0, 2)
                pnl_percent = round(pnl_pct, 2)

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
                # Standard Stock Trade
                quantity = self.risk_manager.calculate_position_size(entry_price, stop_loss)
                if quantity == 0:
                    continue

                exit_time = df.iloc[-1].name
                trigger_price = float(df.iloc[-1]["close"])

                # 3. Pessimistic Exits
                for i in range(entry_idx + 1, len(df)):
                    bar = df.iloc[i]
                    low = float(bar["low"])
                    high = float(bar["high"])

                    if is_bullish:
                        if low <= stop_loss:
                            trigger_price = stop_loss
                            exit_time = bar.name
                            break
                        elif high >= target_price:
                            trigger_price = target_price
                            exit_time = bar.name
                            break
                    else:
                        if high >= stop_loss:
                            trigger_price = stop_loss
                            exit_time = bar.name
                            break
                        elif low <= target_price:
                            trigger_price = target_price
                            exit_time = bar.name
                            break

                exit_price = trigger_price
                if action == "SELL":
                    raw_pnl = (entry_price - exit_price) * quantity
                    pnl_pct = (
                        ((entry_price - exit_price) / entry_price) * 100.0
                        if entry_price > 0
                        else 0.0
                    )
                else:
                    raw_pnl = (exit_price - entry_price) * quantity
                    pnl_pct = (
                        ((exit_price - entry_price) / entry_price) * 100.0
                        if entry_price > 0
                        else 0.0
                    )

                pnl = round(raw_pnl - 50.0, 2)
                pnl_percent = round(pnl_pct, 2)

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
