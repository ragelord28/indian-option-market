"""
Portfolio Engine for offline multi-asset strategy simulation.

Implements Phase 9.9 Red Team Remediation:
- Chronological global signal execution across multi-asset portfolios.
- PortfolioLedger for cash, blocked margin, and free capital tracking.
- Calendar day DTE decay math: elapsed_days = (exit_time - entry_time).total_seconds() / 86400.0.
- Implied volatility sigma extraction from signals and historical bar hv_20.
- Delta strike solver for ATM / OTM option contracts.
- Variable transaction cost model: flat brokerage plus ad-valorem STT / exchange /
  GST / stamp-duty components (see calculate_fno_transaction_cost).
"""

from typing import Dict, Any, List, Optional, Tuple, Union
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Signal
from src.backtester.trade import Trade
from src.backtester.synthetic_options import calculate_option_price, find_strike_for_delta
from src.risk.risk_manager import RiskManager


def calculate_fno_transaction_cost(
    entry_premium: float,
    exit_premium: float,
    quantity: int,
    is_option: bool = True
) -> float:
    """
    Calculate realistic Indian F&O transaction cost friction.

    Breakdown:
    - Brokerage: ₹20 buy + ₹20 sell = ₹40.0
    - STT: 0.1% on sell turnover (exit_premium * quantity * 0.001)
    - Exchange Txn Charges: 0.05% on total turnover ((entry_premium + exit_premium) * quantity * 0.0005)
    - GST: 18% on (Brokerage + Exchange charges)
    - Stamp Duty: 0.003% on buy turnover (entry_premium * quantity * 0.00003)

    ``is_option`` is retained for API compatibility (equity vs. derivative fee
    schedules); the current friction model applies uniformly to both.
    """
    brokerage = 40.0
    stt = exit_premium * quantity * 0.001
    exchange_txn = (entry_premium + exit_premium) * quantity * 0.0005
    gst = (brokerage + exchange_txn) * 0.18
    stamp_duty = entry_premium * quantity * 0.00003
    total_costs = brokerage + stt + exchange_txn + gst + stamp_duty
    return round(total_costs, 2)


def _empty_result(final_capital: float) -> Dict[str, Any]:
    """Standard empty simulation payload (no executable data -> no trades)."""
    return {
        "metrics": {
            "total_trades": 0,
            "winning_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "final_capital": final_capital,
        },
        "trades": [],
    }


def _compute_pnl(
    action: str, entry_px: float, exit_px: float, quantity: int
) -> Tuple[float, float]:
    """
    Compute (raw_pnl, pnl_percent) for a closed BUY/SELL position.

    pnl_percent is expressed on the per-unit entry-price basis; a non-positive
    entry price yields 0.0 to guard against division by zero.
    """
    if action == "SELL":
        raw_pnl = (entry_px - exit_px) * quantity
        pnl_pct = ((entry_px - exit_px) / entry_px) * 100.0 if entry_px > 0 else 0.0
    else:
        raw_pnl = (exit_px - entry_px) * quantity
        pnl_pct = ((exit_px - entry_px) / entry_px) * 100.0 if entry_px > 0 else 0.0
    return raw_pnl, pnl_pct


def _get_sigma(row: pd.Series, metadata: Optional[Dict[str, Any]] = None) -> float:
    """Extract hv_20 volatility from metadata or row, fallback to 0.20."""
    if metadata and "hv_20" in metadata and metadata["hv_20"] is not None:
        val = metadata["hv_20"]
        if not pd.isna(val) and float(val) > 0:
            return float(val)
    if "hv_20" in row.index and not pd.isna(row["hv_20"]) and float(row["hv_20"]) > 0:
        return float(row["hv_20"])
    return 0.20


class PortfolioEngine:
    """
    Simulates portfolio strategy execution across multi-asset historical DataFrames
    with chronological margin tracking, calendar day option pricing, and risk management.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        initial_capital: float = 1000000.0,
        risk_manager: Optional[RiskManager] = None,
        max_concurrent_trades: int = 5,
        lot_size: int = 50,
    ):
        """
        Initialize the PortfolioEngine.

        Args:
            strategy: Concrete strategy instance (subclass of BaseStrategy).
            initial_capital: Starting portfolio cash balance (default 1,000,000.0).
            risk_manager: Optional RiskManager instance.
            max_concurrent_trades: Maximum allowed concurrent open positions (default 5).
            lot_size: Standard option lot size multiplier (default 50).
        """
        self.strategy = strategy
        self.initial_capital = float(initial_capital)
        self.risk_manager = risk_manager or RiskManager(account_capital=initial_capital)
        self.max_concurrent_trades = max_concurrent_trades
        self.lot_size = lot_size

    def _evaluate_position_exit(
        self,
        pos: Dict[str, Any],
        df: pd.DataFrame,
        current_time: pd.Timestamp,
        force_close: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate if an open position meets exit criteria up to current_time.
        """
        symbol = pos["symbol"]
        entry_time = pos["entry_time"]
        entry_price_or_premium = pos["entry_price_or_premium"]
        stop_loss = pos["stop_loss"]
        target_price = pos["target_price"]
        is_bullish = pos["is_bullish"]
        is_option = pos["is_option"]
        opt_type = pos.get("option_type", "c")
        strike = pos.get("strike", pos["entry_spot"])
        quantity = pos["quantity"]
        action = pos["action"]

        timestamps = list(df.index)
        sub_indices = [
            i for i, ts in enumerate(timestamps) if entry_time < ts <= current_time
        ]

        if not sub_indices and not force_close:
            return None

        # exit_bar_idx / exit_time / trigger_price are assigned on every path that
        # reaches their read sites: inside the scan loop below or the force-close block.
        exit_found = False

        for i in sub_indices:
            bar = df.iloc[i]
            bar_time = bar.name
            low = float(bar["low"])
            high = float(bar["high"])

            # Check price targets / stops
            if is_bullish:
                if low <= stop_loss:
                    trigger_price = stop_loss
                    exit_time = bar_time
                    exit_bar_idx = i
                    exit_found = True
                    break
                elif high >= target_price:
                    trigger_price = target_price
                    exit_time = bar_time
                    exit_bar_idx = i
                    exit_found = True
                    break
            else:
                if high >= stop_loss:
                    trigger_price = stop_loss
                    exit_time = bar_time
                    exit_bar_idx = i
                    exit_found = True
                    break
                elif low <= target_price:
                    trigger_price = target_price
                    exit_time = bar_time
                    exit_bar_idx = i
                    exit_found = True
                    break

            # Calendar day DTE expiration check (30 days max for options / stocks)
            elapsed_days = (bar_time - entry_time).total_seconds() / 86400.0
            if elapsed_days >= 30.0:
                trigger_price = float(bar["close"])
                exit_time = bar_time
                exit_bar_idx = i
                exit_found = True
                break

        if not exit_found:
            if force_close:
                exit_bar_idx = sub_indices[-1] if sub_indices else (len(df) - 1)
                final_bar = df.iloc[exit_bar_idx]
                trigger_price = float(final_bar["close"])
                exit_time = final_bar.name
                exit_found = True
            else:
                return None

        # Pricing exit
        exit_bar = df.iloc[exit_bar_idx]
        elapsed_days = (exit_time - entry_time).total_seconds() / 86400.0

        if is_option:
            dte = max(30.0 - elapsed_days, 0.0)
            exit_sigma = _get_sigma(exit_bar, pos.get("metadata"))
            exit_premium = calculate_option_price(
                opt_type, S=trigger_price, K=strike, days_to_expiry=dte, sigma=exit_sigma
            )
            exit_price_or_premium = round(exit_premium, 2)
            trade_type = "OPTION"
        else:
            exit_price_or_premium = trigger_price
            trade_type = "STOCK"

        raw_pnl, pnl_pct = _compute_pnl(
            action, entry_price_or_premium, exit_price_or_premium, quantity
        )

        # Realistic Indian F&O Transaction Costs
        total_cost = calculate_fno_transaction_cost(
            entry_premium=entry_price_or_premium,
            exit_premium=exit_price_or_premium,
            quantity=quantity,
            is_option=is_option,
        )
        net_pnl = round(raw_pnl - total_cost, 2)

        trade = Trade(
            symbol=symbol,
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=round(entry_price_or_premium, 2),
            exit_price=round(exit_price_or_premium, 2),
            quantity=quantity,
            pnl=net_pnl,
            pnl_percent=round(pnl_pct, 2),
            trade_type=trade_type,
            metadata={
                "strike": strike,
                "entry_spot": pos["entry_spot"],
                "trigger_price": trigger_price,
                "strategy": pos.get("strategy_name"),
                "confidence": pos.get("confidence"),
                "transaction_cost": total_cost,
                "option_type": opt_type,
            },
        )

        return {
            "trade": trade,
            "margin_released": pos["margin_required"],
            "net_pnl": net_pnl,
        }

    def run(
        self,
        stock_dfs: Union[Dict[str, pd.DataFrame], pd.DataFrame],
        signals: Optional[List[Signal]] = None,
    ) -> Dict[str, Any]:
        """
        Run portfolio backtest simulation across stock DataFrames with chronological margin tracking.

        Args:
            stock_dfs: Dictionary mapping symbols to market DataFrames, or a single DataFrame.
            signals: Optional list of Signals. If None, generated via strategy for all stocks.

        Returns:
            Dictionary containing metrics and executed Trade objects.
        """
        # Handle single DataFrame input for backward compatibility
        if isinstance(stock_dfs, pd.DataFrame):
            if stock_dfs.empty:
                return _empty_result(self.initial_capital)
            sym = (
                str(stock_dfs["symbol"].iloc[0])
                if "symbol" in stock_dfs.columns
                else "ASSET"
            )
            stock_dfs = {sym: stock_dfs}

        if not stock_dfs:
            return _empty_result(self.initial_capital)

        # 1. Gather & Filter Signals across all stocks if not provided
        if signals is None:
            raw_signals: List[Signal] = []
            for sym, df in stock_dfs.items():
                if df is None or df.empty:
                    continue
                s_list = self.strategy.generate_signals(df)
                raw_signals.extend(
                    [s for s in s_list if self.strategy.filter_signal_rule_8(s)]
                )
            signals = raw_signals

        # Sort ALL signals chronologically by timestamp
        signals = sorted(signals, key=lambda s: pd.Timestamp(s.timestamp))

        cash: float = self.initial_capital
        open_positions: List[Dict[str, Any]] = []
        closed_trades: List[Trade] = []

        # 2. Chronological simulation loop
        for signal in signals:
            symbol = signal.symbol
            if symbol not in stock_dfs or stock_dfs[symbol].empty:
                continue

            df = stock_dfs[symbol]
            sig_time = pd.Timestamp(signal.timestamp)
            if sig_time not in df.index:
                continue

            timestamps = list(df.index)
            entry_idx = timestamps.index(sig_time)
            entry_row = df.iloc[entry_idx]
            entry_spot = float(entry_row["close"])
            action = signal.action.upper()

            # A. Mark-to-market and exit open positions whose exit criteria are met prior to/at sig_time
            still_open: List[Dict[str, Any]] = []
            for pos in open_positions:
                pos_df = stock_dfs[pos["symbol"]]
                res = self._evaluate_position_exit(
                    pos, pos_df, sig_time, force_close=False
                )
                if res is not None:
                    cash += res["margin_released"] + res["net_pnl"]
                    closed_trades.append(res["trade"])
                else:
                    still_open.append(pos)
            open_positions = still_open

            # B. Check max_concurrent_trades limit
            if len(open_positions) >= self.max_concurrent_trades:
                continue

            # C. Sizing and Margin calculation
            sigma = _get_sigma(entry_row, signal.metadata)
            entry_price = (
                float(signal.entry_price) if signal.entry_price is not None else entry_spot
            )

            # Shared stop/target resolution for both option and stock legs
            if signal.stop_loss is None or signal.target_price is None:
                stop_loss, target_price = self.risk_manager.calculate_stop_and_target(
                    entry_price, action
                )
            else:
                stop_loss = float(signal.stop_loss)
                target_price = float(signal.target_price)

            is_bullish = target_price > entry_spot

            is_option = signal.metadata.get("type") == "OPTION"
            if is_option:
                opt_type = signal.metadata.get("option_type")
                if not opt_type:
                    sig_type = str(signal.metadata.get("strategy_type", "")).upper()
                    opt_type = "p" if ("PUT" in sig_type or "PE" in sig_type) else "c"
                opt_type = str(opt_type).lower()
                target_delta = signal.metadata.get("delta_target")
                strike = find_strike_for_delta(
                    opt_type, entry_spot, target_delta, days_to_expiry=30.0, sigma=sigma
                )

                entry_premium = calculate_option_price(
                    opt_type, S=entry_spot, K=strike, days_to_expiry=30.0, sigma=sigma
                )
                stop_premium = calculate_option_price(
                    opt_type, S=stop_loss, K=strike, days_to_expiry=30.0, sigma=sigma
                )

                quantity = self.risk_manager.calculate_position_size(
                    entry_price=entry_premium,
                    stop_loss=stop_premium,
                    lot_size=self.lot_size,
                )
                if quantity == 0:
                    continue

                if action == "BUY":
                    margin_required = entry_premium * quantity
                else:
                    margin_required = (0.20 * entry_spot) * quantity

                entry_price_or_premium = entry_premium
                trade_lot_size = self.lot_size
            else:
                quantity = self.risk_manager.calculate_position_size(
                    entry_price=entry_price, stop_loss=stop_loss, lot_size=1
                )
                if quantity == 0:
                    continue

                margin_required = entry_price * quantity
                entry_price_or_premium = entry_price
                trade_lot_size = 1

            # D. Check free capital constraint
            if margin_required > cash or margin_required <= 0:
                continue

            # Deduct margin from available cash
            cash -= margin_required

            position = {
                "symbol": symbol,
                "entry_time": sig_time,
                "entry_idx": entry_idx,
                "entry_spot": entry_spot,
                "entry_price_or_premium": entry_price_or_premium,
                "stop_loss": stop_loss,
                "target_price": target_price,
                "is_bullish": is_bullish,
                "is_option": is_option,
                "option_type": signal.metadata.get("option_type", "c"),
                "strike": strike if is_option else entry_spot,
                "quantity": quantity,
                "lot_size": trade_lot_size,
                "action": action,
                "margin_required": margin_required,
                "strategy_name": signal.strategy_name,
                "confidence": signal.confidence,
                "metadata": signal.metadata,
            }
            open_positions.append(position)

        # 3. Final force close of any remaining open positions at the end of data
        for pos in open_positions:
            pos_df = stock_dfs[pos["symbol"]]
            last_time = pos_df.index[-1]
            res = self._evaluate_position_exit(
                pos, pos_df, last_time, force_close=True
            )
            if res is not None:
                cash += res["margin_released"] + res["net_pnl"]
                closed_trades.append(res["trade"])

        # 4. Summary metrics
        total_trades = len(closed_trades)
        winning_trades = sum(1 for t in closed_trades if t.pnl > 0)
        win_rate = (
            round(winning_trades / total_trades, 4) if total_trades > 0 else 0.0
        )
        total_pnl = round(sum(t.pnl for t in closed_trades), 2)
        final_capital = round(cash, 2)

        return {
            "metrics": {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "final_capital": final_capital,
            },
            "trades": closed_trades,
        }


# Alias for backward compatibility
BacktestEngine = PortfolioEngine
