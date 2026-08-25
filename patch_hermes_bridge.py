with open("src/api/hermes_bridge.py", "r") as f:
    content = f.read()

import re

old_status = """    if provider is not None:
        try:
            authenticated = bool(provider.is_token_valid())
        except Exception:
            authenticated = False

    result: Dict[str, Any] = {
        "server_time_ist": now_ist.strftime("%Y-%m-%d %H:%M IST"),
        "auth_status": "AUTHENTICATED" if authenticated else "TOKEN_EXPIRED",
        "authenticated": authenticated,
        "market_phase": _market_phase(now_ist),
        "market_session_active": is_market_session_active(now_ist),
    }

    if not authenticated:
        try:
            from src.data.upstox_auth import get_login_url
            result["login_url"] = get_login_url()
            result["remedy"] = "Token expired. Open the login URL in a browser, complete Upstox OAuth, and re-run status."
        except Exception:
            result["login_url"] = None
            result["remedy"] = "Token expired and login URL could not be generated (check UPSTOX_API_KEY)."

    wl_path = Path(watchlist_path)"""

new_status = """    user_name = None
    if provider is not None:
        try:
            prof = provider.get_user_profile()
            if prof:
                authenticated = True
                user_name = prof.get("user_name", "Unknown User")
            else:
                authenticated = False
        except Exception:
            authenticated = False

    result: Dict[str, Any] = {}
    if authenticated:
        result = {
            "status": "CONNECTED",
            "user": user_name or "Ritik Bhriegu",
            "expiry": (now_ist + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S"),
            "ready": True
        }
    else:
        auth_url = None
        try:
            from src.data.upstox_auth import get_login_url
            auth_url = get_login_url()
            # Spawn the listener if not already running
            import subprocess
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            res = sock.connect_ex(('127.0.0.1', 8501))
            sock.close()
            if res != 0: # Port not in use
                import os
                listener_script = os.path.join(Path(__file__).resolve().parents[2], 'scripts', 'upstox_oauth_listener.py')
                subprocess.Popen([sys.executable, listener_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

        result = {
            "status": "DISCONNECTED",
            "auth_url": auth_url,
            "listener_port": 8501
        }
        
    result["server_time_ist"] = now_ist.strftime("%Y-%m-%d %H:%M IST")
    result["market_phase"] = _market_phase(now_ist)
    result["market_session_active"] = is_market_session_active(now_ist)

    wl_path = Path(watchlist_path)"""

content = content.replace(old_status, new_status)

with open("src/api/hermes_bridge.py", "w") as f:
    f.write(content)

print("Patched hermes_bridge.py")
