"""
Option Analytics & Automated Strike Selection Engine.

Provides quantitative helper functions:
1. `calculate_pcr`: Computes total Put-Call Ratio (PCR) from option chain.
2. `interpret_pcr`: Maps PCR to institutional regime classification and score.
3. `calculate_vrp`: Computes Volatility Risk Premium (VRP = IV - HV).
4. `find_max_pain`: Computes Max Pain strike where option writers experience minimum total financial payout loss.
5. `rank_strikes`: Ranks and selects Top 3 optimal option contract strikes with spread liquidity gating.
6. `get_best_strike`: Selects the single optimal 'Best Strike' option contract and computes its target price.
"""

import calendar
from datetime import date, datetime, timedelta
from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd

from src.backtester.synthetic_options import calculate_option_price

NSE_HOLIDAYS_2026 = {
    date(2026, 1, 26), date(2026, 3, 6), date(2026, 4, 3),
    date(2026, 4, 14), date(2026, 5, 1), date(2026, 10, 2),
    date(2026, 10, 20), date(2026, 11, 9), date(2026, 11, 10),
    date(2026, 12, 25)
}


def get_monthly_expiry_date(dt: date | datetime | None = None) -> date:
    """
    Resolve verified Tuesday Monthly Expiry Date for NSE F&O contracts.
    NSE stock options expire on the Last Tuesday of the month.
    If Last Tuesday is an NSE Holiday or weekend, steps backward to preceding trading day.
    """
    if dt is None:
        dt = date.today()
    if isinstance(dt, datetime):
        dt = dt.date()
    year, month = dt.year, dt.month

    def _find_last_tuesday(y: int, m: int) -> date:
        last_day = calendar.monthrange(y, m)[1]
        target = date(y, m, last_day)
        # 1 is Tuesday (Monday=0, Tuesday=1, Wednesday=2, Thursday=3)
        while target.weekday() != 1:
            target -= timedelta(days=1)
        while target in NSE_HOLIDAYS_2026 or target.weekday() >= 5:
            target -= timedelta(days=1)
        return target

    expiry = _find_last_tuesday(year, month)
    if dt > expiry:
        next_m = 1 if month == 12 else month + 1
        next_y = year + 1 if month == 12 else year
        expiry = _find_last_tuesday(next_y, next_m)
    return expiry


def get_days_to_monthly_expiry(dt: date | datetime | None = None) -> int:
    """
    Calculate exact remaining Days to Monthly Expiry (DTE) for NSE F&O contracts.
    Returns minimum 1 DTE.
    """
    if dt is None:
        dt = date.today()
    if isinstance(dt, datetime):
        dt = dt.date()
    expiry = get_monthly_expiry_date(dt)
    return max((expiry - dt).days, 1)


def get_strike_step(spot: float) -> float:
    """Official NSE Equity Option Strike Step Intervals"""
    if spot <= 100:
        return 1.0
    elif spot <= 250:
        return 2.5   # e.g. ASHOKLEY (170, 172.5, 175, 177.5)
    elif spot <= 500:
        return 5.0   # e.g. SBIN, PFC
    elif spot <= 1000:
        return 10.0  # e.g. ICICIBANK, AXISBANK
    elif spot <= 2500:
        return 20.0  # e.g. RELIANCE, INFY
    elif spot <= 5000:
        return 50.0  # e.g. TCS, BAJFINANCE
    else:
        return 100.0 # e.g. HAL, PAGEIND, MARUTI


def snap_to_strike_grid(spot: float, strike_step: float | None = None) -> float:
    """Snaps any continuous floating price to the nearest valid exchange strike."""
    if strike_step is None:
        strike_step = get_strike_step(spot)
    return round(round(spot / strike_step) * strike_step, 2)


def calculate_pcr(option_chain_df: pd.DataFrame) -> float:
    """
    Calculate Put-Call Ratio (PCR) based on total Open Interest.

    Args:
        option_chain_df: DataFrame containing `call_oi` and `put_oi` columns.

    Returns:
        PCR ratio rounded to 2 decimal places. Returns 0.0 if data empty or Call OI is 0.
    """
    if option_chain_df.empty or "call_oi" not in option_chain_df.columns or "put_oi" not in option_chain_df.columns:
        return 0.0

    total_call_oi = float(option_chain_df["call_oi"].sum())
    total_put_oi = float(option_chain_df["put_oi"].sum())

    if total_call_oi <= 0:
        return 0.0

    return round(total_put_oi / total_call_oi, 2)


def interpret_pcr(pcr: float) -> Tuple[str, float]:
    """
    Classify PCR into linear institutional regime bounds.

    - PCR >= 1.20 -> Bullish Support (+1.0 score)
    - 0.80 <= PCR < 1.20 -> Neutral (0.0 score)
    - PCR < 0.80 -> Bearish Resistance (-1.0 score)

    Args:
        pcr: Put-Call Ratio float.

    Returns:
        Tuple of (regime_label: str, score: float).
    """
    if pcr >= 1.20:
        return ("Bullish Support", 1.0)
    elif pcr >= 0.80:
        return ("Neutral", 0.0)
    else:
        return ("Bearish Resistance", -1.0)


def calculate_vrp(atm_iv: float, hv_20: float) -> float:
    """
    Calculate Volatility Risk Premium (VRP = Implied Volatility - Historical Volatility).

    Args:
        atm_iv: ATM Implied Volatility (in decimal e.g. 0.25 or percentage e.g. 25.0).
        hv_20: 20-day Historical Volatility (in decimal e.g. 0.20 or percentage e.g. 20.0).

    Returns:
        VRP value as decimal (e.g. 0.05 = 5.0% premium).
    """
    iv_val = float(atm_iv)
    hv_val = float(hv_20)

    if iv_val > 1.5:
        iv_val = iv_val / 100.0
    if hv_val > 1.5:
        hv_val = hv_val / 100.0

    return round(iv_val - hv_val, 4)


def find_max_pain(option_chain_df: pd.DataFrame) -> float:
    """
    Compute Max Pain strike price from option chain DataFrame.

    Max Pain is the strike price where the cumulative intrinsic value payout
    to option buyers is minimized (option sellers experience minimum loss).

    Args:
        option_chain_df: DataFrame containing `strike_price`, `call_oi`, and `put_oi`.

    Returns:
        Max Pain strike price float.
    """
    if option_chain_df.empty or "strike_price" not in option_chain_df.columns:
        return 0.0

    strikes = option_chain_df["strike_price"].values
    call_ois = option_chain_df["call_oi"].fillna(0.0).values
    put_ois = option_chain_df["put_oi"].fillna(0.0).values

    if len(strikes) == 0:
        return 0.0

    min_loss = float("inf")
    max_pain_strike = float(strikes[0])

    for k_eval in strikes:
        call_loss = np.sum(np.maximum(k_eval - strikes, 0) * call_ois)
        put_loss = np.sum(np.maximum(strikes - k_eval, 0) * put_ois)
        total_loss = call_loss + put_loss

        if total_loss < min_loss:
            min_loss = total_loss
            max_pain_strike = float(k_eval)

    return max_pain_strike


def rank_strikes(
    option_chain_df: pd.DataFrame,
    spot_price: float,
    bias: str = "BULLISH",
    lot_size: int = 50,
    hv_20: float = 0.20,
) -> pd.DataFrame:
    """
    Rank and select Top 3 optimal option strikes with spread liquidity gating and VRP check.

    Ranks:
    - Rank 1 (Best - ITM Delta ~0.60-0.65): ITM strike nearest delta 0.60/0.65.
    - Rank 2 (Balanced - ATM Delta ~0.50): ATM strike nearest spot price.
    - Rank 3 (Aggressive - OTM Delta ~0.35-0.40): OTM strike 1 step away from ATM.

    Args:
        option_chain_df: DataFrame with option chain metrics.
        spot_price: Current underlying spot price.
        bias: Directional bias ('BULLISH' or 'BEARISH').
        lot_size: Option lot size multiplier (default 50).
        hv_20: 20-day Historical Volatility float.

    Returns:
        DataFrame containing top 3 ranked recommended strikes with liquidity_warning flag.
    """
    if option_chain_df.empty or "strike_price" not in option_chain_df.columns:
        return pd.DataFrame()

    df = option_chain_df.copy().sort_values("strike_price").reset_index(drop=True)
    is_bullish = bias.upper() == "BULLISH"

    if is_bullish:
        option_type = "CE"
        ltp_col = "call_ltp"
        iv_col = "call_iv"
        oi_col = "call_oi"
        delta_col = "call_delta"
        ask_col = "call_ask"
        bid_col = "call_bid"
    else:
        option_type = "PE"
        ltp_col = "put_ltp"
        iv_col = "put_iv"
        oi_col = "put_oi"
        delta_col = "put_delta"
        ask_col = "put_ask"
        bid_col = "put_bid"

    # Find ATM index (nearest strike to spot_price)
    strike_diffs = np.abs(df["strike_price"].values - spot_price)
    atm_idx = int(np.argmin(strike_diffs))

    # Index selections
    if is_bullish:
        itm_idx = max(0, atm_idx - 1)  # 1 strike ITM for Calls
        otm_idx = min(len(df) - 1, atm_idx + 1)  # 1 strike OTM for Calls
    else:
        itm_idx = min(len(df) - 1, atm_idx + 1)  # 1 strike ITM for Puts
        otm_idx = max(0, atm_idx - 1)  # 1 strike OTM for Puts

    selected_indices = [
        (1, "🥇 BEST (ITM)", itm_idx),
        (2, "🥈 BALANCED (ATM)", atm_idx),
        (3, "🥉 AGGRESSIVE (OTM)", otm_idx),
    ]

    rows = []
    for rank, label, idx in selected_indices:
        row_data = df.iloc[idx]
        strike = float(row_data["strike_price"])
        ltp = float(row_data.get(ltp_col, 0.0))
        iv = float(row_data.get(iv_col, 0.0))
        oi = float(row_data.get(oi_col, 0.0))

        delta = float(row_data.get(delta_col, 0.0))
        if delta == 0.0:
            if rank == 1:
                delta = 0.65 if is_bullish else -0.65
            elif rank == 2:
                delta = 0.50 if is_bullish else -0.50
            else:
                delta = 0.35 if is_bullish else -0.35

        # Bid-Ask Spread Calculation & Liquidity Gate
        if ask_col in row_data and bid_col in row_data and row_data[ask_col] > 0 and ltp > 0:
            spread_pct = round(((float(row_data[ask_col]) - float(row_data[bid_col])) / ltp) * 100.0, 2)
        else:
            spread_pct = 0.5  # Fallback estimate

        liquidity_warning = spread_pct > 4.0
        vrp_val = calculate_vrp(iv, hv_20)

        capital_per_lot = round(ltp * lot_size, 2)

        rows.append(
            {
                "Rank": rank,
                "Recommendation Label": label,
                "Strike Price": strike,
                "Option Type": option_type,
                "LTP (₹)": round(ltp, 2),
                "Delta": round(delta, 2),
                "IV (%)": round(iv * 100.0 if iv < 1.5 else iv, 1),
                "VRP (%)": round(vrp_val * 100.0, 1),
                "Open Interest": int(oi),
                "Capital per Lot (₹)": capital_per_lot,
                "Bid-Ask Spread (%)": spread_pct,
                "Liquidity Warning": liquidity_warning,
            }
        )

    res_df = pd.DataFrame(rows)
    return res_df


def get_best_strike(
    option_chain_df: pd.DataFrame,
    spot_price: float,
    underlying_target: float,
    bias: str = "BULLISH",
    lot_size: int = 50,
    hv_20: float = 0.20,
) -> Dict[str, Any]:
    """
    Select the single optimal 'Best Strike' option contract and calculate its expected target price,
    including VRP and liquidity spread gating.

    Args:
        option_chain_df: DataFrame containing option chain details.
        spot_price: Current spot price of underlying asset.
        underlying_target: Technical price target of underlying asset.
        bias: Directional strategy bias ('BULLISH' or 'BEARISH').
        lot_size: Option lot size (default 50).
        hv_20: 20-day Historical Volatility.

    Returns:
        Dictionary containing best strike metrics:
        `strike`, `type`, `ltp`, `delta`, `capital`, `option_target_price`, `vrp`, `liquidity_warning`, `spread_pct`.
    """
    is_bullish = bias.upper() == "BULLISH"
    opt_type = "CE" if is_bullish else "PE"

    if option_chain_df.empty or "strike_price" not in option_chain_df.columns:
        snapped_spot_strike = snap_to_strike_grid(spot_price)
        return {
            "strike": snapped_spot_strike,
            "type": opt_type,
            "ltp": 0.0,
            "delta": 0.65 if is_bullish else -0.65,
            "capital": 0.0,
            "option_target_price": 0.0,
            "underlying_spot": spot_price,
            "underlying_target": underlying_target,
            "vrp": 0.0,
            "liquidity_warning": False,
            "spread_pct": 0.5,
        }

    df = option_chain_df.copy().sort_values("strike_price").reset_index(drop=True)

    ltp_col = "call_ltp" if is_bullish else "put_ltp"
    delta_col = "call_delta" if is_bullish else "put_delta"
    iv_col = "call_iv" if is_bullish else "put_iv"
    ask_col = "call_ask" if is_bullish else "put_ask"
    bid_col = "call_bid" if is_bullish else "put_bid"

    deltas = df[delta_col].fillna(0.0).values if delta_col in df.columns else np.zeros(len(df))
    has_valid_deltas = np.any(np.abs(deltas) > 0.01)

    target_delta = 0.65 if is_bullish else -0.65

    if has_valid_deltas:
        diffs = np.abs(deltas - target_delta)
        best_idx = int(np.argmin(diffs))
    else:
        strikes = df["strike_price"].values
        strike_diffs = np.abs(strikes - spot_price)
        atm_idx = int(np.argmin(strike_diffs))
        if is_bullish:
            best_idx = max(0, atm_idx - 1)
        else:
            best_idx = min(len(df) - 1, atm_idx + 1)

    row = df.iloc[best_idx]
    strike = float(row["strike_price"])
    ltp = float(row.get(ltp_col, 0.0))
    delta = float(row.get(delta_col, 0.0))
    iv = float(row.get(iv_col, 0.20))

    if delta == 0.0:
        delta = 0.65 if is_bullish else -0.65

    # Spread calculation & gating
    if ask_col in row and bid_col in row and row[ask_col] > 0 and ltp > 0:
        spread_pct = round(((float(row[ask_col]) - float(row[bid_col])) / ltp) * 100.0, 2)
    else:
        spread_pct = 0.5

    liquidity_warning = spread_pct > 4.0
    vrp_val = calculate_vrp(iv, hv_20)

    # Non-linear Black-Scholes target pricing (captures Gamma expansion)
    iv_decimal = iv / 100.0 if iv > 1.0 else iv
    dte = float(get_days_to_monthly_expiry())
    flag = 'c' if is_bullish else 'p'
    target_premium = calculate_option_price(
        flag=flag,
        S=underlying_target,
        K=strike,
        days_to_expiry=dte,
        r=0.07,
        sigma=iv_decimal,
    )
    option_target_price = round(max(target_premium, ltp * 0.50), 2)
    bs_entry_premium = calculate_option_price(
        flag=flag,
        S=spot_price,
        K=strike,
        days_to_expiry=dte,
        r=0.07,
        sigma=iv_decimal,
    )
    capital_required = round(ltp * lot_size, 2)

    return {
        "strike": strike,
        "type": opt_type,
        "ltp": round(ltp, 2),
        "delta": round(delta, 2),
        "capital": capital_required,
        "option_target_price": option_target_price,
        "underlying_spot": round(spot_price, 2),
        "underlying_target": round(underlying_target, 2),
        "vrp": round(vrp_val * 100.0, 1),
        "liquidity_warning": liquidity_warning,
        "spread_pct": spread_pct,
        "bs_entry_premium": round(bs_entry_premium, 2),
    }
