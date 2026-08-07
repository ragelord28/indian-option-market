"""
Unit tests for Risk Management Engine (src/risk/).

Per CodingStandards.md:
- Tests mirror src/ structure (src/risk/ -> tests/test_risk.py).
- Tests cover stop-loss/target calculations and position sizing logic.
"""

import pytest
from src.risk.risk_manager import RiskManager


def test_risk_manager_default_stop_and_target():
    """Test 2% default percentage stop loss and 2:1 target calculation for BUY and SELL."""
    rm = RiskManager(account_capital=100000.0, max_risk_per_trade_pct=0.02, risk_reward_ratio=2.0)

    # Entry = 100.0, BUY action. Distance = 2.0 (2%). Stop = 98.0, Target = 104.0
    stop, target = rm.calculate_stop_and_target(entry_price=100.0, action="BUY")
    assert stop == 98.0
    assert target == 104.0

    # Entry = 100.0, SELL action. Distance = 2.0. Stop = 102.0, Target = 96.0
    stop_sell, target_sell = rm.calculate_stop_and_target(entry_price=100.0, action="SELL")
    assert stop_sell == 102.0
    assert target_sell == 96.0


def test_risk_manager_atr_stop_and_target():
    """Test ATR-based stop loss calculation (1.5 * ATR)."""
    rm = RiskManager(account_capital=100000.0, max_risk_per_trade_pct=0.02, risk_reward_ratio=2.0)

    # Entry = 100.0, ATR = 4.0. Distance = 6.0. Stop = 94.0, Target = 112.0
    stop, target = rm.calculate_stop_and_target(entry_price=100.0, action="BUY", atr=4.0)
    assert stop == 94.0
    assert target == 112.0


def test_risk_manager_position_size():
    """Test position sizing based on risk capital limits."""
    rm = RiskManager(account_capital=100000.0, max_risk_per_trade_pct=0.02)
    # Capital = 100,000, Max Risk = 2,000. Entry = 100, Stop = 98 -> Risk per unit = 2.0
    # Shares = 2000 / 2.0 = 1000 shares
    pos_size = rm.calculate_position_size(entry_price=100.0, stop_loss=98.0, lot_size=1)
    assert pos_size == 1000

    # With lot_size = 75 (F&O lot size) -> 1000 // 75 = 13 lots = 975 shares
    pos_size_lots = rm.calculate_position_size(entry_price=100.0, stop_loss=98.0, lot_size=75)
    assert pos_size_lots == 975


def test_risk_manager_invalid_inputs():
    """Test handling of invalid inputs."""
    rm = RiskManager()
    with pytest.raises(ValueError, match="Entry price must be positive"):
        rm.calculate_stop_and_target(entry_price=-10.0, action="BUY")

    with pytest.raises(ValueError, match="Invalid trade action"):
        rm.calculate_stop_and_target(entry_price=100.0, action="HOLD")
