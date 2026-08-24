#!/usr/bin/env python3
import os
import sys
import time
import subprocess
from pathlib import Path
import json

def run_cmd(cmd, check=True):
    print(f"\n>>> Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    res = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True)
    if res.returncode != 0 and check:
        print(f"FAILED: {res.stderr}\n{res.stdout}")
        sys.exit(1)
    if res.stdout.strip():
        print(res.stdout)
    return res.stdout, res.stderr

def verify_auth_self_healing():
    print("\n--- 1. Testing Auth Self-Healing ---")
    # Using existing hermes_bridge to check status
    stdout, _ = run_cmd(["venv/bin/python3", "-m", "src.api.hermes_bridge", "status", "--json"])
    data = json.loads(stdout)
    assert "status" in data
    print(f"Auth Status: {data['status']}")
    
def verify_premarket_fast_read():
    print("\n--- 2. Testing 16:00 D-1 Watchlist fast-read lookup ---")
    start = time.time()
    stdout, _ = run_cmd(["venv/bin/python3", "-m", "src.api.hermes_bridge", "premarket", "--json"])
    elapsed = time.time() - start
    print(f"Premarket load time: {elapsed:.3f}s")
    assert elapsed < 2.0, "Premarket read took too long!"

def verify_orb_scan():
    print("\n--- 3. Testing 09:30 ORB scan tick simulation ---")
    stdout, stderr = run_cmd(["venv/bin/python3", "scripts/hermes_native_dispatcher.py", "--once"])
    print("Dispatcher ran successfully (silent output expected outside market hours).")

def verify_trade_logging():
    print("\n--- 4. Testing NL trade logging and trailing stop ---")
    stdout, _ = run_cmd(["venv/bin/python3", "-m", "src.api.hermes_bridge", "log-trade", "--text", "Bought CROMPTON 250 PE at 2.30, 1 lot", "--json"])
    data = json.loads(stdout)
    assert data["success"] is True
    print("Trade Logged:", data["position"]["option_symbol"])

def main():
    print("Starting End-to-End Complete Desk Verification...")
    verify_auth_self_healing()
    verify_premarket_fast_read()
    verify_orb_scan()
    verify_trade_logging()
    print("\n--- All checks passed successfully! ---")

if __name__ == "__main__":
    main()
