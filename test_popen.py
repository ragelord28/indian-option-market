import sys, os, subprocess
from pathlib import Path
listener_script = os.path.join(Path("src/api/hermes_bridge.py").resolve().parents[2], 'scripts', 'upstox_oauth_listener.py')
p = subprocess.Popen([sys.executable, listener_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
import time
time.sleep(2)
p.poll()
print("Return code:", p.returncode)
if p.returncode is not None:
    print("Stderr:", p.stderr.read().decode())
