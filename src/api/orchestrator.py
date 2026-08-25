import os
import json
import logging
import requests
from typing import Dict, Any, List
from dotenv import load_dotenv

from src.api.intent_router import route_intent
from src.api.hermes_bridge import (
    check_system_status,
    get_premarket_shortlist,
    poll_actionable_triggers_diff,
    log_user_trade
)

try:
    from src.api.validator import validate_provenance
except ImportError:
    def validate_provenance(llm_resp: str, context: str) -> str:
        return llm_resp

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

SYSTEM_PROMPT = """You are IND OPT MKT, an autonomous NSE F&O options trading desk agent.
You have been provided with VERBATIM_TOOL_PAYLOADS_JSON which contains the ground-truth state of the desk.
Your job is ONLY to format these JSON payloads into a crisp, professional Markdown response for the trader.

RULES:
1. NEVER invent, hallucinate, or guess any numeric values (prices, strikes, PnL, lot sizes).
2. ONLY output numbers if they exist exactly in the VERBATIM_TOOL_PAYLOADS_JSON.
3. Use GitHub-flavored Markdown tables and emoji status markers (🟢, 🔴, 🟡).
4. If a tool payload says DISCONNECTED, make sure to prominently display the auth_url.
5. If there are no triggers in scan, state clearly: "No active breakouts confirmed as of [Current Time]."
"""

def orchestrate(utterance: str) -> str:
    # 1. Route Intent
    intents = route_intent(utterance)
    
    # 2. Fetch Ground Truth
    payloads = {}
    
    if "status" in intents:
        payloads["status"] = check_system_status()
    if "premarket" in intents:
        payloads["premarket"] = get_premarket_shortlist(force_scan=False)
    if "scan" in intents:
        payloads["scan"] = poll_actionable_triggers_diff(force_session_evaluation=True)
    if "log_trade" in intents:
        payloads["log_trade"] = log_user_trade(text=utterance)
        
    context_json = json.dumps(payloads, indent=2, default=str)
    
    # 3. LLM Synthesis
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return f"⚠️ OPENROUTER_API_KEY not set. Raw Ground Truth:\n```json\n{context_json}\n```"
        
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"USER QUERY: {utterance}\n\nVERBATIM_TOOL_PAYLOADS_JSON:\n{context_json}"}
    ]
    
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8501", 
                "X-Title": "IND_OPT_MKT_DESK",
            },
            json={
                "model": "deepseek/deepseek-chat",
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": 2048,
            },
            timeout=15.0
        )
        resp.raise_for_status()
        llm_response = resp.json()["choices"][0]["message"]["content"]
        
        # 4. Provenance Validation
        validated_response = validate_provenance(llm_response, context_json)
        return validated_response
        
    except requests.exceptions.Timeout:
        logger.error("OpenRouter API timeout.")
        return f"⚠️ LLM Timeout. Raw Ground Truth:\n```json\n{context_json}\n```"
    except Exception as err:
        logger.error(f"OpenRouter API error: {err}")
        return f"⚠️ LLM Error ({err}). Raw Ground Truth:\n```json\n{context_json}\n```"
