with open("src/api/hermes_bridge.py", "r") as f:
    content = f.read()

import re
old_main = """    if args.json or args.command == "daemon":
        print(json.dumps(out, indent=2))
    else:
        print(json.dumps(out, indent=2))
"""

new_main = """    if args.json or args.command == "daemon":
        print(json.dumps(out, indent=2))
    elif args.command == "status":
        if out.get("status") == "CONNECTED":
            print(f"🟢 CONNECTED | User: {out.get('user', 'Unknown')} | Expiry: {out.get('expiry', '')} | Desk Ready: {out.get('ready', False)}")
        else:
            print(f"🔴 DISCONNECTED | Login URL: {out.get('auth_url', '')} | Listener Port: {out.get('listener_port', 8501)}")
    else:
        print(json.dumps(out, indent=2))
"""

# Let's see if the old_main exists.
# We'll just replace the last part of the file.

if "if args.json" in content:
    content = re.sub(r'    if args\.json.*?(?=\n\s*return 0)', new_main, content, flags=re.DOTALL)
else:
    # Just replace the last print(json.dumps(out, indent=2))
    content = re.sub(r'    print\(json\.dumps\(out, indent=2\)\)\n\n    return 0', new_main + '\n    return 0', content)

with open("src/api/hermes_bridge.py", "w") as f:
    f.write(content)

print("Formatted output added.")
