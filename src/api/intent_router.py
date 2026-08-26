class IntentRouter:
    def __init__(self, threshold: float = 0.35):
        self.threshold = threshold

    def route(self, utterance: str) -> set:
        u = utterance.lower()
        hits = set()
        
        # Premarket watchlist keywords
        if any(w in u for w in ["watchlist", "shortlist", "shortlisted", "candidate", "candidates", "premarket", "stocks", "watching"]):
            hits.add("premarket")
            
        # Live Breakout / Scan keywords
        if any(w in u for w in ["breakout", "breakouts", "broke", "trigger", "triggers", "scan", "update", "new", "orb", "live"]):
            hits.add("scan")
            
        # Status / Auth keywords
        if any(w in u for w in ["status", "auth", "broker", "health", "connected", "upstox", "login", "logged"]):
            hits.add("status")
            
        # Trade logging
        if any(w in u for w in ["bought", "sold", "log trade", "record", "fill"]):
            hits.add("log_trade")
            
        return hits
