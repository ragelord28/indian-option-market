"""
Global Tunable Settings — Indian Option Market Platform.

Single source of truth for quantitative parameters shared by the trade watcher,
strategy builder, and the Hermes agent bridge. Values here must stay in sync
with the backtest arena findings (ruflo_arena) and the unit-test expectations.
"""

# --- Dynamic Trailing Stop (trade_watcher + hermes_bridge) -------------------
# Backtest-optimal Sharpe (6.78) regime: 1.2x ATR trail distance ratcheting on
# a +1.5% directional spot move. Bullish SL only ratchets UP (max); Bearish SL
# only ratchets DOWN (min).
TRAILING_STOP_ATR_MULTIPLIER: float = 1.2
TRAILING_TRIGGER_SPOT_PCT: float = 1.5

# --- Delta-Anchored Option Exit Limits (strategy_builder + hermes_bridge) ----
# Target/SL option premiums scale with underlying spot distance x delta anchor.
DELTA_ANCHOR: float = 0.65

# --- Fallback Estimates (used when live quote/ATR unavailable) ---------------
DEFAULT_ATR_PCT_OF_SPOT: float = 0.015  # 1.5% of spot when ATR unknown
TARGET_SPOT_PCT: float = 3.0            # +/-3% technical target move

# --- Hermes Agent Bridge Polling ---------------------------------------------
HERMES_POLL_INTERVAL_SEC: int = 300  # 5-minute diff polling during market hours
