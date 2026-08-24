# Project: IND OPT MKT Hermes Autonomous Lifecycle

## Architecture
- **Autonomous Market Desk Engine**:
  - **Auth Subsystem**: `src/data/upstox_auth.py` / `scripts/upstox_oauth_listener.py` handles OAuth authorization code exchange, self-healing auth on expired tokens, Chrome User-Agent header, `Api-Version: 2.0`, binding to `localhost:8501`, token cache persistence to `.env` (`UPSTOX_ACCESS_TOKEN`) and `data/cache/upstox_token.json`, immediate port release.
  - **Bridge Subsystem**: `src/api/hermes_bridge.py` exposes `check_system_status` (proactively prompting login URL on expired tokens) and `log_trade` (NLP trade parsing, ATR calculations, paper trade tracking).
  - **Strategy & Execution Subsystem**: `src/strategies/trailing.py` implements 1.2x ATR initial SL, 0.65 delta target, dynamic trailing ratchet, state persistence to `data/paper/active_trades.json`.
  - **Schedule & Dispatch Subsystem**: `~/.hermes/cron/jobs.json` orchestrates 5 daily market phases (09:00 Auth & Watchlist, 09:15-09:30 Silent ORB, 09:30-15:10 5-min Dispatcher, 15:10 Square-off, 16:00 Premarket Screening).
  - **Verification Suite**: `scripts/verify_full_desk_lifecycle.py` and `tests/` validating full desk lifecycle simulation and 100% pytest pass rate.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: Automated Upstox OAuth Flow | Upstox auth hardening, localhost:8501 listener, headers, env & cache persistence, check_system_status prompt | none | PLANNED |
| 2 | M2: Daily Market Lifecycle & Schedule Automation | ~/.hermes/cron/jobs.json scheduling (09:00, 09:15-09:30, 09:30-15:10, 15:10, 16:00), native dispatcher integration | M1 | PLANNED |
| 3 | M3: Position Tracking & Dynamic Trailing Stop Engine | src/strategies/trailing.py & log_trade in hermes_bridge, NLP order parser, 1.2x ATR SL ratchet, 0.65 delta target, active_trades persistence | M1 | PLANNED |
| 4 | M4: End-to-End Simulation & Verification Suite | scripts/verify_full_desk_lifecycle.py (Auth, Premarket, ORB Breakout, Trailing Ratchet), 100% pytest pass rate | M1, M2, M3 | PLANNED |
| 5 | M5: Git Synchronization & Final Verification | Stage, commit with feat(desk), push to origin/main, full verification pass | M4 | PLANNED |

## Interface Contracts
### `src/data/upstox_auth.py` / `scripts/upstox_oauth_listener.py` ↔ `src/api/hermes_bridge.py`
- Auth receiver binds to port 8501, uses User-Agent: Chrome / Api-Version: 2.0, saves token to `.env` (`UPSTOX_ACCESS_TOKEN`) and `data/cache/upstox_token.json`, releases port immediately.
- `check_system_status()` returns auth status, token expiry check, outputs login URL if expired.

### `src/api/hermes_bridge.py` ↔ `src/strategies/trailing.py`
- `log_trade(trade_text)` parses natural language e.g. "Bought NIFTY 24500 CE at 150.0, 2 lot".
- Trailing stop engine computes initial SL (1.2x ATR) and target (0.65 delta), tracks high-water mark, adjusts ratchet on ticks/cycles.

## Code Layout
- `src/data/`: Data providers, auth, caching
- `src/strategies/`: Strategy execution, trailing stop engine, ORB
- `src/api/`: Hermes bridge and API connectors
- `scripts/`: Operational dispatchers, listeners, and verification test scripts
- `tests/`: Automated pytest unit and integration tests
