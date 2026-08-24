# Execution Plan: IND OPT MKT Hermes Autonomous Lifecycle

## Overview
Orchestration plan to fulfill R1 through R5:
1. Exploration Phase:
   - Spawn 3 Explorers in parallel to inspect:
     - Explorer 1: Upstox OAuth subsystem (`src/data/upstox_auth.py`, `src/api/hermes_bridge.py`, auth listener, headers, port 8501, `.env` and `data/cache/upstox_token.json` caching).
     - Explorer 2: Market schedule & cron subsystem (`~/.hermes/cron/jobs.json`, `scripts/hermes_native_dispatcher.py`, 5 market phases).
     - Explorer 3: Position tracking, trailing stop engine, and simulation suite (`src/strategies/trailing.py`, `log_trade`, NLP parser, `scripts/verify_full_desk_lifecycle.py`, `tests/`).
2. Milestone Execution (Worker -> Reviewer -> Challenger -> Auditor -> Gate):
   - **Milestone 1**: Automated Upstox OAuth Flow & Self-Healing Auth (R1)
   - **Milestone 2**: Daily Market Lifecycle & Schedule Automation (R2)
   - **Milestone 3**: Position Tracking & Dynamic Trailing Stop Engine (R3)
   - **Milestone 4**: End-to-End Simulation & Verification Suite (R4)
   - **Milestone 5**: Git Synchronization & Final Victory Check (R5)
3. Dual-Track E2E Testing:
   - Create and verify `TEST_INFRA.md` and `TEST_READY.md`.
   - Ensure 100% pytest test pass rate.
   - Run `PYTHONPATH=. venv/bin/python3 scripts/verify_full_desk_lifecycle.py` with zero errors.
4. Forensic Integrity Audits at each milestone and final victory audit before Sentinel handoff.
