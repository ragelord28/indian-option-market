# Architecture.md — Indian Option Market System Architecture

## 1. Guiding Principle: Backtest–Live Parity
The Strategy Engine (`src/strategies/`) is written ONCE. Both the Backtester
and the live pipeline call this same code — never separate copies. Only the
data source differs: historical data for backtesting, live data for trading.
This guarantees that what was backtested is exactly what runs live.

## 2. Modular System Components
The platform consists of independent, decoupled Python modules:

1. **Data Ingestion & Caching Module** (`src/data/`)
   - Provides a standard internal data format that all other modules consume —
     no module outside `src/data/` ever sees a provider's raw response.
   - Implemented as pluggable provider adapters, e.g.:
     - `UpstoxProvider` — live intraday bars (minute-level) and historical data via Upstox API v2
     - `YahooFinanceProvider` — free historical OHLCV data (primarily underlying
       stocks/indices), useful for early-stage strategy backtesting
   - New data sources are added as new adapters, without changing the Strategy
     Engine, Backtester, or any other downstream module.
   - Stores and caches data locally using Parquet files or SQLite to reduce
     API load and speed up analysis.
   - Note: free sources like Yahoo Finance are not expected to provide
     reliable historical Indian options-chain data (strikes/IV). Options
     backtesting may require Upstox historical data or synthetic option
     pricing off underlying data — open item, to be resolved in Decisions.md.

2. **Strategy Engine** (`src/strategies/`)
   - Runs technical and quantitative algorithms across multiple timeframes for the ~50–150 FnO stock universe.
   - Evaluates multi-indicator combinations rather than relying on single indicators in isolation.
   - Same code path is used for both backtesting and live runs (see Section 1).

3. **Backtesting Engine** (`src/backtester/`)
   - Tests strategy rules against historical market data over varying lookback windows.
   - Factors in transaction fees, slippage, and options pricing dynamics.
   - Calls the Strategy Engine directly — does not reimplement strategy logic.

4. **Risk & Position Management Engine** (`src/risk/`)
   - Calculates recommended position sizing based on portfolio size and volatility.
   - Determines stop-loss levels, price targets, and trailing stop-loss logic.

5. **Signal & Quality Filtering Engine** (`src/signals/`)
   - Calculates a confidence score and generates a plain-language explanation for every trade setup.
   - Implements **Core.md Rule 8**: internal quality filter suppresses low-confidence or noisy signals. Only high-confidence setups reach the user.

6. **Orchestrator** (`src/orchestrator/`)
   - Owns the live monitoring loop: polls Upstox at a set interval, feeds fresh data through Data Ingestion → Strategy Engine → Risk Engine → Signal Filter, in sequence.
   - Does not contain strategy logic itself — purely coordinates the other modules.

7. **Logging & Audit Trail** (`src/audit_log/`)
   - Records every signal generated, including ones suppressed by the Rule 8 filter, with timestamp and reasoning.
   - Cross-cutting: called by the Signal Filter and Backtester, not a standalone pipeline stage.
   - Feeds future strategy review and improvement (Vision.md, "Continuous improvement").

8. **Monitoring Dashboard / UI** (`src/ui/`)
   - Displays real-time strategy state, high-quality signals, risk metrics, and explanations.

## 3. Multi-Agent Ecosystem & The Data Funnel

To protect broker API rate limits and keep operations cost-effective, the system enforces a strict "Data Funnel" architecture operated by 4 specialized agents with strict data source boundaries:

1. **Agent 1: D-1 Scanner (The Researcher)**
   - **Timing**: Runs End-of-Day (EOD).
   - **Data Sources**: Uses `yfinance` (underlying stocks/indices) and `nsepython` (free public NSE web scraping) to scan the ~150 F&O stock universe.
   - **Function**: Performs broad technical and quantitative analysis to filter 150 stocks down to a focused shortlist of 3–5 high-conviction candidate stocks for the upcoming trading session.
2. **Agent 1.5: The 9:30 AM Radar**
   - **Timing**: Runs a lightweight snapshot query at exactly 9:31 AM.
   - **Data Sources**: Uses the Upstox API on the Top 50 universe.
   - **Function**: Fetches only the first 15-minute candle to identify spontaneous Opening Range Breakouts (ORB) and high-volume gaps. Passes these 1–2 live targets to Agent 2, preventing the need to stream live data for the entire universe.

3. **Agent 2: D-Day Monitor (The Sniper)**
   - **Timing**: Runs live during market hours.
   - **Data Sources**: Uses the **Upstox API ONLY**, strictly targeted at the 3–5 shortlisted stocks produced by Agent 1 & Agent 1.5.
   - **Function**: Monitors live options chains, real-time intraday ticks, implied volatility (IV), open interest (OI) shifts, and execution triggers.

4. **Agent 3: The Validator**
   - **Timing**: Interactive / on-demand during trade evaluation.
   - **Data Sources**: Upstox API and risk management engine.
   - **Function**: Validates manual trade decisions or broker calls against system risk parameters, position sizing rules, and portfolio limits.

5. **Agent 4: The Backtester**
   - **Timing**: Offline strategy research & development.
   - **Data Sources**: `yfinance` underlying historical OHLCV data combined with **Black-Scholes Synthetic Option Pricing** (`py_vollib`).
   - **Function**: Simulates historical options trades without requiring expensive or unavailable historical options tick data by synthetically pricing options contracts off historical underlying price and IV surfaces.

### Model Context Protocol (MCP) Integration
AI agents interact with external tools and services via dedicated Model Context Protocol (MCP) servers:
- **Upstox MCP**: Exposes live market quotes, option chains, and account status to Agent 2 and Agent 3.
- **Web Scraping MCP (Crawl4AI)**: Exposes public NSE web scraping capabilities for EOD research and market news analysis to Agent 1.
- **Database MCP**: Exposes local SQLite/Parquet query tools for accessing cached market data and audit logs.

## 4. End-to-End Data Pipelines

**Backtesting (offline) path:**
`Historical Data (cached)` → `Backtester` → `Strategy Engine` → `Risk Engine` → `Signal Filter` → `Backtest Report`

**Live (online) path:**
`Upstox API (live)` → `Orchestrator (polls every N min)` → `Data Ingestion & Caching` → `Strategy Engine` (same code as backtest) → `Risk Engine` → `Signal Filter (Rule 8)` → `Logging` → `Dashboard` → `Manual Trade Execution`

## 5. Testing
- `tests/` mirrors the structure of `src/` — one test module per component.
- Every module must be testable in isolation, per Core.md.

## 6. Configuration & Data Storage
- **Secrets & Keys**: stored locally in `.env` (never committed to GitHub).
- **Strategy & Risk Parameters**: structured YAML configuration files.
- **Historical Data**: local Parquet/SQLite storage.
- **`.gitignore`**: excludes `.env`, cached data (`data/`), and logs (`logs/`) — none of these belong in version control.

## 7. Project Folder Structure
```
indian-option-market/
├── docs/              # knowledge base (Core.md, Vision.md, Architecture.md, ...)
├── src/
│   ├── data/
│   ├── strategies/
│   ├── backtester/
│   ├── risk/
│   ├── signals/
│   ├── orchestrator/
│   ├── audit_log/
│   └── ui/
├── tests/
├── configs/           # YAML strategy/risk parameters
├── data/              # local cache (gitignored)
├── logs/              # gitignored
└── .env               # gitignored, never committed
```
