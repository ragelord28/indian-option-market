"""
Risk & Position Management Engine (src/risk/).

Defines RiskManager for position sizing, ATR/percentage stop-loss, and target price calculations.
"""

from typing import Optional, Tuple


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
        self.account_capital = account_capital
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.risk_reward_ratio = risk_reward_ratio

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
            Position size rounded down to the nearest lot_size, respecting risk floor and notional capital cap.
        """
        risk_per_unit = abs(entry_price - stop_loss)

        if entry_price <= 0 or risk_per_unit <= 0:
            raise ValueError("Entry price and risk per unit must be > 0")

        max_risk_amount = self.account_capital * self.max_risk_per_trade_pct
        raw_shares = max_risk_amount / risk_per_unit
        num_lots = int(raw_shares // lot_size)

        # Fix 1 (The Floor): If num_lots == 0, return 0 (do not force a trade that breaches risk)
        if num_lots == 0:
            return 0

        # Fix 2 (The Notional Cap): Ensure total notional value does not exceed account capital
        notional_value = num_lots * lot_size * entry_price
        while notional_value > self.account_capital and num_lots > 0:
            num_lots -= 1
            notional_value = num_lots * lot_size * entry_price

        return num_lots * lot_size
