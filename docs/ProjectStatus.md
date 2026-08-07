# ProjectStatus.md — Active Development Tracker

## Current Overview
- **Active Phase**: Phase 2 — Minimal Strategy Engine (`src/strategies/`)
- **Status**: Phase 1 (Data Ingestion Layer) Complete. `BaseDataProvider`, `YahooFinanceProvider`, ADR-005 schema validation, Parquet caching, and unit tests implemented and verified.

## Knowledge Base Checklist
- [x] `docs/Core.md` — Project Constitution
- [x] `docs/Vision.md` — Scope & Capabilities
- [x] `docs/Architecture.md` — System Design & Data Pipeline
- [x] `docs/Roadmap.md` — Development Roadmap
- [x] `docs/CodingStandards.md` — Code Quality & Testing Rules
- [x] `docs/ProjectStatus.md` — Active Development Tracker
- [x] `docs/Decisions.md` — Decision Log (ADR-001 through ADR-005)
- [x] `docs/Ideas.md` — Research & Ideas Backlog
- [x] `docs/Changelog.md` — Version Log

## Phase Progress
- [x] **Phase 0**: Knowledge Base & Environment Setup
- [x] **Phase 1**: Data Ingestion Layer (`src/data/`, `YahooFinanceProvider`, Parquet Caching, `tests/test_data.py`)
- [ ] **Phase 2**: Minimal Strategy Engine (`src/strategies/`)
- [ ] **Phase 3**: Minimal Backtesting Engine (`src/backtester/`)
- [ ] **Phase 4**: Risk & Signal Filtering (`src/risk/`, `src/signals/`)
- [ ] **Phase 5**: Checkpoint & Architecture Review

## Next Immediate Steps
1. Begin Phase 2 design for baseline moving average crossover strategy in `src/strategies/`.
2. Ensure strict separation of strategy calculation from data retrieval per ADR-003.
3. Write unit tests in `tests/test_strategies.py`.


