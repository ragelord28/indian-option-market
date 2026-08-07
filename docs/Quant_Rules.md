# Quantitative Rules & Boundaries
*Mandatory rulebook for the Strategy Engine.*

## 1. Greek Parameter Limits
- **Delta:**
  - Directional Buying: Standard target 0.40 to 0.60 (ATM to slightly ITM).
  - Premium Selling (Credit Spreads): Target 0.15 to 0.25.
  - Deep OTM Exception (Delta < 0.15): Allowed ONLY for high-momentum or catalyst events (e.g., earnings breakouts, major news events). MUST meet strict liquidity checks (Bid-Ask spread <= 3% of premium and active Open Interest).
- **Gamma:** Avoid holding high Gamma (NTM) options overnight in the last 2 days before expiry.
- **Theta:** Buyers use tight trailing stops (last 7 days). Sellers target 45-to-7 DTE.
- **Vega:** Do NOT buy options when IVR > 50 or IVP > 80 (IV crush risk).

## 2. Synthetic Option Pricing (Black-Scholes)
- **Pricing Model:** Black-Scholes-Merton (`py_vollib`).
- **Risk-Free Rate (r):** 6.5% (0.065) - Indian RBI Repo Rate proxy.

## 3. Approved Options Strategies
- **Directional:** Long Call / Long Put on momentum breakouts.
- **Non-Directional:** Bear Call / Bull Put Credit Spreads (when IVR > 50).
- **Momentum Deep OTM Snipe:** Small position sizing on high-catalyst events with strict liquidity checks.

## 4. Signal Invalidation Rules (Rule 8 Integration)
- Signals are suppressed if: Confidence < 0.60, Bid-Ask spread > 5%, or IV > 80 for buyers.
- **Deep OTM Invalidation:** Any Deep OTM signal (Delta < 0.15) lacking an explicit momentum/catalyst flag OR with a Bid-Ask spread > 3% is automatically suppressed by Rule 8.
