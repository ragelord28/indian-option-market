# Core.md — Indian Option Market: Project Constitution

## What this project is
An AI-assisted quantitative research and decision-support platform for the
Indian options market (initially ~50–150 FnO stocks). It helps research,
backtest, and monitor trading strategies, and generates signals with
explained confidence scores.

## What this project is NOT
- It is NOT a fully automated trading bot.
- It will NEVER place orders automatically.
- All trade execution is manual, performed by the project owner.

## Non-negotiable rules
1. AI is a research and decision-support assistant only — never an executor.
2. Every module must be independently testable.
3. No duplicate code — reuse existing modules instead of rewriting logic.
4. Every important decision is documented (see Decisions.md).
5. Architectural trade-offs are explained BEFORE implementation, not after.
6. Any agent may recommend a better approach than a prior decision — past
   decisions are not sacred, but changing them requires updating Decisions.md.
7. The project must remain modular and able to grow indefinitely without
   becoming unmaintainable.

## Who is building this
The project owner is a non-coder. All AI collaborators (Gemini, Antigravity,
Claude, and any specialist agents) must explain their work in plain language,
not assume prior programming knowledge, and avoid unexplained jargon.

## How to use this document
Every AI agent working on this project should read this file first, before
reading any other document, and before writing any code or documentation.
