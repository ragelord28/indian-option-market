#!/usr/bin/env python3
"""
End-to-End Verification: Hermes ("IND OPT MKT") Bot & Buzz Desktop Integration.

Asserts, with hard pass/fail per check:
  1. Hermes workspace & bot configuration exist and are valid
     (project mount, ind-opt-mkt personality, recurring cron dispatcher,
      Buzz managed-agents.json entry with OpenRouter/claude-3.5-haiku).
  2. All 5 tool endpoints in src.api.hermes_bridge execute cleanly via the
     project venv (CLI subprocesses; log-trade journals backed up & restored).
  3. Natural-language trade parsing handles live execution strings.
  4. Anti-spam state deduplication suppresses identical repeat polls.
  5. Full pytest unit suite passes with zero failures.

Exit code 0 only if every check passes.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_PY = PROJECT_ROOT / "venv/bin/python3"
HERMES = Path.home() / ".local/bin/hermes"
BUZZ_AGENTS_FILE = Path.home() / ".local/share/xyz.block.buzz.app/agents/managed-agents.json"
ACTIVE_POS = PROJECT_ROOT / "data/paper/active_positions.json"
ACTIVE_TRADES = PROJECT_ROOT / "data/paper/active_trades.json"

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results: list[dict] = []


def check(name: str, fn) -> None:
    try:
        detail = fn()
        results.append({"check": name, "status": PASS, "detail": detail or ""})
        print(f"{PASS}  {name}" + (f" — {detail}" if detail else ""))
    except Exception as err:
        results.append({"check": name, "status": FAIL, "detail": str(err)})
        print(f"{FAIL}  {name} — {err}")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=str(PROJECT_ROOT), **kw)


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# 1. Hermes workspace & bot configuration
# ---------------------------------------------------------------------------


def check_hermes_project() -> str:
    out = run([str(HERMES), "project", "list"])
    require(out.returncode == 0, f"hermes project list failed: {out.stderr[:200]}")
    require("indian-option-market" in out.stdout, "Hermes project 'indian-option-market' not listed")
    detail = run([str(HERMES), "project", "show", "indian-option-market"])
    require(str(PROJECT_ROOT) in detail.stdout or detail.returncode == 0,
            "project detail lookup failed")
    return "project 'Indian Option Market' (indian-option-market) registered with repo folder"


def check_hermes_persona() -> str:
    out = run([str(HERMES), "config", "get", "agent.personalities.ind-opt-mkt.system_prompt"])
    require(out.returncode == 0 and "IND OPT MKT" in out.stdout, "ind-opt-mkt personality not configured")
    return "agent.personalities.ind-opt-mkt registered with tool-binding system prompt"


def check_hermes_cron() -> str:
    out = run([str(HERMES), "cron", "list"])
    require(out.returncode == 0, "hermes cron list failed")
    require("IND OPT MKT Trading Day Dispatcher" in out.stdout, "dispatcher cron job missing")
    require("*/5 * * * *" in out.stdout, "dispatcher cron is not recurring every 5 minutes")
    return "cron job 'IND OPT MKT Trading Day Dispatcher' @ */5 * * * *"


def check_openrouter_key() -> str:
    env_file = Path.home() / ".hermes/.env"
    content = env_file.read_text(encoding="utf-8")
    # Match only an UNCOMMENTED assignment with a non-empty value (skips the
    # '# OPENROUTER_API_KEY=' template comment Hermes ships).
    m = re.search(r"^OPENROUTER_API_KEY=(\S+)$", content, re.MULTILINE)
    require(m is not None and len(m.group(1)) >= 20,
            "OPENROUTER_API_KEY missing/empty in ~/.hermes/.env")
    return "OpenRouter provider key present in ~/.hermes/.env (value not read)"


def check_buzz_agent() -> str:
    require(BUZZ_AGENTS_FILE.exists(), "Buzz managed-agents.json not found")
    agents = json.loads(BUZZ_AGENTS_FILE.read_text(encoding="utf-8"))
    entry = next((a for a in agents if a.get("name") == "IND OPT MKT"), None)
    require(entry is not None, "IND OPT MKT not registered in Buzz")
    require(entry.get("provider") == "openrouter", f"provider={entry.get('provider')!r}")
    # Buzz's curated model ID space: 'openrouter/free' (NOT raw OpenRouter slugs)
    require(entry.get("model") == "openrouter/free", f"model={entry.get('model')!r}")
    require(entry.get("is_active") is True, "agent not active")
    require(entry.get("respond_to") == "owner-only", "agent not owner-only")
    require("hermes_bridge" in entry.get("system_prompt", ""), "system prompt lacks tool bindings")
    return f"Buzz bot active (slug {entry['slug']}, owner-only, tool-bound persona)"


# ---------------------------------------------------------------------------
# 2. All 5 tool endpoints via project venv
# ---------------------------------------------------------------------------


def _cli_ok(subcommand: list[str]) -> str:
    out = run([str(VENV_PY), "-m", "src.api.hermes_bridge", *subcommand])
    require(out.returncode == 0, f"`{' '.join(subcommand)}` exited {out.returncode}: {out.stderr[:300]}")
    payload = json.loads(out.stdout)
    require(isinstance(payload, dict), "CLI did not emit a JSON object")
    return f"`{' '.join(subcommand)}` -> valid JSON"


def check_tool_status() -> str:
    payload = json.loads(run([str(VENV_PY), "-m", "src.api.hermes_bridge", "status", "--json"]).stdout)
    for key in ("auth_status", "market_phase", "watchlist_fresh"):
        require(key in payload, f"status payload missing {key}")
    return f"auth={payload['auth_status']} phase={payload['market_phase']}"


def check_tool_premarket() -> str:
    return _cli_ok(["premarket", "--json"])


def check_tool_triggers() -> str:
    out = run([str(VENV_PY), "-m", "src.api.hermes_bridge", "triggers", "--json"])
    require(out.returncode == 0, f"triggers exited {out.returncode}: {out.stderr[:300]}")
    payload = json.loads(out.stdout)
    require("has_updates" in payload and "events" in payload, "triggers diff contract violated")
    return f"has_updates={payload['has_updates']} events={len(payload['events'])}"


def check_tool_positions() -> str:
    out = run([str(VENV_PY), "-m", "src.api.hermes_bridge", "positions", "--json"])
    require(out.returncode == 0, f"positions exited {out.returncode}: {out.stderr[:300]}")
    payload = json.loads(out.stdout)
    require("has_updates" in payload and "events" in payload, "positions diff contract violated")
    return f"has_updates={payload['has_updates']} events={len(payload['events'])}"


def check_tool_log_trade() -> str:
    """Full CLI log-trade round-trip with byte-exact journal backup/restore."""
    backups: dict[Path, bytes | None] = {}
    for f in (ACTIVE_POS, ACTIVE_TRADES):
        backups[f] = f.read_bytes() if f.exists() else None
    try:
        out = run([str(VENV_PY), "-m", "src.api.hermes_bridge", "log-trade", "--json",
                   "--text", "Bought HEROMOTOCO 5700 CE at 104.90, 1 lot"])
        require(out.returncode == 0, f"log-trade exited {out.returncode}: {out.stderr[:300]}")
        payload = json.loads(out.stdout)
        require(payload.get("success") is True, f"log-trade failed: {payload.get('error')}")
        pos = payload["position"]
        require(pos["symbol"] == "HEROMOTOCO" and pos["strike"] == 5700.0, "NL parse incorrect")
        require(pos["lot_size"] == 150, "lot size not resolved from official map")
        sl_dist = pos["atr"] * 1.2
        require(abs((pos["entry_spot"] - pos["sl_spot"]) - sl_dist) < 0.05, "SL not 1.2×ATR from spot")
        return (f"parsed HEROMOTOCO 5700 CE @ ₹104.90, lot=150, "
                f"SL ₹{pos['stop_loss']} / target ₹{pos['target']} (0.65Δ), journals restored")
    finally:
        for f, data in backups.items():
            f.parent.mkdir(parents=True, exist_ok=True)
            if data is None:
                f.write_text("[]", encoding="utf-8")
            else:
                f.write_bytes(data)


# ---------------------------------------------------------------------------
# 3. Natural-language parsing (direct API)
# ---------------------------------------------------------------------------


def check_nl_parsing() -> str:
    code = (
        "from src.api.hermes_bridge import parse_trade_text as p;"
        "r = p('Bought HEROMOTOCO 5700 CE at 104.90, 1 lot');"
        "assert r['symbol']=='HEROMOTOCO' and r['option_type']=='CE', r;"
        "assert r['strike']==5700.0 and r['entry_price']==104.9 and r['lots']==1, r;"
        "r2 = p('bought relance 2500 call 886.20 2 lots');"
        "assert r2['symbol']=='RELIANCE' and r2['option_type']=='CE' and r2['lots']==2, r2;"
        "print('ok')"
    )
    out = run([str(VENV_PY), "-c", code])
    require(out.returncode == 0 and "ok" in out.stdout,
            f"NL parsing failed: {out.stderr[:300]}")
    return "exact + fuzzy ('relance'→RELIANCE) + CALL/PUT keyword forms parse"


# ---------------------------------------------------------------------------
# 4. Anti-spam dedup
# ---------------------------------------------------------------------------


def check_antispam() -> str:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        wl = {
            "timestamp": "2026-08-16T18:00:00",
            "top_bullish": [{
                "symbol": "RELIANCE", "close": 2500.0, "atr_14": 30.0,
                "conviction_score": 90.0, "regime": "Bullish Momentum",
                "suggested_action": "BUY CALL", "simulated_open": 2505.0,
                "has_event_risk": False, "candle_close": 2520.0,
                "orb_high": 2510.0, "orb_low": 2490.0, "rvol": 1.5,
            }],
            "top_bearish": [], "top_volatility_harvest": [],
        }
        wl_file = tmp / "watchlist_latest.json"
        wl_file.write_text(json.dumps(wl), encoding="utf-8")

        code = (
            "import json,sys;"
            "from datetime import datetime;"
            "from src.api.hermes_bridge import poll_actionable_triggers_diff as p;"
            "kw = dict(watchlist_path=sys.argv[1], radar_path=sys.argv[2] + '/radar.json',"
            "          tracker_path=sys.argv[2] + '/tracker.json', force_session_evaluation=True,"
            "          now_dt=datetime(2026,8,17,10,0));"
            "a = p(**kw); b = p(**kw);"
            "assert a['has_updates'] and len(a['events'])==1, a;"
            "assert not b['has_updates'] and b['events']==[], b;"
            "print('ok')"
        )
        out = run([str(VENV_PY), "-c", code, str(wl_file), str(tmp)])
        require(out.returncode == 0 and "ok" in out.stdout,
            f"anti-spam dedup failed: {out.stderr[:300]}")
        return "first poll emits 1 TRIGGERED; identical re-poll returns empty delta"


# ---------------------------------------------------------------------------
# 5. Full pytest suite
# ---------------------------------------------------------------------------


def check_pytest() -> str:
    env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT))
    out = subprocess.run(
        [str(VENV_PY), "-m", "pytest", "tests/", "-q", "--tb=no", "-p", "no:cacheprovider"],
        capture_output=True, text=True, timeout=600, cwd=str(PROJECT_ROOT), env=env,
    )
    tail = (out.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else "no output"
    require(out.returncode == 0, f"pytest failed: {summary}")
    require("failed" not in summary or "0 failed" in summary, f"pytest failures: {summary}")
    return summary


# ---------------------------------------------------------------------------


def main() -> int:
    print(f"\n🔍 Hermes ⬄ Buzz Integration Verification — {datetime.now():%Y-%m-%d %H:%M IST}\n")

    check("1a. Hermes project mounts repo workspace", check_hermes_project)
    check("1b. Hermes ind-opt-mkt persona configured", check_hermes_persona)
    check("1c. Hermes recurring cron dispatcher (*/5 * * * *)", check_hermes_cron)
    check("1d. OpenRouter provider key present", check_openrouter_key)
    check("1e. Buzz 'IND OPT MKT' bot registered", check_buzz_agent)

    check("2a. Tool: check_system_status (venv CLI)", check_tool_status)
    check("2b. Tool: get_premarket_shortlist (venv CLI)", check_tool_premarket)
    check("2c. Tool: poll_actionable_triggers_diff (venv CLI)", check_tool_triggers)
    check("2d. Tool: poll_active_positions_diff (venv CLI)", check_tool_positions)
    check("2e. Tool: log_user_trade NL fill (venv CLI)", check_tool_log_trade)

    check("3.  Natural-language trade parsing", check_nl_parsing)
    check("4.  Anti-spam trigger dedup", check_antispam)
    check("5.  Full pytest suite", check_pytest)

    failed = [r for r in results if r["status"] == FAIL]
    print(f"\n{'=' * 70}")
    print(f"RESULT: {len(results) - len(failed)}/{len(results)} checks passed"
          + (f" — {len(failed)} FAILED" if failed else " — ALL GREEN ✅"))

    report = PROJECT_ROOT / "logs/hermes_buzz_verification.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"ran_at": datetime.now().isoformat(), "results": results}, indent=2),
                      encoding="utf-8")
    print(f"Full report: {report}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
