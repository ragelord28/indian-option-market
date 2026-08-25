"""
Upstox API v2 OAuth 2.0 Authentication Manager.

Provides 1-click OAuth authentication for Upstox API v2:
1. Generates official authorization URL.
2. Runs a lightweight local HTTP callback server listening on port 8501.
3. Exchanges authorization code for an access_token.
4. Persists UPSTOX_ACCESS_TOKEN securely into .env.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import os
from pathlib import Path
from urllib.parse import urlencode, parse_qs, urlparse
import subprocess
import logging
import requests
from dotenv import load_dotenv, set_key

# Load environment variables from .env
ENV_PATH = Path(".env")
load_dotenv(dotenv_path=ENV_PATH)

UPSTOX_AUTH_DIALOG_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


def get_login_url(api_key: str = None, redirect_uri: str = None) -> str:
    """
    Generate the official Upstox OAuth 2.0 authorization dialog URL.

    Args:
        api_key: Upstox API Key (defaults to env UPSTOX_API_KEY).
        redirect_uri: Redirect URI (defaults to env UPSTOX_REDIRECT_URI).

    Returns:
        Formatted OAuth authorization dialog URL string.
    """
    client_id = api_key or os.getenv("UPSTOX_API_KEY", "")
    raw_redirect = redirect_uri or os.getenv("UPSTOX_REDIRECT_URI", "http://127.0.0.1:8501")
    redirect_target = raw_redirect.strip().rstrip("/")

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_target,
    }
    return f"{UPSTOX_AUTH_DIALOG_URL}?{urlencode(params)}"


def notify_auth_failure():
    """Trigger desktop notification and log auth failure."""
    log_path = Path("data/logs/dispatcher.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    msg = "Upstox Auth Token Expired (HTTP 401). Please re-authenticate."
    with open(log_path, "a", encoding="utf-8") as f:
        import datetime
        f.write(f"[{datetime.datetime.now().isoformat()}] ERROR: {msg}\n")
    try:
        subprocess.run(["notify-send", "-u", "critical", "Hermes Auth Error", msg], check=False)
    except Exception:
        pass


def fetch_and_save_token(
    auth_code: str,
    api_key: str = None,
    api_secret: str = None,
    redirect_uri: str = None,
    env_file: str | Path = ENV_PATH,
) -> str:
    """
    Exchange authorization code for access token via Upstox Token API and save to .env.

    Args:
        auth_code: Authorization code or full URL received from OAuth callback.
        api_key: Upstox API Key.
        api_secret: Upstox API Secret.
        redirect_uri: Registered OAuth Redirect URI.
        env_file: Target .env file path.

    Returns:
        Retrieved access_token string.

    Raises:
        ValueError: If API request fails or token response is invalid.
    """
    # Extract code cleanly if full URL or query string is passed
    code_str = auth_code.strip()
    if "code=" in code_str or "http" in code_str or "?" in code_str:
        try:
            parsed = urlparse(code_str if "http" in code_str else f"http://dummy/{code_str if code_str.startswith('?') else '?' + code_str}")
            query = parse_qs(parsed.query)
            if "code" in query and query["code"]:
                code_str = query["code"][0]
        except Exception:
            pass

    client_id = api_key or os.getenv("UPSTOX_API_KEY", "")
    client_secret = api_secret or os.getenv("UPSTOX_API_SECRET", "")
    raw_redirect = redirect_uri or os.getenv("UPSTOX_REDIRECT_URI", "http://127.0.0.1:8501")
    redirect_target = raw_redirect.strip().rstrip("/")

    if not client_id or not client_secret:
        raise ValueError(
            "UPSTOX_API_KEY or UPSTOX_API_SECRET is missing in environment/.env."
        )

    headers = {
        "accept": "application/json",
        "Api-Version": "2.0",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    }
    payload = {
        "code": code_str,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_target,
        "grant_type": "authorization_code",
    }

    try:
        response = requests.post(
            UPSTOX_TOKEN_URL, headers=headers, data=payload, timeout=10
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        raise ValueError(
            f"Failed to exchange authorization code for access token: {e}"
        ) from e

    access_token = data.get("access_token")
    if not access_token:
        raise ValueError(f"No access_token returned by Upstox API: {data}")

    # Persist token to .env file
    env_file_path = Path(env_file)
    if not env_file_path.exists():
        env_file_path.touch()

    set_key(env_file_path, "UPSTOX_ACCESS_TOKEN", access_token)
    os.environ["UPSTOX_ACCESS_TOKEN"] = access_token

    import json
    for token_path in [Path("data/cache/upstox_token.json"), Path("data/upstox_token.json")]:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as f:
            json.dump({"access_token": access_token}, f, indent=2)
    return access_token


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for capturing OAuth callback redirect on localhost."""

    captured_code: str = None

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if "code" in query:
            OAuthCallbackHandler.captured_code = query["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            html = """
            <html>
                <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                    <h1 style="color: #10B981;">Authentication Successful!</h1>
                    <p>Upstox Authorization Code captured. You can close this tab now.</p>
                </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>400 Bad Request: Missing authorization code</h1>")

    def log_message(self, format, *args):
        pass  # Suppress default HTTP server logs


def run_auth_cli():
    """CLI runner for 1-Click Upstox Authentication."""
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    api_key = os.getenv("UPSTOX_API_KEY", "")
    redirect_uri = os.getenv("UPSTOX_REDIRECT_URI", "http://127.0.0.1:8501")

    if not api_key or api_key == "your_api_key_here":
        print("[ERROR] Please populate UPSTOX_API_KEY and UPSTOX_API_SECRET in .env first.")
        return

    login_url = get_login_url(api_key, redirect_uri)
    print("=" * 80)
    print("                      UPSTOX API V2 OAUTH AUTHENTICATION                      ")
    print("=" * 80)
    print("\nPlease open the following URL in your web browser to log in:")
    print(f"\n  {login_url}\n")
    print("Waiting for browser redirect on port 8501...")

    # Parse port from redirect URI
    parsed_redirect = urlparse(redirect_uri)
    port = parsed_redirect.port or 8501

    server = HTTPServer(("127.0.0.1", port), OAuthCallbackHandler)
    server.handle_request()  # Wait for single callback request

    code = OAuthCallbackHandler.captured_code
    if code:
        print("\nAuthorization code received! Exchanging for access token...")
        try:
            token = fetch_and_save_token(code)
            print("Authentication Successful!")
            print(f"Token saved to .env (Token prefix: {token[:8]}...)")
        except Exception as e:
            print(f"[ERROR] Token exchange failed: {e}")
    else:
        print("[ERROR] Failed to capture authorization code from callback.")


if __name__ == "__main__":
    run_auth_cli()
