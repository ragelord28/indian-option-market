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
