import re

with open("/home/radhe-radhe/.hermes/skills/indian_option_market/run.py", "r") as f:
    content = f.read()

content = content.replace("timeout=5", "timeout=None")
content = content.replace("timeout=10", "timeout=None")

with open("/home/radhe-radhe/.hermes/skills/indian_option_market/run.py", "w") as f:
    f.write(content)

print("Patched run.py")
