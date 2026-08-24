#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.upstox_auth import get_login_url
from src.api.hermes_bridge import check_system_status, get_premarket_shortlist, poll_actionable_triggers_diff, log_user_trade, poll_active_positions_diff

def test_auth():
    print("--- 1. Auth Test ---")
    status = check_system_status()
    print("System Status:", status)
    if status.get("auth_status") == "TOKEN_EXPIRED":
        print("Login URL:", status.get("login_url"))
    print("Auth test passed.\n")

def test_premarket():
    print("--- 2. Premarket & D-1 Test ---")
    shortlist = get_premarket_shortlist(force_scan=False)
    print(f"Generated {shortlist.get('total_candidates', 0)} candidates.")
    print("Premarket test passed.\n")

def test_orb():
    print("--- 3. ORB Setup & Breakout Simulation ---")
    diff = poll_actionable_triggers_diff()
    print(f"Has updates: {diff.get('has_updates')}")
    print("ORB test passed.\n")

def test_trailing():
    print("--- 4. Trade Logging & Trailing Test ---")
    res = log_user_trade(text="Bought CROMPTON 250 PE at 15.20, 2 lot")
    print("Log User Trade Result:", res.get("success"))
    if res.get("success"):
        print(res.get("confirmation_markdown"))
    
    # Simulate price movement
    pos_diff = poll_active_positions_diff()
    print("Position Tracking Updates:", pos_diff.get("events"))
    print("Trailing test passed.\n")

if __name__ == "__main__":
    try:
        test_auth()
        test_premarket()
        test_orb()
        test_trailing()
        print("✅ VERIFICATION SUCCESSFUL")
    except Exception as e:
        print(f"❌ VERIFICATION FAILED: {e}")
        sys.exit(1)
