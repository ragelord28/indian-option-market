with open("scripts/verify_auth_bot_flow.py", "r") as f:
    content = f.read()

import re
old_code = """# Back up token
os.system("mv data/cache/upstox_token.json data/cache/upstox_token.json.bak 2>/dev/null")
os.system("mv .env .env.bak 2>/dev/null")"""

new_code = """# Corrupt token
os.system("mv data/cache/upstox_token.json data/cache/upstox_token.json.bak 2>/dev/null")
os.system("cp .env .env.bak")
os.system("sed -i 's/UPSTOX_ACCESS_TOKEN=.*/UPSTOX_ACCESS_TOKEN=INVALID/g' .env")"""

content = content.replace(old_code, new_code)

old_restore = """finally:
    # Restore token
    os.system("mv data/cache/upstox_token.json.bak data/cache/upstox_token.json 2>/dev/null")
    os.system("mv .env.bak .env 2>/dev/null")"""

new_restore = """finally:
    # Restore token
    os.system("mv data/cache/upstox_token.json.bak data/cache/upstox_token.json 2>/dev/null")
    os.system("mv .env.bak .env 2>/dev/null")
"""

content = content.replace(old_restore, new_restore)

with open("scripts/verify_auth_bot_flow.py", "w") as f:
    f.write(content)
