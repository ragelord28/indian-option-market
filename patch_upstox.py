with open("src/data/upstox_provider.py", "r") as f:
    content = f.read()

import re

# Add get_user_profile
new_func = """
    def get_user_profile(self) -> dict | None:
        if not self.access_token:
            return None
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        url = f"{UPSTOX_BASE_URL}/user/profile"
        try:
            res = requests.get(url, headers=headers, timeout=3)
            if res.status_code == 200:
                return res.json().get('data', {})
            return None
        except Exception:
            return None
"""

# Find where to insert it (after is_token_valid)
content = content.replace('    def _get_instrument_key(self, symbol: str) -> str:', new_func.lstrip('\n') + '\n    def _get_instrument_key(self, symbol: str) -> str:')

with open("src/data/upstox_provider.py", "w") as f:
    f.write(content)

print("Patched upstox_provider.py")
