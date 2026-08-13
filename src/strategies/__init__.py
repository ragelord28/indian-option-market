"""
Strategy Engine Module for the Indian Option Market platform.

Provides BaseStrategy interface, Signal data structure, Rule 8 quality filtering,
and Phase 6 / Phase 8.5 / Phase 10 concrete trading strategy implementations.
"""

from src.strategies.base_strategy import Signal, BaseStrategy
from src.strategies.orb_momentum import ORBMomentumStrategy
from src.strategies.hedged_vol_premium import HedgedVolPremiumStrategy
from src.strategies.oi_swing import OISwingStrategy
from src.strategies.custom_research_strategy import RelativeStrengthVWAPReversionStrategy
from src.strategies.composite_holy_grail import CompositeHolyGrailStrategy
from src.strategies.avpc_afternoon import AVPCAfternoonStrategy

__all__ = [
    "Signal",
    "BaseStrategy",
    "ORBMomentumStrategy",
    "HedgedVolPremiumStrategy",
    "OISwingStrategy",
    "RelativeStrengthVWAPReversionStrategy",
    "CompositeHolyGrailStrategy",
    "AVPCAfternoonStrategy",
]
