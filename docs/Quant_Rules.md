# Quantitative Rules & Boundaries
*Mandatory rulebook for the Strategy Engine.*
## 1. Greek Parameter Limits
- **Delta:** Directional Buying (0.40 to 0.60). Premium Selling (0.15 to 0.25). Reject buying deep OTM options (Delta < 0.15).
- **Gamma:** Avoid holding high Gamma (NTM) options overnight in the last 2 days before expiry.
- **Theta:** Buyers use tight trailing stops (last 7 days). Sellers target 45-to-7 DTE.
- **Vega:** Do NOT buy options when IVR > 50 or IVP > 80 (IV crush risk).
## 2. Synthetic Option Pricing (Black-Scholes)
- **Pricing Model:** Black-Scholes-Merton (`py_vollib`).
- **Risk-Free Rate (r):** 6.5% (0.065) - Indian RBI Repo Rate proxy.
## 3. Approved Options Strategies
- **Directional:** Long Call / Long Put on momentum breakouts.
- **Non-Directional:** Bear Call / Bull Put Credit Spreads (when IVR > 50).
## 4. Signal Invalidation Rules (Rule 8)
Signals are suppressed if: Confidence < 0.60, Bid-Ask spread > 5%, or IV > 80 for buyers.
