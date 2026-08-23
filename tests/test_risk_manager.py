"""
Unit tests for Risk Management Engine position sizing & floor enforcement (src/risk/risk_manager.py).
"""

import pytest
from src.risk.risk_manager import RiskManager, calculate_position_size


def test_calculate_position_size_returns_zero_on_sub_one_lot():
    """Verify calculate_position_size returns 0 when risk budget is smaller than 1 lot risk."""
    # Account capital = 100,000, max risk = 2% = 2,000.
    # Entry = 100.0, Stop = 90.0 -> Risk per unit = 10.0. Max units = 200.
    # With lot_size = 500 -> num_lots = 200 // 500 = 0.
    # Must strictly return 0 (never force 1 lot)!
    size = calculate_position_size(
        account_capital=100000.0,
        risk_per_trade_pct=2.0,
        entry_price=100.0,
        stop_loss=90.0,
        lot_size=500,
    )
    assert size == 0

    rm = RiskManager(account_capital=100000.0, max_risk_per_trade_pct=0.02)
    size_rm = rm.calculate_position_size(entry_price=100.0, stop_loss=90.0, lot_size=500)
    assert size_rm == 0


def test_calculate_position_size_normal_lot():
    """Verify calculate_position_size correctly sizes valid trades."""
    # Account capital = 1,000,000, max risk = 2% = 20,000.
    # Entry = 100.0, Stop = 95.0 -> Risk per unit = 5.0. Max units = 4000.
    # With lot_size = 250 -> 4000 // 250 = 16 lots = 4000 units.
    size = calculate_position_size(
        account_capital=1000000.0,
        risk_per_trade_pct=2.0,
        entry_price=100.0,
        stop_loss=95.0,
        lot_size=250,
    )
    assert size == 4000


def test_calculate_position_size_zero_or_negative_risk():
    """Verify calculate_position_size returns 0 on zero or invalid risk per unit."""
    assert calculate_position_size(100000.0, 2.0, 100.0, 100.0, 50) == 0
    assert calculate_position_size(100000.0, 2.0, -10.0, 90.0, 50) == 0
