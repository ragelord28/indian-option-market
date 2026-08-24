import re

with open("scripts/hermes_native_dispatcher.py", "r") as f:
    content = f.read()

# Fix times to match prompt
content = content.replace('PREMARKET_PUSH_MIN = 8 * 60 + 45  # 08:45', 'PREMARKET_PUSH_MIN = 9 * 60  # 09:00')
content = content.replace('08:45 IST        D-1 pre-market shortlist table', '09:00 IST        D-1 pre-market shortlist table')
content = content.replace('08:45–09:14', '09:00–09:14')

# Add 16:00 D-1 Evening screening
EOD_SCAN_MIN = "16 * 60  # 16:00"
content = content.replace('EOD_MIN = 15 * 60 + 10          # 15:10', f'EOD_MIN = 15 * 60 + 10          # 15:10\nEOD_SCAN_MIN = 16 * 60          # 16:00')

scan_block_old = """    state["cycles"] = int(state.get("cycles", 0)) + 1
    state["last_cycle_ist"] = now.strftime("%Y-%m-%d %H:%M:%S")"""
scan_block_new = """    if EOD_SCAN_MIN <= mins and not state.get("evening_scan_sent"):
        try:
            from src.api.hermes_bridge import get_premarket_shortlist
            # force scan generates the next day's list
            get_premarket_shortlist(force_scan=True)
            res = deliver("✅ 16:00 D-1 Evening Screening", "Next day watchlist generated successfully.")
            results.append(res)
            state["evening_scan_sent"] = True
        except Exception as err:
            results.append({"delivered_via": "error", "title": "16:00 Scan", "error": str(err)})

    state["cycles"] = int(state.get("cycles", 0)) + 1
    state["last_cycle_ist"] = now.strftime("%Y-%m-%d %H:%M:%S")"""
content = content.replace(scan_block_old, scan_block_new)

with open("scripts/hermes_native_dispatcher.py", "w") as f:
    f.write(content)

print("Fixed dispatcher times")
