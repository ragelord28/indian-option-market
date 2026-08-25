import os
import sys
import json
from datetime import datetime, time
from pathlib import Path

def is_market_hours() -> bool:
    now = datetime.now()
    # Monday = 0, Friday = 4, Saturday = 5, Sunday = 6
    if now.weekday() >= 5:
        return False
    current_time = now.time()
    return time(9, 30) <= current_time <= time(15, 30)

def get_premarket_markdown() -> str:
    cache_file = Path("data/cache/premarket_shortlist.json")
    if not cache_file.exists():
        return "### 📋 D-1 Shortlist\n\nNo shortlist cache found. Run nightly scanner post 4:00 PM."
    
    try:
        data = json.loads(cache_file.read_text())
    except Exception as e:
        return f"Error reading shortlist cache: {e}"
    
    candidates = data.get("candidates", [])
    if not candidates:
        return "### 📋 D-1 Shortlist\n\nNo candidates met conviction thresholds."
    
    bullish = [c for c in candidates if "BULLISH" in str(c.get("bias", "")).upper()]
    bearish = [c for c in candidates if "BEARISH" in str(c.get("bias", "")).upper()]
    
    md = f"## 📋 D-1 Pre-Market Shortlist ({data.get('date', 'Latest Session')})\n\n"
    
    if bullish:
        md += "### 🟢 Top Bullish Candidates\n\n"
        md += "| Symbol | Conviction | ATR | HV20 | Bias |\n|---|---|---|---|---|\n"
        for c in bullish:
            md += f"| **{c.get('symbol')}** | {c.get('conviction_score', '-')} | ₹{c.get('atr', 0):.2f} | {c.get('hv20', 0):.1f}% | {c.get('bias', '-')} |\n"
        md += "\n"
        
    if bearish:
        md += "### 🔴 Top Bearish Candidates\n\n"
        md += "| Symbol | Conviction | ATR | HV20 | Bias |\n|---|---|---|---|---|\n"
        for c in bearish:
            md += f"| **{c.get('symbol')}** | {c.get('conviction_score', '-')} | ₹{c.get('atr', 0):.2f} | {c.get('hv20', 0):.1f}% | {c.get('bias', '-')} |\n"
        md += "\n"
        
    return md

def get_live_radar_markdown() -> str:
    # 1. First check live radar state cache or run fresh evaluation
    radar_file = Path("data/cache/live_radar_state.json")
    radar_data = []
    
    if radar_file.exists():
        try:
            radar_data = json.loads(radar_file.read_text())
        except Exception:
            pass
            
    if not radar_data:
        try:
            from src.radar.morning_radar import run_morning_radar
            radar_res = run_morning_radar(force_session_evaluation=True)
            
            # Safely extract the DataFrame/Data, which is typically the first element if a tuple is returned
            df_radar = radar_res[0] if isinstance(radar_res, tuple) else radar_res
            
            if isinstance(df_radar, dict) and "radar_items" in df_radar:
                radar_data = df_radar["radar_items"]
            elif hasattr(df_radar, "to_dict"):
                radar_data = df_radar.to_dict(orient="records")
            elif isinstance(df_radar, list):
                radar_data = df_radar
            else:
                radar_data = []
        except Exception as e:
            return f"Error executing Agent 1.5 Radar: {e}"

    triggered = []
    vetoed = []
    watching = []

    for row in radar_data:
        status = str(row.get("status", row.get("Agent 1.5 Status", "")))
        sym = str(row.get("symbol", row.get("Symbol", "")))
        spot = row.get("close", row.get("Live Spot (₹)", row.get("Live Spot", "-")))
        trigger_zone = row.get("trigger_zone", row.get("Trigger Zone", "-"))
        target = row.get("target", row.get("Target Spot", row.get("Target", "-")))
        strategy = row.get("suggested_action", row.get("Optimal Strategy", "-"))
        reason = row.get("orb_reason", row.get("ORB State / Reason", row.get("Reason", "-")))

        item = {
            "symbol": sym,
            "status": status,
            "spot": spot,
            "trigger_zone": trigger_zone,
            "target": target,
            "strategy": strategy,
            "reason": reason
        }

        if "TRIGGERED" in status:
            triggered.append(item)
        elif "VETOED" in status:
            vetoed.append(item)
        else:
            watching.append(item)

    now_str = datetime.now().strftime("%I:%M %p IST")
    md = f"## ⚡ Agent 1.5 Live Morning Radar ({now_str})\n\n"

    # Cumulative Breakouts section
    if triggered:
        md += "### 🔥 Confirmed Breakouts Today (Cumulative)\n\n"
        md += "| Symbol | Trigger State | Live Spot | Trigger Zone | Target Spot | Strategy |\n"
        md += "|---|---|---|---|---|---|\n"
        for t in triggered:
            md += f"| **{t['symbol']}** | 🟢 {t['status']} | ₹{t['spot']} | ₹{t['trigger_zone']} | ₹{t['target']} | {t['strategy']} |\n"
        md += "\n"
    else:
        md += "### 📊 Live Breakout Triggers\n\nNo breakouts confirmed today as of " + now_str + ".\n\n"

    # Actively Watching / Inside Range
    if watching:
        md += "### 👀 In Range / Watching\n\n"
        md += "| Symbol | Live Spot | Trigger Zone | Target Spot | Strategy |\n"
        md += "|---|---|---|---|---|\n"
        for w in watching:
            md += f"| {w['symbol']} | ₹{w['spot']} | {w['trigger_zone']} | ₹{w['target']} | {w['strategy']} |\n"
        md += "\n"

    # Vetoed setups
    if vetoed:
        md += "### 🚫 Filtered / Vetoed Candidates\n\n"
        md += "| Symbol | Status | Reason |\n"
        md += "|---|---|---|\n"
        for v in vetoed:
            md += f"| {v['symbol']} | 🔴 {v['status']} | {v['reason']} |\n"
        md += "\n"

    return md

def orchestrate(query: str) -> str:
    u = query.lower()
    
    # Status Query
    if any(w in u for w in ["status", "auth", "broker", "health", "connected", "upstox"]):
        from src.api.hermes_bridge import cmd_status
        res = cmd_status()
        return res.get("result", {}).get("markdown", "Status check completed.")
        
    # Trade Logging Query
    if any(w in u for w in ["bought", "sold", "log trade", "record fill"]):
        return "To log a fill, use the format: `Bought <SYMBOL> <STRIKE> <CE/PE> at <PRICE>, <LOTS> lots`."

    # Market Hours State Routing:
    if is_market_hours():
        # During 09:30 - 15:30 IST: Return Live Agent 1.5 Radar (with cumulative breakouts)
        return get_live_radar_markdown()
    else:
        # 16:00 - 09:30 IST / Weekends / Holidays: Return D-1 Shortlist
        return get_premarket_markdown()
