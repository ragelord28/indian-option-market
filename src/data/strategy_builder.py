"""
Multi-Leg Strategy Builder & Execution Ticket Analytics Engine (Phase 12.5 Upgrade).

Supports both Naked Single Strike (ITM Sniper) and Multi-Leg Defined-Risk Spreads
(Bull Call Spread, Bull Put Spread, Bear Put Spread, Bear Call Spread, Iron Condor)
based on directional bias, conviction score, IV Rank (IVR), Volatility Risk Premium (VRP),
and liquidity spread gating.
Computes net position Greeks, post-slippage execution drag, defined basket margins,
and multi-curve payoff models.
"""

from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

from src.backtester.synthetic_options import calculate_option_price
from src.data.option_analytics import (
    get_days_to_monthly_expiry,
    get_monthly_expiry_date,
    get_strike_step,
    snap_to_strike_grid,
    get_adjacent_exchange_strikes,
)
from src.scanner.universe import get_lot_size


def _find_closest_strike(
    df: pd.DataFrame,
    target_delta: float,
    option_type: str,
    spot_price: float,
    fallback_strike_offset: float = 0.0,
    symbol: Optional[str] = None,
) -> pd.Series:
    """Find row in option chain dataframe closest to target delta or fallback offset."""
    delta_col = "call_delta" if option_type.upper() == "CE" else "put_delta"

    if not df.empty and delta_col in df.columns:
        deltas = df[delta_col].fillna(0.0).values
        if np.any(np.abs(deltas) > 0.01):
            diffs = np.abs(deltas - target_delta)
            best_idx = int(np.argmin(diffs))
            return df.iloc[best_idx]

    # Fallback if dataframe is empty or deltas missing
    target_strike = snap_to_strike_grid(spot_price + fallback_strike_offset, symbol=symbol)
    if not df.empty and "strike_price" in df.columns:
        diffs = np.abs(df["strike_price"].values - target_strike)
        best_idx = int(np.argmin(diffs))
        return df.iloc[best_idx]

    # Synthetic fallback row
    is_ce = option_type.upper() == "CE"
    dte = float(get_days_to_monthly_expiry())
    synth_ltp = calculate_option_price(
        flag="c" if is_ce else "p", S=spot_price, K=target_strike, days_to_expiry=dte
    )
    return pd.Series(
        {
            "strike_price": target_strike,
            "call_ltp": synth_ltp if is_ce else 10.0,
            "put_ltp": synth_ltp if not is_ce else 10.0,
            "call_delta": target_delta if is_ce else 0.50,
            "put_delta": target_delta if not is_ce else -0.50,
            "call_iv": 0.20,
            "put_iv": 0.20,
            "call_ask": synth_ltp * 1.01 if is_ce else 10.1,
            "call_bid": synth_ltp * 0.99 if is_ce else 9.9,
            "put_ask": synth_ltp * 1.01 if not is_ce else 10.1,
            "put_bid": synth_ltp * 0.99 if not is_ce else 9.9,
        }
    )


def _build_ticket_from_legs(
    symbol: str,
    strat_name: str,
    rationale: str,
    legs: List[Dict[str, Any]],
    spot_price: float,
    lot_size: int = 50,
) -> Dict[str, Any]:
    """Helper to process leg list and return full strategy ticket dictionary."""
    processed_legs = []
    total_mid_cost = 0.0
    total_slippage_cost = 0.0
    spread_pcts = []

    net_delta = 0.0
    net_theta = 0.0
    net_vega = 0.0
    net_gamma = 0.0

    for item in legs:
        idx = item["leg_idx"]
        act = item["action"]
        opt_type = item["type"]
        r = item["row"]

        raw_strike = float(r.get("strike_price", spot_price))
        strike = snap_to_strike_grid(raw_strike, symbol=symbol)
        ltp_key = "call_ltp" if opt_type == "CE" else "put_ltp"
        ask_key = "call_ask" if opt_type == "CE" else "put_ask"
        bid_key = "call_bid" if opt_type == "CE" else "put_bid"
        delta_key = "call_delta" if opt_type == "CE" else "put_delta"

        mid_ltp = float(r.get(ltp_key, 0.0))
        ask = float(r.get(ask_key, mid_ltp * 1.01 if mid_ltp > 0 else 0.0))
        bid = float(r.get(bid_key, mid_ltp * 0.99 if mid_ltp > 0 else 0.0))

        delta_val = float(r.get(delta_key, 0.65 if opt_type == "CE" else -0.65))

        # Dynamic Black-Scholes Greeks & Option Premiums
        iv_key = "call_iv" if opt_type == "CE" else "put_iv"
        sigma = float(r.get(iv_key, 0.20))
        sigma = max(sigma, 0.01)  # Prevent division by zero
        dte = float(get_days_to_monthly_expiry())
        T = max(dte, 0.5) / 365.0  # Annualized, min 0.5 day to avoid div-by-zero
        r_rate = 0.065  # Risk-free rate (India 10Y ~6.5%)
        sqrt_T = float(np.sqrt(T))

        flag = "c" if opt_type == "CE" else "p"
        p_entry_calc = calculate_option_price(flag=flag, S=spot_price, K=strike, days_to_expiry=dte, r=r_rate, sigma=sigma)

        is_ce = opt_type == "CE"
        target_spot_leg = round(spot_price * (1.03 if is_ce else 0.97), 2)
        sl_spot_leg = round(spot_price * (0.985 if is_ce else 1.015), 2)

        p_target_calc = calculate_option_price(flag=flag, S=target_spot_leg, K=strike, days_to_expiry=dte, r=r_rate, sigma=sigma)
        p_sl_calc = calculate_option_price(flag=flag, S=sl_spot_leg, K=strike, days_to_expiry=dte, r=r_rate, sigma=sigma)

        entry_ltp_final = mid_ltp if mid_ltp > 0 else p_entry_calc

        # d1, d2 for Black-Scholes
        if strike > 0 and sigma > 0:
            d1 = (np.log(spot_price / strike) + (r_rate + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
            d2 = d1 - sigma * sqrt_T
            from scipy.stats import norm
            nd1 = float(norm.pdf(d1))

            if opt_type == "CE":
                delta_val = float(norm.cdf(d1))
            else:
                delta_val = float(norm.cdf(d1) - 1.0)

            gamma_val = float(nd1 / (spot_price * sigma * sqrt_T))
            vega_val = float(spot_price * nd1 * sqrt_T / 100.0)

            if opt_type == "CE":
                theta_val = float(
                    -(spot_price * nd1 * sigma) / (2.0 * sqrt_T * 365.0)
                    - r_rate * strike * np.exp(-r_rate * T) * float(norm.cdf(d2)) / 365.0
                )
            else:
                theta_val = float(
                    -(spot_price * nd1 * sigma) / (2.0 * sqrt_T * 365.0)
                    + r_rate * strike * np.exp(-r_rate * T) * float(norm.cdf(-d2)) / 365.0
                )
        else:
            gamma_val = 0.02 if act == "BUY" else -0.02
            vega_val = 0.8 if act == "BUY" else -0.8
            theta_val = -0.5 if act == "BUY" else +0.5

        if act == "SELL":
            gamma_val = -abs(gamma_val)
            vega_val = -abs(vega_val)
            theta_val = abs(theta_val)
        else:
            gamma_val = abs(gamma_val)
            vega_val = abs(vega_val)
            theta_val = -abs(theta_val)

        if ask > 0 and entry_ltp_final > 0:
            spr = ((ask - bid) / entry_ltp_final) * 100.0
        else:
            spr = 1.0
        spread_pcts.append(spr)

        exec_price = ask if (act == "BUY" and ask > 0) else (entry_ltp_final * 1.01 if act == "BUY" else (bid if bid > 0 else entry_ltp_final * 0.99))
        mid_cash = (entry_ltp_final * lot_size) if act == "BUY" else -(entry_ltp_final * lot_size)
        exec_cash = (exec_price * lot_size) if act == "BUY" else -(exec_price * lot_size)

        total_mid_cost += mid_cash
        total_slippage_cost += (exec_cash - mid_cash)

        multiplier = 1.0 if act == "BUY" else -1.0
        net_delta += delta_val * multiplier * lot_size
        net_theta += theta_val * lot_size
        net_vega += vega_val * lot_size
        net_gamma += gamma_val * lot_size

        exp_dt = get_monthly_expiry_date()
        expiry_str = exp_dt.strftime("%d%b%y").upper()
        option_symbol = f"{symbol} {expiry_str} {strike:g} {opt_type}"

        processed_legs.append(
            {
                "#": idx,
                "Option Contract": option_symbol,
                "Action": act,
                "Valid Strike": strike,
                "Option LTP / Entry (₹)": round(entry_ltp_final, 2),
                "Target Premium (₹)": round(p_target_calc, 2),
                "SL Premium (₹)": round(p_sl_calc, 2),
                "Delta": round(delta_val, 2),
                "Lot Size": lot_size,
                "Strike": strike,
                "Type": opt_type,
                "Bid (₹)": round(bid, 2),
                "Ask (₹)": round(ask, 2),
                "Mid LTP (₹)": round(entry_ltp_final, 2),
                "Theta (₹/d)": round(theta_val, 2),
                "Vega": round(vega_val, 2),
            }
        )

    is_debit = total_mid_cost > 0
    net_cost_abs = abs(total_mid_cost)

    strikes_list = [l["Strike"] for l in processed_legs]
    min_strike = min(strikes_list)
    max_strike = max(strikes_list)
    spread_width = abs(max_strike - min_strike) if len(strikes_list) > 1 else 50.0

    clean_name = strat_name.replace("🛡️", "").replace("🎯", "").strip()

    if "Naked" in clean_name:
        max_loss = net_cost_abs
        max_profit = net_cost_abs * 2.5
        basket_margin = net_cost_abs
        breakeven = min_strike + (net_cost_abs / lot_size) if "CE" in clean_name else max_strike - (net_cost_abs / lot_size)

    elif clean_name in ("Bull Call Debit Spread", "Bear Put Debit Spread"):
        max_loss = net_cost_abs
        max_profit = max((spread_width * lot_size) - net_cost_abs, 1.0)
        basket_margin = net_cost_abs
        breakeven = min_strike + (net_cost_abs / lot_size) if clean_name == "Bull Call Debit Spread" else max_strike - (net_cost_abs / lot_size)

    elif clean_name in ("Bull Put Credit Spread", "Bear Call Credit Spread"):
        max_profit = net_cost_abs
        max_loss = max((spread_width * lot_size) - net_cost_abs, 1.0)
        basket_margin = spread_width * lot_size
        breakeven = max_strike - (net_cost_abs / lot_size) if clean_name == "Bull Put Credit Spread" else min_strike + (net_cost_abs / lot_size)

    else:  # Iron Condor
        max_profit = net_cost_abs
        wing_width = (max_strike - min_strike) / 3.0
        max_loss = max((wing_width * lot_size) - net_cost_abs, 1.0)
        basket_margin = wing_width * lot_size
        breakeven = round(spot_price, 2)

    rom_pct = (max_profit / basket_margin) * 100.0 if basket_margin > 0 else 0.0
    reward_risk_ratio = max_profit / max_loss if max_loss > 0 else 1.0
    avg_spread = float(np.mean(spread_pcts)) if spread_pcts else 1.0

    if avg_spread < 2.0:
        liq_grade = "A"
    elif avg_spread <= 4.0:
        liq_grade = "B"
    else:
        liq_grade = "C (VETO)"

    slippage_drag_pct = (total_slippage_cost / max_profit) * 100.0 if max_profit > 0 else 0.0
    slippage_veto = (slippage_drag_pct > 20.0) or (liq_grade == "C (VETO)")

    # Payoff Curve
    spot_range = np.linspace(spot_price * 0.90, spot_price * 1.10, 50)
    payoff_expiry = []
    payoff_t0 = []
    payoff_tmid = []

    for S in spot_range:
        exp_pnl = 0.0
        for leg in processed_legs:
            act = leg["Action"]
            K = leg["Strike"]
            opt_t = leg["Type"]
            mid_p = leg["Option LTP / Entry (₹)"]

            pay = max(S - K, 0.0) if opt_t == "CE" else max(K - S, 0.0)
            exp_pnl += (pay - mid_p) * lot_size if act == "BUY" else (mid_p - pay) * lot_size

        payoff_expiry.append(round(exp_pnl, 2))

        dte = float(get_days_to_monthly_expiry())
        dte_mid = max(dte / 2.0, 1.0)
        bs_pnl_t0 = 0.0
        bs_pnl_tmid = 0.0
        for leg in processed_legs:
            act = leg["Action"]
            K = leg["Strike"]
            opt_t = leg["Type"]
            mid_p = leg["Option LTP / Entry (₹)"]
            flag = "c" if opt_t == "CE" else "p"
            bs_t0 = calculate_option_price(flag=flag, S=S, K=K, days_to_expiry=dte, sigma=0.20)
            bs_tmid = calculate_option_price(flag=flag, S=S, K=K, days_to_expiry=dte_mid, sigma=0.20)
            if act == "BUY":
                bs_pnl_t0 += (bs_t0 - mid_p) * lot_size
                bs_pnl_tmid += (bs_tmid - mid_p) * lot_size
            else:
                bs_pnl_t0 += (mid_p - bs_t0) * lot_size
                bs_pnl_tmid += (mid_p - bs_tmid) * lot_size
        payoff_t0.append(round(bs_pnl_t0, 2))
        payoff_tmid.append(round(bs_pnl_tmid, 2))

    primary_leg = processed_legs[0] if processed_legs else {}
    p_entry_main = primary_leg.get("Option LTP / Entry (₹)", 0.0)
    p_target_main = primary_leg.get("Target Premium (₹)", 0.0)
    p_sl_main = primary_leg.get("SL Premium (₹)", 0.0)
    strike_main = primary_leg.get("Valid Strike", spot_price)
    opt_symbol_main = primary_leg.get("Option Contract", f"{symbol} OPT")

    return {
        "symbol": symbol,
        "strategy_name": strat_name,
        "rationale": rationale,
        "legs": processed_legs,
        "option_symbol": opt_symbol_main,
        "option_entry_limit": round(p_entry_main, 2),
        "option_target_exit": round(p_target_main, 2),
        "option_sl_exit": round(p_sl_main, 2),
        "max_profit_inr": round(max_profit, 2),
        "max_loss_inr": round(max_loss, 2),
        "strike": strike_main,
        "lot_size": lot_size,
        "net_debit_or_credit": "Net Debit" if is_debit else "Net Credit",
        "net_mid_cost": round(net_cost_abs, 2),
        "post_slippage_cost": round(net_cost_abs + total_slippage_cost, 2),
        "guaranteed_slippage_cost": round(total_slippage_cost, 2),
        "slippage_drag_pct": round(slippage_drag_pct, 1),
        "slippage_veto": slippage_veto,
        "liquidity_grade": liq_grade,
        "basket_margin": round(basket_margin, 2),
        "max_profit": round(max_profit, 2),
        "max_loss": round(max_loss, 2),
        "breakeven": round(breakeven, 2),
        "rom_pct": round(rom_pct, 1),
        "reward_risk_ratio": round(reward_risk_ratio, 2),
        "net_greeks": {
            "delta": round(net_delta, 2),
            "gamma": round(net_gamma, 4),
            "theta_per_day": round(net_theta, 2),
            "vega": round(net_vega, 2),
        },
        "payoff_curve": {
            "spot_range": [round(s, 2) for s in spot_range],
            "payoff_expiry": payoff_expiry,
            "payoff_t0": payoff_t0,
            "payoff_tmid": payoff_tmid,
        },
    }


def build_optimal_strategy(
    symbol: str,
    spot_price: float,
    bias: str,
    ivr: float,
    vrp: float,
    option_chain_df: pd.DataFrame,
    lot_size: int = 50,
    underlying_target: Optional[float] = None,
    conviction_score: float = 82.0,
) -> Dict[str, Any]:
    """
    Build optimal multi-leg options strategy execution ticket, constructing both
    Naked Single Strike (ITM Sniper) and Defined-Risk Multi-Leg Spread payloads.
    """
    if symbol:
        official_lot = get_lot_size(symbol)
        if lot_size in (1, 50) or official_lot != 250:
            lot_size = official_lot

    df = option_chain_df.copy() if not option_chain_df.empty else pd.DataFrame()
    bias_upper = bias.upper()
    is_bullish = "BULLISH" in bias_upper
    is_bearish = "BEARISH" in bias_upper
    step = round(spot_price * 0.015, 1)

    # 1. Build Naked Payload
    if is_bullish:
        r_naked = _find_closest_strike(df, 0.65, "CE", spot_price, fallback_strike_offset=-step, symbol=symbol)
        naked_legs = [{"leg_idx": 1, "action": "BUY", "type": "CE", "row": r_naked}]
        naked_name = "🎯 Naked Long CE (ITM Sniper)"
        naked_rat = f"High Conviction ({conviction_score:.1f} pts) & Low IVR ({ivr:.1f}%). Directional ITM Call Sniper."
    elif is_bearish:
        r_naked = _find_closest_strike(df, -0.65, "PE", spot_price, fallback_strike_offset=+step, symbol=symbol)
        naked_legs = [{"leg_idx": 1, "action": "BUY", "type": "PE", "row": r_naked}]
        naked_name = "🎯 Naked Long PE (ITM Sniper)"
        naked_rat = f"High Conviction ({conviction_score:.1f} pts) & Low IVR ({ivr:.1f}%). Directional ITM Put Sniper."
    else:  # Rangebound
        r_naked = _find_closest_strike(df, 0.50, "CE", spot_price, fallback_strike_offset=0.0, symbol=symbol)
        naked_legs = [{"leg_idx": 1, "action": "BUY", "type": "CE", "row": r_naked}]
        naked_name = "🎯 Naked ATM Call"
        naked_rat = "Rangebound / Mean Reversion Neutral Stance."

    naked_payload = _build_ticket_from_legs(symbol, naked_name, naked_rat, naked_legs, spot_price, lot_size)

    # 2. Build Spread Payload
    if is_bullish:
        if ivr > 60.0 or vrp > 3.0:
            r1 = _find_closest_strike(df, -0.30, "PE", spot_price, fallback_strike_offset=-step, symbol=symbol)
            r2 = _find_closest_strike(df, -0.15, "PE", spot_price, fallback_strike_offset=-step * 2.5, symbol=symbol)
            spread_legs = [{"leg_idx": 1, "action": "SELL", "type": "PE", "row": r1}, {"leg_idx": 2, "action": "BUY", "type": "PE", "row": r2}]
            spread_name = "🛡️ Bull Put Credit Spread"
            spread_rat = f"Bullish with Elevated IVR ({ivr:.1f}%). Selling premium via Bull Put Credit Spread."
        else:
            r1 = _find_closest_strike(df, 0.60, "CE", spot_price, fallback_strike_offset=-step, symbol=symbol)
            r2 = _find_closest_strike(df, 0.25, "CE", spot_price, fallback_strike_offset=+step * 1.5, symbol=symbol)
            spread_legs = [{"leg_idx": 1, "action": "BUY", "type": "CE", "row": r1}, {"leg_idx": 2, "action": "SELL", "type": "CE", "row": r2}]
            spread_name = "🛡️ Bull Call Debit Spread"
            spread_rat = f"Bullish with Moderate IVR ({ivr:.1f}%). Defined-risk Bull Call Debit Spread."
    elif is_bearish:
        if ivr > 60.0 or vrp > 3.0:
            r1 = _find_closest_strike(df, 0.30, "CE", spot_price, fallback_strike_offset=+step, symbol=symbol)
            r2 = _find_closest_strike(df, 0.15, "CE", spot_price, fallback_strike_offset=+step * 2.5, symbol=symbol)
            spread_legs = [{"leg_idx": 1, "action": "SELL", "type": "CE", "row": r1}, {"leg_idx": 2, "action": "BUY", "type": "CE", "row": r2}]
            spread_name = "🛡️ Bear Call Credit Spread"
            spread_rat = f"Bearish with Elevated IVR ({ivr:.1f}%). Selling premium via Bear Call Credit Spread."
        else:
            r1 = _find_closest_strike(df, -0.60, "PE", spot_price, fallback_strike_offset=+step, symbol=symbol)
            r2 = _find_closest_strike(df, -0.25, "PE", spot_price, fallback_strike_offset=-step * 1.5, symbol=symbol)
            spread_legs = [{"leg_idx": 1, "action": "BUY", "type": "PE", "row": r1}, {"leg_idx": 2, "action": "SELL", "type": "PE", "row": r2}]
            spread_name = "🛡️ Bear Put Debit Spread"
            spread_rat = f"Bearish with Moderate IVR ({ivr:.1f}%). Defined-risk Bear Put Debit Spread."
    else:  # Iron Condor
        rc_sell = _find_closest_strike(df, 0.20, "CE", spot_price, fallback_strike_offset=+step * 1.5, symbol=symbol)
        rc_buy = _find_closest_strike(df, 0.10, "CE", spot_price, fallback_strike_offset=+step * 3.0, symbol=symbol)
        rp_sell = _find_closest_strike(df, -0.20, "PE", spot_price, fallback_strike_offset=-step * 1.5, symbol=symbol)
        rp_buy = _find_closest_strike(df, -0.10, "PE", spot_price, fallback_strike_offset=-step * 3.0, symbol=symbol)
        spread_legs = [
            {"leg_idx": 1, "action": "SELL", "type": "CE", "row": rc_sell},
            {"leg_idx": 2, "action": "BUY", "type": "CE", "row": rc_buy},
            {"leg_idx": 3, "action": "SELL", "type": "PE", "row": rp_sell},
            {"leg_idx": 4, "action": "BUY", "type": "PE", "row": rp_buy},
        ]
        spread_name = "🛡️ Iron Condor"
        spread_rat = f"Rangebound regime (IVR={ivr:.1f}%). Dual-sided Iron Condor premium collection."

    spread_payload = _build_ticket_from_legs(symbol, spread_name, spread_rat, spread_legs, spot_price, lot_size)

    # Determine default recommended mode
    use_naked_default = (conviction_score >= 88.0) and (ivr <= 40.0)
    default_payload = naked_payload if use_naked_default else spread_payload

    res_ticket = dict(default_payload)
    res_ticket["default_mode"] = "NAKED" if use_naked_default else "SPREAD"
    res_ticket["naked_option"] = naked_payload
    res_ticket["spread_option"] = spread_payload
    return res_ticket


def build_naked_itm_ticket(
    symbol: str,
    spot_price: float,
    bias: str = "BULLISH",
    target_spot: Optional[float] = None,
    sl_spot: Optional[float] = None,
    iv: float = 0.20,
    lot_size: Optional[int] = None,
    live_option_ltp: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Build Actionable ITM Sniper Option Ticket with snapped strike grid, Black-Scholes entry / live LTP,
    and Delta-anchored Target/SL option exit limit prices.
    """
    if lot_size is None or lot_size <= 0:
        lot_size = get_lot_size(symbol)

    is_bullish = "BULLISH" in bias.upper()
    option_type = "CE" if is_bullish else "PE"

    itm_call_strike, atm_strike, itm_put_strike = get_adjacent_exchange_strikes(symbol, spot_price, steps=1)
    strike = itm_call_strike if is_bullish else itm_put_strike

    if target_spot is None:
        target_spot = round(spot_price * (1.03 if is_bullish else 0.97), 2)
    if sl_spot is None:
        sl_spot = round(spot_price * (0.985 if is_bullish else 1.015), 2)

    dte = float(get_days_to_monthly_expiry())
    flag = "c" if is_bullish else "p"

    # Real Volatility Rule: ensure sigma is derived from actual stock historical volatility
    sigma_val = float(iv if 0.05 <= iv <= 1.0 else (iv / 100.0 if iv > 1.0 else 0.22))
    sigma = min(max(sigma_val, 0.05), 1.0)

    # Entry Premium Resolution
    P_entry = None
    if live_option_ltp and float(live_option_ltp) > 0:
        P_entry = round(float(live_option_ltp), 2)
    else:
        try:
            from src.data.upstox_provider import fetch_live_option_ltp
            live_ltp_fetched = fetch_live_option_ltp(symbol, strike, option_type)
            if live_ltp_fetched and float(live_ltp_fetched) > 0:
                P_entry = round(float(live_ltp_fetched), 2)
        except Exception:
            pass

    if P_entry is None or P_entry <= 0:
        bs_price = calculate_option_price(flag=flag, S=spot_price, K=strike, days_to_expiry=dte, r=0.065, sigma=sigma)
        P_entry = max(5.0, round(bs_price, 2))

    dist_target = abs(target_spot - spot_price)
    dist_sl = abs(sl_spot - spot_price)
    delta_mag = 0.65

    P_target = round(P_entry + (delta_mag * dist_target), 2)
    P_sl = max(1.0, round(P_entry - (delta_mag * dist_sl), 2))

    exp_dt = get_monthly_expiry_date()
    expiry_str = exp_dt.strftime("%d%b%y").upper()
    option_symbol = f"{symbol} {expiry_str} {strike:g} {option_type}"

    max_profit = (P_target - P_entry) * lot_size
    max_loss = (P_entry - P_sl) * lot_size

    return {
        "symbol": symbol,
        "option_symbol": option_symbol,
        "option_type": option_type,
        "strike": strike,
        "spot_price": spot_price,
        "target_spot": target_spot,
        "sl_spot": sl_spot,
        "option_entry_limit": P_entry,
        "option_target_exit": P_target,
        "option_sl_exit": P_sl,
        "max_profit_inr": round(max_profit, 2),
        "max_loss_inr": round(max_loss, 2),
        "lot_size": lot_size,
    }
