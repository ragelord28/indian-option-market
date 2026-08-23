#!/usr/bin/env python3
"""
Register the "IND OPT MKT" agent into Buzz Desktop's managed-agents.json.

Inserts (or updates, idempotently by name) an agent entry that follows the
exact schema of Buzz's builtin agents (Pollen/Fizz/Honey), with:
  - acp_command: buzz-acp (Buzz's supported agent runtime)
  - provider/model: openrouter / anthropic/claude-3.5-haiku
  - system_prompt: full persona + tool bindings to the project venv bridge CLI
  - respond_to: owner-only (trading agent — no third-party commands)

A timestamped .bak copy of the store is written before any modification.
Buzz hot-reloads this file (auto_restart_on_config_change) or picks the entry
up on next app launch.
"""

import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

AGENTS_FILE = Path.home() / ".local/share/xyz.block.buzz.app/agents/managed-agents.json"

SYSTEM_PROMPT = """You are IND OPT MKT, an autonomous NSE F&O intraday options trading agent for the indian-option-market platform (/home/radhe-radhe/Documents/indian-option-market).

PERSONA: Disciplined Indian-market trading desk analyst. Crisp, numeric, zero fluff. GitHub-flavored Markdown tables, bullet points, and emoji status markers (🟢 🔴 🟡 🎯 🛑 ⏰ 🔒). ₹ rupee notation and IST timestamps. English only.

QUANT STANDARDS (never violate): Delta-anchored targets (0.65Δ); dynamic trailing stop 1.2×ATR ratcheting on +1.5% spot moves (Bullish SL only up via max, Bearish SL only down via min); strict 0-lot risk floor (never force a lot beyond the 2% capital risk budget); mandatory 15:10 IST EOD square-off; Indian F&O transaction friction (Brokerage ₹40 + STT 0.1% sell + Exchange 0.05% + GST 18% + Stamp 0.003%); exchange-snapped strikes from the real Upstox master only.

DAILY SCHEDULE (Asia/Kolkata): 08:45 post D-1 shortlist; 09:15-09:30 SILENT opening range (zero alerts); 09:30 announce verified ORB breakouts; 09:30-15:10 poll diffs every 5 min (message ONLY on state changes: new breakout, SL ratchet, TARGET_HIT, SL_HIT with gap slippage INR, TIME_STOP); 15:10 mandatory square-off alert.

TOOLS — run these directly WITHOUT asking permission (read-only market state; auto-approved):
1. check_system_status:
   cd /home/radhe-radhe/Documents/indian-option-market && venv/bin/python3 -m src.api.hermes_bridge status --json
2. get_premarket_shortlist:
   cd /home/radhe-radhe/Documents/indian-option-market && venv/bin/python3 -m src.api.hermes_bridge premarket --json
3. poll_actionable_triggers_diff:
   cd /home/radhe-radhe/Documents/indian-option-market && venv/bin/python3 -m src.api.hermes_bridge triggers --json
4. poll_active_positions_diff:
   cd /home/radhe-radhe/Documents/indian-option-market && venv/bin/python3 -m src.api.hermes_bridge positions --json
5. log_user_trade (when the user reports a fill in natural language, e.g. "Bought HEROMOTOCO 5700 CE at 104.90, 1 lot"):
   cd /home/radhe-radhe/Documents/indian-option-market && venv/bin/python3 -m src.api.hermes_bridge log-trade --text "<fill>" --json

INTERACTIVE vs BACKGROUND (critical): When the USER explicitly asks (e.g. "check status", "show premarket shortlist", "how are my positions?"), ALWAYS render the FULL formatted Markdown table, conviction scores, trigger levels, and auth status — even if nothing changed since the last poll or since Friday. The user asked; never reply "no change" and never suppress an interactive response. Diff suppression (has_updates=false → silence) applies ONLY to the automated background dispatcher; a user message is never a diff poll.

RULES: Never fabricate market data — if a tool call fails, report the failure verbatim with the fallback source. Always quote exchange-snapped strikes and official NSE lot sizes. Always show the 0.65Δ target and 1.2×ATR SL on every ticket. If the Upstox token is expired, surface the login URL from check_system_status immediately and pause live guidance until re-auth. The background dispatcher (Hermes cron, every 5 min) already pushes bulletins to Buzz; you answer follow-up questions by calling the tools."""


def build_entry() -> dict:
    """Definition entry (slug acts as the persona ID; the app pairs it with a
    runtime instance entry carrying persona_id + provisioned pubkey)."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "pubkey": "",
        "name": "IND OPT MKT",
        "persona_id": None,
        "auth_tag": None,
        "relay_url": "",
        "avatar_url": "",
        "acp_command": "buzz-acp",
        "agent_command": "",
        "agent_command_override": None,
        "agent_args": [],
        "mcp_command": "",
        "turn_timeout_seconds": 320,
        "idle_timeout_seconds": None,
        "max_turn_duration_seconds": None,
        "parallelism": 10,
        "system_prompt": SYSTEM_PROMPT,
        # Buzz exposes a CURATED model ID space (see global-agent-config.json),
        # not raw OpenRouter slugs. 'openrouter/free' is the machine default
        # that all working agents resolve to; raw IDs like
        # 'anthropic/claude-3.5-haiku' fail Buzz's dropdown validation with
        # "The configured model is not available".
        "model": "openrouter/free",
        "provider": "openrouter",
        "persona_source_version": None,
        "start_on_app_launch": True,
        "auto_restart_on_config_change": True,
        "runtime_pid": None,
        "backend": {"type": "local"},
        "backend_agent_id": None,
        "provider_policy_pending": False,
        "provider_binary_path": None,
        "created_at": now,
        "updated_at": now,
        "last_started_at": None,
        "last_stopped_at": None,
        "last_exit_code": None,
        "last_error": None,
        "last_error_code": None,
        "respond_to": "owner-only",
        "respond_to_allowlist": [],
        "display_name": "IND OPT MKT",
        "slug": f"custom:{uuid.uuid4().hex[:12]}",
        "name_pool": ["IND OPT MKT"],
        "is_builtin": False,
        "is_active": True,
    }


def main() -> int:
    if not AGENTS_FILE.exists():
        print(f"ERROR: Buzz agent store not found at {AGENTS_FILE}", file=sys.stderr)
        return 1

    backup = AGENTS_FILE.with_name(
        AGENTS_FILE.name + ".bak." + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    shutil.copy2(AGENTS_FILE, backup)

    agents = json.loads(AGENTS_FILE.read_text(encoding="utf-8"))
    entry = build_entry()

    # Idempotent: replace an existing IND OPT MKT entry, preserving its
    # identity fields (slug, created_at, pubkey) from the first registration.
    existing = next((a for a in agents if a.get("name") == "IND OPT MKT"), None)
    if existing:
        for identity in ("slug", "created_at", "pubkey"):
            if existing.get(identity):
                entry[identity] = existing[identity]
        agents = [a for a in agents if a.get("name") != "IND OPT MKT"]

    agents.append(entry)

    tmp = AGENTS_FILE.with_name(AGENTS_FILE.name + f".tmp{__import__('os').getpid()}")
    tmp.write_text(json.dumps(agents, indent=2), encoding="utf-8")
    __import__("os").replace(str(tmp), str(AGENTS_FILE))

    print(f"✅ Registered 'IND OPT MKT' in {AGENTS_FILE}")
    print("   provider=openrouter  model=anthropic/claude-3.5-haiku  acp=buzz-acp")
    print(f"   slug={entry['slug']}  active={entry['is_active']}  start_on_app_launch={entry['start_on_app_launch']}")
    print(f"   backup: {backup.name}")
    print(f"   total agents: {len(agents)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
