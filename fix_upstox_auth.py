import re

with open("src/data/upstox_auth.py", "r") as f:
    content = f.read()

# Fix redirect URI and port
content = content.replace('os.getenv("UPSTOX_REDIRECT_URI", "http://localhost:8501")', 'os.getenv("UPSTOX_REDIRECT_URI", "http://127.0.0.1:8501")')
content = content.replace('http://127.0.0.1:5000/callback', 'http://127.0.0.1:8501')
content = content.replace('port 5000', 'port 8501')
content = content.replace('or 5000', 'or 8501')
content = content.replace('5000', '8501')

# Add headers
headers_old = """    headers = {
        "accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }"""
headers_new = """    headers = {
        "accept": "application/json",
        "Api-Version": "2.0",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    }"""
content = content.replace(headers_old, headers_new)

# Fix cache path
cache_old = 'for token_path in [Path("data/tokens/upstox_token.json"), Path("data/upstox_token.json")]:'
cache_new = 'for token_path in [Path("data/cache/upstox_token.json"), Path("data/upstox_token.json")]:'
content = content.replace(cache_old, cache_new)

with open("src/data/upstox_auth.py", "w") as f:
    f.write(content)

print("Fixed upstox_auth.py")
