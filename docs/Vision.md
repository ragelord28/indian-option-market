# Vision.md — Indian Option Market

## Purpose
An AI-assisted quantitative research and decision-support platform for the
Indian options market. The platform supports the trader's decision-making;
it never trades on its own (see Core.md).

## Target market
- Indian F&O (Futures & Options) segment
- Initial universe: ~50–150 selected FnO stocks

## Core capabilities (long-term)
1. **Strategy research** — design and iterate on trading strategies
2. **Backtesting** — test strategies against historical market data using Python
3. **Live market data** — fetch and analyze live data via the Upstox API
4. **Multi-strategy monitoring** — track several strategies running at once
5. **Signal generation** — entry and exit signals derived from:
   - Historical data across multiple time periods/timeframes (backtesting
     different lookback windows and horizons)
   - Live intraday data tracked at minute-level granularity
   - Multiple technical indicators analyzed together, not in isolation
   Only signals meeting a high confidence/quality bar are surfaced
   (see Core.md, rule 8).
6. **Risk suggestions** — stop-loss, targets, trailing stop-loss, position sizing
7. **Confidence scoring** — every signal comes with a confidence score and
   an explanation of why
8. **Continuous improvement** — the platform evolves through ongoing research
   and experimentation
9. **Documentation & history** — every module and decision is recorded and
   traceable over time

## Explicitly out of scope
- Automatic/unattended order placement
- Any execution path that bypasses manual trader approval

## Tooling the owner uses to build this
- Gemini, Antigravity, Claude — as AI collaborators
- GitHub — version control and knowledge base home
- Python — backtesting and data analysis
- Upstox API — live market data

## Status
This is a long-term project built incrementally, one small, confirmed step
at a time. See Roadmap.md for what's being built now vs. later.
