# Decisions.md — Architecture Decision Records (ADR)

This document records major technical decisions, including context, rationale, and trade-offs.

---

## ADR-001: Manual Trade Execution Only
- **Date**: 2026-08-05
- **Status**: Accepted
- **Context**: The platform is designed for research and decision support, not automated execution.
- **Decision**: All trade execution remains manual. The system will never contain automated order placement code.
- **Consequences**: Eliminates algorithmic execution risk. Keeps development focused on analysis, risk management, and signal quality.

---

## ADR-002: Data Adapter Pattern & Yahoo Finance Initial Provider
- **Date**: 2026-08-05
- **Status**: Accepted
- **Context**: We need to build and test initial strategy modules without requiring live paid API credentials immediately.
- **Decision**: Use a pluggable Adapter Pattern in `src/data/`. Implement `YahooFinanceProvider` first for historical stock data,
  followed by `UpstoxProvider` for live market data in later phases (with options-chain data handling flagged as a separate open item — see Architecture.md).
- **Consequences**: Downstream strategy and backtesting modules consume a standardized internal data format and are agnostic to data sources.
  *Note on data limitation*: Yahoo Finance only provides ~7 days of 1-minute intraday data, reinforcing the necessity of Upstox integration for historical intraday strategy backtesting.

---

## ADR-003: Backtest–Live Strategy Parity
- **Date**: 2026-08-05
- **Status**: Accepted
- **Context**: Writing separate code paths for backtesting and live monitoring introduces logic drift and execution bugs.
- **Decision**: Strategy logic in `src/strategies/` is written once and shared by both the Backtesting Engine and the Live Orchestrator.
- **Consequences**: Ensures that live strategy calculations behave identically to historical backtests.

---

## ADR-004: Internal Signal Quality Filtering (Rule 8)
- **Date**: 2026-08-05
- **Status**: Accepted
- **Context**: Noisy or weak trade signals create decision fatigue.
- **Decision**: Suppress low-confidence setups internally within `src/signals/`. Only high-confidence setups meeting quality thresholds are surfaced.
- **Consequences**: Emphasizes signal quality over quantity. Suppressed signals are logged for audit purposes.

---

## ADR-005: Standard Internal Market Data Schema & Provider Interface
- **Date**: 2026-08-06
- **Status**: Accepted
- **Context**: Modules outside `src/data/` must consume a unified, standardized internal market data structure, regardless of the underlying raw data provider (Yahoo Finance, Upstox, etc.).
- **Decision**: 
  - Standardized market data DataFrames must use a `DatetimeIndex` named `timestamp` localized to Indian Standard Time (IST, `Asia/Kolkata`).
  - Required columns: `symbol` (str), `open` (float64), `high` (float64), `low` (float64), `close` (float64), `adj_close` (float64), `volume` (int64/float64), `open_interest` (float64).
  - Allowed internal symbol characters include uppercase letters, numbers, underscores, ampersands, and hyphens (e.g., `RELIANCE`, `M&M`, `BAJAJ-AUTO`, `NIFTY50`; disallowed: provider suffixes like `.NS` or `^`, lowercase tickers).
  - Data ingestion adapters must inherit from `BaseDataProvider` and adhere strictly to this schema.
- **Consequences**: Downstream strategy, backtesting, risk, and signal modules consume a consistent schema and timezone, cleanly decoupled from data provider specifics.

---

## ADR-006: The Data Funnel & API Limit Protection
- **Date**: 2026-08-07
- **Status**: Accepted
- **Context**: Querying broker APIs (Upstox) continuously across a broad 150 F&O stock universe risks hitting rate limits and consuming quota unnecessarily.
- **Decision**: High-rate-limit broker APIs (Upstox) are strictly reserved for live D-Day execution on narrow shortlists (3–5 stocks) and interactive trade validation. Broad D-1 scanning and historical backtesting must rely on free data sources (`yfinance`, `nsepython`) and synthetic Black-Scholes option pricing (`py_vollib`).
- **Consequences**: Eliminates broker API rate limit breaches, optimizes execution speed during live market hours, and enables cost-effective offline backtesting.



