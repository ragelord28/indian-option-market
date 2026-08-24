# Original User Request

## 2026-08-24T13:45:12Z

Verify, harden, and stress-test the complete autonomous lifecycle of the IND OPT MKT Hermes bot across all 5 operational phases.

Working directory: /home/radhe-radhe/Documents/indian-option-market
Integrity mode: development

## Requirements

### R1. Automated Upstox OAuth Flow (Self-Healing Auth)
- Harden `src/data/upstox_auth.py` (or create `scripts/upstox_oauth_listener.py` if missing).
- Ensure `check_system_status` (in `src/api/hermes_bridge.py`) proactively outputs the login URL if the token is expired.
- The OAuth receiver must automatically bind to `localhost:8501`, use an explicit Chrome `User-Agent` header to prevent Cloudflare 1010 blocks, include `Api-Version: 2.0`, and write the token to `.env` (`UPSTOX_ACCESS_TOKEN`) and `data/cache/upstox_token.json`.
- The receiver must release the port immediately after approval.

### R2. Daily Market Lifecycle & Schedule Automation
- Ensure the Hermes cron jobs in `~/.hermes/cron/jobs.json` correctly orchestrate the trading day:
  - 09:00: Check auth status, load watchlist.
  - 09:15-09:30: Silent ORB window.
  - 09:30-15:10: Run `scripts/hermes_native_dispatcher.py` every 5 mins (live LTP, ORB breakouts, direct stream, `notify-send`).
  - 15:10: Mandatory Intraday Square-off.
  - 16:00: Execute Pre-market screening pipeline.

### R3. Position Tracking & Dynamic Trailing Stop Engine
- Harden `src/strategies/trailing.py` and `log_trade` in `src/api/hermes_bridge.py`.
- The agent must parse natural language like "Bought <SYMBOL> <STRIKE> <CE/PE> at <PRICE>, <LOTS> lot", calculate the 1.2x ATR initial SL and 0.65 delta target, and log it to `data/paper/active_trades.json` (or active positions).
- In the 5-minute cycle, the engine must evaluate live prices against the 1.2x ATR trailing stop ratchet and alert on target, stop loss, or ratchet.

### R4. End-to-End Simulation & Verification Suite
- Create and run `scripts/verify_full_desk_lifecycle.py` which executes:
  1. Auth test (read/refresh cache).
  2. Premarket & D-1 test.
  3. ORB Setup & Breakout Simulation (injecting simulated ticks).
  4. Trade Logging & Trailing Test (simulating multi-step price changes).

### R5. Git Synchronization
- Stage, commit (`feat(desk): harden autonomous lifecycle, oauth listener, and position trailing`), and push to `origin/main`.

## Acceptance Criteria

### Unit Tests
- [ ] Run `PYTHONPATH=. venv/bin/pytest tests/` and confirm 100% test pass rate.

### Lifecycle Verification
- [ ] Running `PYTHONPATH=. venv/bin/python3 scripts/verify_full_desk_lifecycle.py` completes with zero errors and validates the auth, ORB breakout generation, and trailing stop ratchet logic.

### Auth Module Hardening
- [ ] `src/data/upstox_auth.py` includes the explicit headers (`User-Agent`, `Api-Version: 2.0`) and binds to 8501.
