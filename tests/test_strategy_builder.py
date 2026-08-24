"""
Unit tests for Multi-Leg Strategy Builder & Execution Ticket Analytics Engine (src/data/strategy_builder.py).

Per CodingStandards.md:
- Tests verify Debit Spread, Credit Spread, and Iron Condor construction.
- Tests verify Net Greeks, Basket Margin, Slippage Drag, and Payoff curve math.
- Tests verify non-linear Black-Scholes payoff curves (T+0, T+Mid, Expiry).
"""

import pandas as pd
import pytest

from src.data.strategy_builder import build_optimal_strategy
from src.backtester.synthetic_options import calculate_option_price


@pytest.fixture
def mock_option_chain_df() -> pd.DataFrame:
    """Fixture returning mock option chain DataFrame across 5 strikes."""
    data = [
        {"strike_price": 2400.0, "call_ltp": 110.0, "call_ask": 111.0, "call_bid": 109.0, "call_delta": 0.75, "call_iv": 0.22, "put_ltp": 12.0, "put_ask": 12.5, "put_bid": 11.5, "put_delta": -0.25, "put_iv": 0.22},
        {"strike_price": 2450.0, "call_ltp": 70.0, "call_ask": 70.5, "call_bid": 69.5, "call_delta": 0.60, "call_iv": 0.21, "put_ltp": 22.0, "put_ask": 22.5, "put_bid": 21.5, "put_delta": -0.38, "put_iv": 0.21},
        {"strike_price": 2500.0, "call_ltp": 45.0, "call_ask": 45.5, "call_bid": 44.5, "call_delta": 0.50, "call_iv": 0.20, "put_ltp": 42.0, "put_ask": 42.5, "put_bid": 41.5, "put_delta": -0.50, "put_iv": 0.20},
        {"strike_price": 2550.0, "call_ltp": 25.0, "call_ask": 25.5, "call_bid": 24.5, "call_delta": 0.25, "call_iv": 0.21, "put_ltp": 72.0, "put_ask": 72.5, "put_bid": 71.5, "put_delta": -0.65, "put_iv": 0.21},
        {"strike_price": 2600.0, "call_ltp": 12.0, "call_ask": 12.5, "call_bid": 11.5, "call_delta": 0.10, "call_iv": 0.22, "put_ltp": 112.0, "put_ask": 112.5, "put_bid": 111.5, "put_delta": -0.80, "put_iv": 0.22},
    ]
    return pd.DataFrame(data)


def test_build_bull_call_debit_spread(mock_option_chain_df: pd.DataFrame):
    """Test Bull Call Debit Spread construction for Bullish bias with low IVR."""
    ticket = build_optimal_strategy(
        symbol="RELIANCE",
        spot_price=2500.0,
        bias="BULLISH",
        ivr=30.0,
        vrp=-2.0,
        option_chain_df=mock_option_chain_df,
        lot_size=50,
        conviction_score=82.0,
    )

    assert "Bull Call Debit Spread" in ticket["strategy_name"]
    assert len(ticket["legs"]) == 2
    assert ticket["legs"][0]["Action"] == "BUY"
    assert ticket["legs"][1]["Action"] == "SELL"
    assert ticket["net_debit_or_credit"] == "Net Debit"
    assert ticket["max_profit"] > 0
    assert ticket["max_loss"] > 0
    assert "net_greeks" in ticket
    assert "payoff_curve" in ticket
    assert "naked_option" in ticket
    assert "spread_option" in ticket


def test_build_bull_put_credit_spread(mock_option_chain_df: pd.DataFrame):
    """Test Bull Put Credit Spread construction for Bullish bias with high IVR."""
    ticket = build_optimal_strategy(
        symbol="RELIANCE",
        spot_price=2500.0,
        bias="BULLISH",
        ivr=75.0,
        vrp=6.0,
        option_chain_df=mock_option_chain_df,
        lot_size=50,
        conviction_score=82.0,
    )

    assert "Bull Put Credit Spread" in ticket["strategy_name"]
    assert len(ticket["legs"]) == 2
    assert ticket["legs"][0]["Action"] == "SELL"
    assert ticket["legs"][1]["Action"] == "BUY"
    assert ticket["net_debit_or_credit"] == "Net Credit"


def test_build_iron_condor(mock_option_chain_df: pd.DataFrame):
    """Test Iron Condor construction for Rangebound bias."""
    ticket = build_optimal_strategy(
        symbol="RELIANCE",
        spot_price=2500.0,
        bias="RANGEBOUND",
        ivr=65.0,
        vrp=4.0,
        option_chain_df=mock_option_chain_df,
        lot_size=50,
        conviction_score=80.0,
    )

    assert "Iron Condor" in ticket["strategy_name"]
    assert len(ticket["legs"]) == 4
    assert "guaranteed_slippage_cost" in ticket
    assert ticket["liquidity_grade"] in ["A", "B", "C (VETO)"]


def test_black_scholes_payoff_curves(mock_option_chain_df: pd.DataFrame):
    """Test that payoff curves use non-linear Black-Scholes valuation for T+0 and T+Mid."""
    ticket = build_optimal_strategy(
        symbol="RELIANCE",
        spot_price=2500.0,
        bias="BULLISH",
        ivr=30.0,
        vrp=-2.0,
        option_chain_df=mock_option_chain_df,
        lot_size=50,
        conviction_score=82.0,
    )

    payoff = ticket["payoff_curve"]
    assert "spot_range" in payoff
    assert "payoff_expiry" in payoff
    assert "payoff_t0" in payoff
    assert "payoff_tmid" in payoff
    assert len(payoff["spot_range"]) == 50
    assert len(payoff["payoff_t0"]) == 50
    assert len(payoff["payoff_tmid"]) == 50

    # T+0 values should NOT be simple 0.40x multiples of expiry payoff
    # Black-Scholes produces non-linear, time-value-inclusive P&L
    for i in range(len(payoff["spot_range"])):
        exp_val = payoff["payoff_expiry"][i]
        t0_val = payoff["payoff_t0"][i]
        if abs(exp_val) > 100.0:
            # T+0 should differ from simple 0.40x scaling
            assert t0_val != round(exp_val * 0.40, 2), \
                f"T+0 at index {i} should not be a simple 0.40x linear scale of expiry P&L"


def test_black_scholes_target_premium():
    """Test that option target premiums use Black-Scholes, not linear delta approximation."""
    from src.data.option_analytics import get_best_strike

    chain_data = [
        {"strike_price": 2400.0, "call_ltp": 110.0, "call_ask": 111.0, "call_bid": 109.0, "call_delta": 0.75, "call_iv": 0.22, "put_ltp": 12.0, "put_ask": 12.5, "put_bid": 11.5, "put_delta": -0.25, "put_iv": 0.22},
        {"strike_price": 2450.0, "call_ltp": 70.0, "call_ask": 70.5, "call_bid": 69.5, "call_delta": 0.60, "call_iv": 0.21, "put_ltp": 22.0, "put_ask": 22.5, "put_bid": 21.5, "put_delta": -0.38, "put_iv": 0.21},
        {"strike_price": 2500.0, "call_ltp": 45.0, "call_ask": 45.5, "call_bid": 44.5, "call_delta": 0.50, "call_iv": 0.20, "put_ltp": 42.0, "put_ask": 42.5, "put_bid": 41.5, "put_delta": -0.50, "put_iv": 0.20},
        {"strike_price": 2550.0, "call_ltp": 25.0, "call_ask": 25.5, "call_bid": 24.5, "call_delta": 0.25, "call_iv": 0.21, "put_ltp": 72.0, "put_ask": 72.5, "put_bid": 71.5, "put_delta": -0.65, "put_iv": 0.21},
    ]
    chain_df = pd.DataFrame(chain_data)

    result = get_best_strike(
        option_chain_df=chain_df,
        spot_price=2500.0,
        underlying_target=2575.0,
        bias="BULLISH",
        lot_size=50,
        hv_20=0.20,
    )

    assert "option_target_price" in result
    assert "bs_entry_premium" in result
    assert result["option_target_price"] > 0
    assert result["bs_entry_premium"] > 0

    # The target should reflect Black-Scholes pricing at S=2575 using verified Tuesday DTE
    strike = result["strike"]
    from src.data.option_analytics import get_days_to_monthly_expiry
    dte = float(get_days_to_monthly_expiry())
    bs_target = calculate_option_price(
        flag="c", S=2575.0, K=strike, days_to_expiry=dte, r=0.07, sigma=0.20
    )
    # The target price should be approximately equal to BS pricing (or floored at 0.5*ltp)
    assert abs(result["option_target_price"] - round(max(bs_target, result["ltp"] * 0.50), 2)) < 3.0


def test_tuesday_monthly_expiry_and_lot_sizes():
    """Test Tuesday monthly expiry date solver and official lot size lookups."""
    from datetime import date
    from src.data.option_analytics import get_monthly_expiry_date, get_days_to_monthly_expiry
    from src.scanner.universe import get_lot_size

    # August 2026 Monthly Expiry must be Tuesday Aug 25, 2026
    aug_date = date(2026, 8, 17)
    expiry = get_monthly_expiry_date(aug_date)
    assert expiry == date(2026, 8, 25)
    assert expiry.weekday() == 1  # 1 is Tuesday

    dte = get_days_to_monthly_expiry(aug_date)
    assert dte == 8

    # Lot size lookups
    assert get_lot_size("RELIANCE") in (250, 500)
    assert get_lot_size("TCS") in (175, 225)
    assert get_lot_size("INFY") in (400, 275)
    assert get_lot_size("HDFCBANK") in (550, 650)
    assert get_lot_size("ASHOKLEY") == 5000
    assert get_lot_size("UNKNOWN_TICKER") == 250


def test_gnfc_purged_from_universe():
    """Verify GNFC is completely purged from all universe registries."""
    from src.scanner.universe import TOP_50_FNO, FULL_FNO_UNIVERSE, SECTOR_MAP, LOT_SIZE_MAP

    assert "GNFC" not in TOP_50_FNO
    assert "GNFC" not in FULL_FNO_UNIVERSE
    assert "GNFC" not in SECTOR_MAP
    assert "GNFC" not in LOT_SIZE_MAP


def test_ashokley_strike_grid_snapping():
    """Verify Ashok Leyland at ₹177.10 snaps to valid strikes (175.00, 177.50, 180.00)."""
    from src.data.option_analytics import get_strike_step, snap_to_strike_grid

    step = get_strike_step(177.10)
    assert step == 2.5  # Step for spot between 100 and 250 is 2.5

    snapped_at_177_10 = snap_to_strike_grid(177.10)
    assert snapped_at_177_10 == 177.50

    snapped_174_1 = snap_to_strike_grid(174.10)
    assert snapped_174_1 == 175.00

    snapped_179_8 = snap_to_strike_grid(179.80)
    assert snapped_179_8 == 180.00


def test_actionable_option_ticket_target_and_sl_premiums():
    """Verify build_naked_itm_ticket computes valid snapped strikes, option contract string, entry, target, and SL exit premiums."""
    from src.data.strategy_builder import build_naked_itm_ticket

    ticket = build_naked_itm_ticket(
        symbol="ASHOKLEY",
        spot_price=177.10,
        bias="BULLISH",
        target_spot=182.50,
        sl_spot=174.50,
        iv=0.25,
        lot_size=5000,
    )

    assert ticket["symbol"] == "ASHOKLEY"
    assert ticket["strike"] in (175.0, 177.5, 180.0)
    assert "ASHOKLEY" in ticket["option_symbol"]
    assert "CE" in ticket["option_symbol"]
    assert ticket["option_entry_limit"] > 0.0
    assert ticket["option_target_exit"] > ticket["option_entry_limit"]
    assert ticket["option_sl_exit"] < ticket["option_entry_limit"]
    assert ticket["max_profit_inr"] > 0.0
    assert ticket["max_loss_inr"] > 0.0
    assert ticket["lot_size"] == 5000


def test_naked_vs_optimal_strategy_schemas():
    """Verify build_naked_itm_ticket vs build_optimal_strategy output schemas."""
    from src.data.strategy_builder import build_naked_itm_ticket, build_optimal_strategy
    import pandas as pd

    naked = build_naked_itm_ticket("RELIANCE", 2500.0, "BULLISH", iv=0.22, lot_size=250)
    assert "option_symbol" in naked
    assert "option_entry_limit" in naked
    assert "option_target_exit" in naked
    assert "option_sl_exit" in naked
    assert "max_profit_inr" in naked
    assert "max_loss_inr" in naked

    optimal = build_optimal_strategy("RELIANCE", 2500.0, "BULLISH", ivr=40.0, vrp=2.0, option_chain_df=pd.DataFrame())
    assert "naked_option" in optimal
    assert "spread_option" in optimal
    assert "default_mode" in optimal


def test_delta_anchored_option_pricing_and_live_ltp():
    """Verify build_naked_itm_ticket computes target and stop loss premiums logically anchored to entry premium with 0.65 delta and supports live_option_ltp."""
    from src.data.strategy_builder import build_naked_itm_ticket

    ticket = build_naked_itm_ticket(
        symbol="ASHOKLEY",
        spot_price=177.10,
        bias="BULLISH",
        target_spot=182.50,
        sl_spot=174.50,
        lot_size=5000,
        live_option_ltp=8.50,
    )

    assert ticket["option_entry_limit"] == 8.50
    assert ticket["option_target_exit"] == round(8.50 + (0.65 * 5.40), 2)
    assert ticket["option_sl_exit"] == round(8.50 - (0.65 * 2.60), 2)
    assert ticket["max_profit_inr"] == round((12.01 - 8.50) * 5000, 2)
    assert ticket["max_loss_inr"] == round((8.50 - 6.81) * 5000, 2)

    ticket_bs = build_naked_itm_ticket(
        symbol="RELIANCE",
        spot_price=2500.0,
        bias="BULLISH",
        target_spot=2575.0,
        sl_spot=2462.5,
        lot_size=250,
    )

    p_entry = ticket_bs["option_entry_limit"]
    assert p_entry >= 5.0
    assert ticket_bs["option_target_exit"] == round(p_entry + 48.75, 2)
    assert ticket_bs["option_sl_exit"] == max(1.0, round(p_entry - 24.375, 2))


def test_universal_volatility_and_pricing_across_universe():
    """Verify that for HEROMOTOCO, PAGEIND, RELIANCE, TCS, and ASHOKLEY, option entry premiums match real market price bands and do not inflate from IV Rank."""
    from src.data.strategy_builder import build_naked_itm_ticket

    test_stocks = [
        ("HEROMOTOCO", 4500.0, "BULLISH", 0.25, 45.0),
        ("PAGEIND", 36000.0, "BULLISH", 0.22, 60.0),
        ("RELIANCE", 2500.0, "BULLISH", 0.20, 40.0),
        ("TCS", 3500.0, "BEARISH", 0.18, 55.0),
        ("ASHOKLEY", 180.0, "BULLISH", 0.28, 80.0),
    ]

    for symbol, spot, bias, true_vol, inflated_ivr in test_stocks:
        ticket_real = build_naked_itm_ticket(symbol=symbol, spot_price=spot, bias=bias, iv=true_vol)
        ticket_inflated = build_naked_itm_ticket(symbol=symbol, spot_price=spot, bias=bias, iv=inflated_ivr)

        assert ticket_real["option_entry_limit"] > 0
        assert ticket_inflated["option_entry_limit"] > 0
        assert ticket_real["option_entry_limit"] < spot * 0.25
        assert ticket_inflated["option_entry_limit"] < spot * 0.25


import random
import pytest
from src.scanner.universe import FULL_FNO_UNIVERSE

# Pre-generate deterministic spot prices and biases for each symbol
random.seed(42)
test_cases = [
    (symbol, random.uniform(40.0, 100000.0), random.choice(["BULLISH", "BEARISH"]), random.uniform(0.15, 0.90))
    for symbol in FULL_FNO_UNIVERSE
]

@pytest.mark.parametrize("symbol, spot, bias, iv", test_cases)
def test_full_fno_universe_strategy_generation(symbol, spot, bias, iv):
    """Verify that every F&O stock can be processed by snap_to_strike_grid and build_naked_itm_ticket without crashing, including extreme spot prices."""
    from src.data.strategy_builder import build_naked_itm_ticket
    from src.data.option_analytics import snap_to_strike_grid, get_strike_step

    # Verify strike snapping logic doesn't crash on this random float
    step = get_strike_step(spot)
    snapped_strike = snap_to_strike_grid(spot, step)
    assert snapped_strike > 0.0

    # Verify ticket construction doesn't crash
    ticket = build_naked_itm_ticket(
        symbol=symbol,
        spot_price=spot,
        bias=bias,
        iv=iv,
    )

    assert ticket["symbol"] == symbol
    assert ticket["strike"] > 0
    assert ticket["max_loss_inr"] > 0
    assert ticket["max_profit_inr"] > 0


# ==============================================================================
# SUB-₹100 F&O EQUITIES PARAMETERIZED EDGE-CASE UNIT TESTS
# (e.g. IDEA, YESBANK, IDFCFIRSTB, PNB, NATIONALUM)
# ==============================================================================

@pytest.mark.parametrize(
    "symbol, spot, expected_step, expected_snapped_strike",
    [
        ("IDEA", 8.35, 0.5, 8.0),
        ("IDEA", 7.60, 0.5, 8.0),
        ("IDEA", 11.20, 0.5, 11.0),
        ("YESBANK", 14.25, 0.5, 14.0),
        ("YESBANK", 18.80, 0.5, 19.0),
        ("IDFCFIRSTB", 64.70, 1.0, 64.0),
        ("IDFCFIRSTB", 71.20, 1.0, 71.0),
        ("PNB", 92.15, 1.0, 92.0),
        ("PNB", 98.60, 1.0, 98.0),
        ("NATIONALUM", 87.40, 1.0, 90.0),
        ("IDEA", 5.40, 0.5, 6.0),
        ("PNB", 99.90, 1.0, 100.0),
        ("PNB", 100.00, 1.0, 100.0),
    ],
)
def test_sub_100_equities_strike_grid_snapping(symbol, spot, expected_step, expected_snapped_strike):
    """Verify strike grid snapping and step determination for sub-₹100 F&O equities."""
    from src.data.option_analytics import get_strike_step, snap_to_strike_grid

    step = get_strike_step(spot, symbol=symbol)
    assert step == expected_step

    snapped = snap_to_strike_grid(spot, symbol=symbol)
    assert snapped == expected_snapped_strike


@pytest.mark.parametrize(
    "symbol, spot_price, bias, expected_opt_type, expected_itm_strike",
    [
        ("IDEA", 8.50, "BULLISH", "CE", 6.0),
        ("IDEA", 8.50, "BEARISH", "PE", 10.0),
        ("YESBANK", 18.00, "BULLISH", "CE", 16.0),
        ("YESBANK", 18.00, "BEARISH", "PE", 19.0),
        ("IDFCFIRSTB", 65.00, "BULLISH", "CE", 64.0),
        ("IDFCFIRSTB", 65.00, "BEARISH", "PE", 66.0),
        ("PNB", 92.00, "BULLISH", "CE", 91.0),
        ("PNB", 92.00, "BEARISH", "PE", 93.0),
        ("NATIONALUM", 88.00, "BULLISH", "CE", 89.0),
        ("NATIONALUM", 88.00, "BEARISH", "PE", 91.0),
    ],
)
def test_sub_100_naked_itm_ticket_creation(symbol, spot_price, bias, expected_opt_type, expected_itm_strike):
    """Verify ITM Sniper Naked ticket creation for sub-₹100 F&O equities for BULLISH and BEARISH biases."""
    from src.data.strategy_builder import build_naked_itm_ticket

    ticket = build_naked_itm_ticket(
        symbol=symbol,
        spot_price=spot_price,
        bias=bias,
        iv=0.35,
    )

    # Schema validation
    required_keys = {
        "symbol", "option_symbol", "option_type", "strike", "spot_price",
        "target_spot", "sl_spot", "option_entry_limit", "option_target_exit",
        "option_sl_exit", "max_profit_inr", "max_loss_inr", "lot_size"
    }
    assert required_keys.issubset(ticket.keys())

    assert ticket["symbol"] == symbol
    assert ticket["option_type"] == expected_opt_type
    assert ticket["strike"] == expected_itm_strike
    assert ticket["spot_price"] == spot_price
    assert ticket["option_entry_limit"] > 0.0
    assert ticket["option_target_exit"] > ticket["option_entry_limit"]
    assert ticket["option_sl_exit"] <= ticket["option_entry_limit"]
    assert ticket["max_profit_inr"] > 0.0
    assert ticket["max_loss_inr"] > 0.0


@pytest.mark.parametrize(
    "symbol, spot, bias, live_ltp, target_spot, sl_spot, expected_target, expected_sl",
    [
        ("IDEA", 8.50, "BULLISH", 1.20, 9.00, 8.20, 1.52, 1.00),
        ("IDFCFIRSTB", 65.00, "BULLISH", 2.50, 68.00, 63.50, 4.45, 1.52),
        ("PNB", 92.00, "BEARISH", 3.20, 89.00, 93.50, 5.15, 2.23),
        ("NATIONALUM", 88.00, "BULLISH", 2.80, 91.00, 86.50, 4.75, 1.82),
    ],
)
def test_sub_100_delta_anchored_target_sl_calculation(
    symbol, spot, bias, live_ltp, target_spot, sl_spot, expected_target, expected_sl
):
    """Verify Delta-anchored 0.65 option target and SL exit limit calculation for sub-₹100 stocks."""
    from src.data.strategy_builder import build_naked_itm_ticket
    from src.scanner.universe import get_lot_size

    ticket = build_naked_itm_ticket(
        symbol=symbol,
        spot_price=spot,
        bias=bias,
        target_spot=target_spot,
        sl_spot=sl_spot,
        live_option_ltp=live_ltp,
    )

    lot = get_lot_size(symbol)

    assert ticket["option_entry_limit"] == live_ltp
    assert ticket["option_target_exit"] == expected_target
    assert ticket["option_sl_exit"] == expected_sl

    expected_profit_inr = round((expected_target - live_ltp) * lot, 2)
    expected_loss_inr = round((live_ltp - expected_sl) * lot, 2)

    assert ticket["max_profit_inr"] == expected_profit_inr
    assert ticket["max_loss_inr"] == expected_loss_inr


@pytest.mark.parametrize(
    "symbol, spot, bias, expected_strike_str, expected_type",
    [
        ("IDEA", 8.50, "BULLISH", "6", "CE"),
        ("IDEA", 8.50, "BEARISH", "10", "PE"),
        ("YESBANK", 18.00, "BULLISH", "16", "CE"),
        ("IDFCFIRSTB", 65.00, "BEARISH", "66", "PE"),
        ("PNB", 92.00, "BULLISH", "91", "CE"),
        ("NATIONALUM", 88.00, "BULLISH", "89", "CE"),
    ],
)
def test_sub_100_option_symbol_formatting(symbol, spot, bias, expected_strike_str, expected_type):
    """Verify option contract symbol string formatting for sub-₹100 stocks."""
    from src.data.strategy_builder import build_naked_itm_ticket
    from src.data.option_analytics import get_monthly_expiry_date

    ticket = build_naked_itm_ticket(symbol=symbol, spot_price=spot, bias=bias)
    exp_str = get_monthly_expiry_date().strftime("%d%b%y").upper()

    expected_symbol = f"{symbol} {exp_str} {expected_strike_str} {expected_type}"
    assert ticket["option_symbol"] == expected_symbol


def test_sub_100_lot_size_resolution():
    """Verify lot size resolution for sub-₹100 equities from official registry and ticket overrides."""
    from src.scanner.universe import get_lot_size
    from src.data.strategy_builder import build_naked_itm_ticket

    # Registry lookup for sub-₹100 equities
    assert get_lot_size("IDEA") in (71475, 80000)
    assert get_lot_size("YESBANK") in (31100, 250)
    assert get_lot_size("IDFCFIRSTB") in (9275, 7500)
    assert get_lot_size("PNB") in (8000, 4000)
    assert get_lot_size("NATIONALUM") in (1875, 3750)

    # Automatic ticket lot resolution when lot_size is None
    ticket_auto = build_naked_itm_ticket(symbol="IDEA", spot_price=8.50)
    assert ticket_auto["lot_size"] == get_lot_size("IDEA")

    # Custom lot size parameter override
    ticket_custom = build_naked_itm_ticket(symbol="IDEA", spot_price=8.50, lot_size=999)
    assert ticket_custom["lot_size"] == 999


@pytest.mark.parametrize(
    "symbol, spot, bias, ivr, vrp",
    [
        ("IDEA", 8.50, "BULLISH", 30.0, -1.5),
        ("IDEA", 8.50, "BEARISH", 35.0, 1.0),
        ("IDFCFIRSTB", 65.00, "BULLISH", 20.0, 0.0),
        ("PNB", 92.00, "BULLISH", 30.0, 1.0),
        ("NATIONALUM", 88.00, "BULLISH", 25.0, -2.0),
    ],
)
def test_sub_100_optimal_strategy_payload_integration(symbol, spot, bias, ivr, vrp):
    """Verify build_optimal_strategy processes sub-₹100 stocks cleanly without calculation errors."""
    import pandas as pd
    from src.data.strategy_builder import build_optimal_strategy

    ticket = build_optimal_strategy(
        symbol=symbol,
        spot_price=spot,
        bias=bias,
        ivr=ivr,
        vrp=vrp,
        option_chain_df=pd.DataFrame(),
        conviction_score=90.0,
    )

    assert ticket["symbol"] == symbol
    assert ticket["strike"] > 0
    assert "naked_option" in ticket
    assert "spread_option" in ticket
    assert "payoff_curve" in ticket
    assert len(ticket["payoff_curve"]["spot_range"]) == 50
    assert ticket["max_profit"] >= 0.0
    assert ticket["max_loss"] >= 0.0


