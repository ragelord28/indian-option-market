# Roadmap.md — Indian Option Market Development Roadmap

## Guiding Principle
Build one thin, working, end-to-end vertical slice first. Prove the
architecture on a single strategy and a single stock before expanding data
providers, adding strategies, or connecting live trading APIs.

## Phase 0 — Knowledge Base & Environment Setup
- Finalize Core Knowledge Base in `/docs/` (`Core.md`, `Vision.md`,
  `Architecture.md`, `Roadmap.md`, `CodingStandards.md`, `ProjectStatus.md`).
- Configure Python virtual environment and Git repository.
- Verify that AI collaborators have full access to `/docs/` as shared context.
*Status*: In Progress

## Phase 1 — Data Ingestion Layer (`src/data/`)
- Define standard internal market data schema (Pandas DataFrame / Data Classes).
- Implement `YahooFinanceProvider` adapter for historical OHLCV data.
- Fetch and cache historical daily data for a single test stock (e.g.,
  `RELIANCE.NS`) in Parquet/SQLite format.
- Write unit tests in `tests/test_data.py` to verify data fetching and caching.

## Phase 2 — Minimal Strategy Engine (`src/strategies/`)
- Implement a baseline strategy (e.g., Simple Moving Average Crossover)
  operating on the standard data format.
- Ensure strict separation between strategy calculation and data retrieval.
- Write unit tests in `tests/test_strategies.py`.

## Phase 3 — Minimal Backtesting Engine (`src/backtester/`)
- Build a backtest runner that feeds historical cached data to the Strategy Engine.
- Calculate basic performance metrics: Total Trades, Win Rate, Net P&L.
- Note: fees and slippage modeling are deliberately excluded in this phase —
  logged as a known simplification, to be addressed post-Phase 5.
- Write unit tests in `tests/test_backtester.py`.

## Phase 4 — Risk & Signal Filtering (`src/risk/`, `src/signals/`)
- Add basic stop-loss and target price logic in `src/risk/`.
- Add confidence scoring and **Core.md Rule 8** filtering in `src/signals/`.
- Verify the complete offline vertical slice:
  `Data` → `Strategy` → `Risk` → `Signal Filter` → `Backtest Report`.

## Phase 5 — Checkpoint & Architecture Review
- Evaluate Phase 1–4 output and performance metrics.
- Record key findings and design adjustments in `docs/Decisions.md`.
- Plan Phase 6+ (Upstox API integration, option chain processing,
  orchestrator loop, dashboard UI).

## Future Phases (Planned Post-Phase 5)
- Upstox API live data integration (`UpstoxProvider`).
- Option chain processing & options backtesting mechanics.
- Live Orchestrator monitoring loop (`src/orchestrator/`).
- Audit logging (`src/logging/`).
- Dashboard UI (`src/ui/`).
- Expansion to the full ~50–150 FnO stock universe.

## Why future phases aren't detailed yet
Detailed planning happens after the Phase 5 checkpoint, using real results
from Phases 1–4 — not before.
