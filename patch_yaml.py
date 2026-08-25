import yaml

with open("/home/radhe-radhe/.hermes/profiles/ind-opt-mkt/config.yaml", "r") as f:
    config = yaml.safe_load(f)

prompt = config["agent"]["system_prompt"]
prompt += "\n\nFORBIDDEN: Never state 'I don't have direct access', 'I cannot check credentials', or tell the user to log in via external web/app manually without providing the tool data.\n"
prompt += "MANDATORY: For any query regarding Upstox, auth, connection, login, market status, or readiness, the bot MUST invoke `check_market_status` (`venv/bin/python3 -m src.api.hermes_bridge status --json`) and format the resulting status card."

config["agent"]["system_prompt"] = prompt

with open("/home/radhe-radhe/.hermes/profiles/ind-opt-mkt/config.yaml", "w") as f:
    yaml.dump(config, f, default_flow_style=False)

print("Patched config.yaml")
