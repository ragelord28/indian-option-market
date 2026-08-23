"""
Risk & Position Management Engine (src/risk/).

Defines RiskManager for position sizing, ATR/percentage stop-loss, and target price calculations.
"""

from typing import Optional, Tuple


def calculate_position_size(
    account_capital: float,
    risk_per_trade_pct: float,
    entry_price: float,
    stop_loss: float,
    lot_size: int = 1,
) -> int:
    """
    Calculate position sizing in units strictly enforcing risk budget.

    Args:
        account_capital: Total account capital.
        risk_per_trade_pct: Max risk percentage (e.g. 2.0 for 2% or 0.02).
        entry_price: Entry price per share/contract.
        stop_loss: Stop-loss price per share/contract.
        lot_size: Minimum trading lot size increment.

    Returns:
        Position size (units) rounded down to lot_size. Returns 0 if the risk budget
        covers less than 1 lot or inputs are invalid (non-positive lot_size included).
    """
    if entry_price <= 0 or abs(entry_price - stop_loss) <= 0:
        return 0
    if lot_size <= 0:  # guard: floor-division sizing below would raise ZeroDivisionError
        return 0

    pct = risk_per_trade_pct / 100.0 if risk_per_trade_pct > 1.0 else risk_per_trade_pct
    max_risk_amount = account_capital * pct
    risk_per_unit = abs(entry_price - stop_loss)

    allowed_units = max_risk_amount / risk_per_unit
    num_lots = int(allowed_units // lot_size)

    # Cap notional value to account capital
    max_notional_lots = int(account_capital // (lot_size * entry_price)) if (lot_size * entry_price) > 0 else 0
    num_lots = min(num_lots, max_notional_lots)

    if num_lots < 1:
        return 0  # Strictly enforce risk budget: NEVER force 1 lot if capital budget is exceeded!

    return num_lots * lot_size


class RiskManager:
    """
    Manages trade position sizing, stop-loss calculation, and target pricing.
    """

    def __init__(
        self,
        account_capital: float = 100000.0,
        max_risk_per_trade_pct: float = 0.02,
        risk_reward_ratio: float = 2.0,
    ):
        """
        Initialize the RiskManager.

        Args:
            account_capital: Total portfolio capital (default 100,000.0).
            max_risk_per_trade_pct: Maximum capital risk per trade as decimal (default 0.02 = 2%).
            risk_reward_ratio: Reward-to-Risk multiplier for target price (default 2.0).
        """
        self.account_capital: float = account_capital
        self.max_risk_per_trade_pct: float = max_risk_per_trade_pct
        self.risk_reward_ratio: float = risk_reward_ratio

    def calculate_stop_and_target(
        self, entry_price: float, action: str, atr: Optional[float] = None
    ) -> Tuple[float, float]:
        """
        Calculate stop-loss and profit target prices.

        Args:
            entry_price: Entry trigger price.
            action: Trade action ('BUY' or 'SELL').
            atr: Optional Average True Range value. If provided and > 0, stop distance = 1.5 * ATR.
                 Otherwise default stop distance = 2% of entry price.

        Returns:
            Tuple of (stop_loss, target_price).
        """
        if entry_price <= 0:
            raise ValueError("Entry price must be positive.")

        if atr is not None and atr > 0:
            distance = 1.5 * atr
        else:
            distance = 0.02 * entry_price

        action_upper = action.upper()
        if action_upper == "BUY":
            stop_loss = round(entry_price - distance, 2)
            target_price = round(entry_price + (distance * self.risk_reward_ratio), 2)
        elif action_upper == "SELL":
            stop_loss = round(entry_price + distance, 2)
            target_price = round(entry_price - (distance * self.risk_reward_ratio), 2)
        else:
            raise ValueError(f"Invalid trade action '{action}'. Must be 'BUY' or 'SELL'.")

        return stop_loss, target_price

    def calculate_position_size(
        self, entry_price: float, stop_loss: float, lot_size: int = 1
    ) -> int:
        """
        Calculate position sizing in units/shares based on account risk capital.

        Args:
            entry_price: Price per share/contract at entry.
            stop_loss: Price per share/contract at stop-loss.
            lot_size: Minimum trading lot increment (default 1).

        Returns:
            Position size rounded down to nearest lot_size. Returns 0 if risk budget < 1 lot.
        """
        if entry_price <= 0 or abs(entry_price - stop_loss) <= 0:
            raise ValueError("Entry price and risk per unit must be > 0")

        return calculate_position_size(
            account_capital=self.account_capital,
            risk_per_trade_pct=self.max_risk_per_trade_pct,
            entry_price=entry_price,
            stop_loss=stop_loss,
            lot_size=lot_size,
        )

