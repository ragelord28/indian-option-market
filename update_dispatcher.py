import re

with open("scripts/hermes_native_dispatcher.py", "r") as f:
    content = f.read()

# 1. Update delivery chain documentation
content = content.replace(
    "3. OUTBOX     — append Markdown bulletin to ~/.hermes/OUTBOX/ (visible in the\n                  workspace) — always-on durable fallback.",
    "3. Stdout     — inject Markdown bulletin into Hermes Bot Chat.\n  4. Log        — maintain fallback structured logging in data/logs/dispatcher.log."
)

# 2. Update OUTBOX to dispatcher.log
content = content.replace(
    "NATIVE_OUTBOX = Path.home() / \".hermes/OUTBOX\"",
    "FALLBACK_LOG = REPO / \"data/logs/dispatcher.log\""
)

# 3. Modify _deliver_to_outbox
def replace_outbox():
    old = """def _deliver_to_outbox(title: str, body: str, now: datetime) -> str:
    NATIVE_OUTBOX.mkdir(parents=True, exist_ok=True)
    path = NATIVE_OUTBOX / f"IND_OPT_MKT_{now.strftime('%Y%m%d')}.md"
    entry = f"\\n\\n---\\n\\n## {title}\\n\\n*{now.strftime('%Y-%m-%d %H:%M IST')}*\\n\\n{body}\\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)
    return str(path)"""
    new = """def _deliver_to_fallback_log(title: str, body: str, now: datetime) -> str:
    FALLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = f"\\n\\n---\\n\\n## {title}\\n\\n*{now.strftime('%Y-%m-%d %H:%M IST')}*\\n\\n{body}\\n"
    with open(FALLBACK_LOG, "a", encoding="utf-8") as f:
        f.write(entry)
    return str(FALLBACK_LOG)"""
    return old, new

old_outbox, new_outbox = replace_outbox()
content = content.replace(old_outbox, new_outbox)

# 4. Modify deliver() to always print the body and log
def replace_deliver():
    old = """def deliver(title: str, body: str, events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    \"\"\"Push one bulletin through the delivery chain; always log events.\"\"\"
    now = now_ist()
    _append_events_log(events or [])
    if _deliver_via_notify_send(title, body):
        return {"delivered_via": "notify-send", "title": title}
    if _deliver_via_hermes(title, body):
        return {"delivered_via": "hermes-send", "title": title}
    outbox_path = _deliver_to_outbox(title, body, now)
    return {"delivered_via": "outbox", "title": title, "outbox_file": outbox_path}"""
    
    new = """def deliver(title: str, body: str, events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    \"\"\"Push one bulletin through the delivery chain; always log events.\"\"\"
    now = now_ist()
    _append_events_log(events or [])
    _deliver_via_notify_send(title, body)
    log_path = _deliver_to_fallback_log(title, body, now)
    
    # Print directly to stdout so Hermes Cron 'bot-chat' delivery injects the markdown!
    print(f"## {title}\\n\\n{body}\\n")
    
    return {"delivered_via": "bot-chat", "title": title, "fallback_log": log_path}"""
    return old, new

old_deliver, new_deliver = replace_deliver()
content = content.replace(old_deliver, new_deliver)

# 5. Modify args.once to avoid printing json array over the markdown
old_once = """    if args.once:
        out = run_cycle()
        # Hermes cron delivers stdout verbatim (empty stdout = silent), so
        # idle cycles (weekends, silent ORB window, no diffs) print nothing.
        delivered = [a for a in out.get("actions", []) if a.get("delivered_via")]
        if delivered:
            print(json.dumps({"phase": out.get("phase"), "actions": delivered}, indent=2, default=str))
        return 0"""
new_once = """    if args.once:
        run_cycle()
        return 0"""
content = content.replace(old_once, new_once)

with open("scripts/hermes_native_dispatcher.py", "w") as f:
    f.write(content)

print("Updated hermes_native_dispatcher.py")
