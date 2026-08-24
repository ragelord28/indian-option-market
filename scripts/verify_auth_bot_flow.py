import subprocess
import os

PROJECT_DIR = '/home/radhe-radhe/Documents/indian-option-market'

def run_status():
    res = subprocess.run(
        ["venv/bin/python3", "-m", "src.api.hermes_bridge", "status"],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True
    )
    return res.stdout.strip()

print("--- 1. Connected State Test ---")
out = run_status()
print(f"Output: {out}")
assert "🟢 CONNECTED" in out, "Failed Connected state check"

print("\n--- 2. Disconnected / Self-Healing State Test ---")
# Corrupt token
os.system("mv data/cache/upstox_token.json data/cache/upstox_token.json.bak 2>/dev/null")
os.system("cp .env .env.bak")
os.system("sed -i 's/UPSTOX_ACCESS_TOKEN=.*/UPSTOX_ACCESS_TOKEN=INVALID/g' .env")
try:
    out2 = run_status()
    print(f"Output: {out2}")
    assert "🔴 DISCONNECTED" in out2, "Failed Disconnected state check"
    assert "8501" in out2, "Listener port not found in output"
    
    # Check if process is listening on 8501
    import time
    import socket
    res = -1
    for i in range(15):
        time.sleep(1)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        res = sock.connect_ex(('127.0.0.1', 8501))
        sock.close()
        if res == 0:
            break
    assert res == 0, "OAuth listener did not start on port 8501"
    print("Listener successfully spawned on port 8501!")
    
    # Kill the listener
    os.system("fuser -k 8501/tcp")
finally:
    # Restore token
    os.system("mv data/cache/upstox_token.json.bak data/cache/upstox_token.json 2>/dev/null")
    os.system("mv .env.bak .env 2>/dev/null")


print("\n✅ Verification Successful!")
