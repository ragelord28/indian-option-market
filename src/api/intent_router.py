import re
from typing import Set, Dict, List

INTENT_LEXICON: Dict[str, List[str]] = {
    "status": ["status", "health", "auth", "login", "upstox", "connected", "ready", "system", "working"],
    "premarket": ["premarket", "watchlist", "shortlist", "d-1", "veto", "vetoed", "candidates", "bullish", "bearish", "list"],
    "scan": ["scan", "triggers", "breakout", "breakouts", "orb", "active", "alert", "alerts", "new", "update", "happening", "market", "now"],
    "log_trade": ["log", "bought", "sold", "buy", "sell", "filled", "order", "trade", "entry", "exit", "lots", "lot", "ce", "pe", "call", "put"]
}

def _cosine_similarity_proxy(utterance: str, lexicon: List[str]) -> float:
    """
    Lightweight deterministic token overlap (acting as a cosine similarity proxy)
    without external dependencies like sentence-transformers.
    """
    words = set(re.findall(r'\w+', utterance.lower()))
    if not words:
        return 0.0
    
    matches = sum(1.0 for w in words if w in lexicon or any(l in w for l in lexicon if len(l) > 4))
    
    if matches == 0:
        return 0.0
        
    # Scale by the square root of utterance length to prevent long queries from diluting score too aggressively
    return matches / max(1.0, (len(words) ** 0.5))

def route_intent(utterance: str, threshold: float = 0.35) -> Set[str]:
    """
    Map a natural language utterance to one or more strict bridge tools.
    """
    utterance_lower = utterance.lower()
    intents: Set[str] = set()
    
    # 1. Hard regex overrides for definitive actions (e.g., logging a trade)
    if re.search(r'\b(bought|sold|buy\s+1\s+lot|sell\s+1\s+lot|log\s+trade)\b', utterance_lower):
        intents.add("log_trade")
        
    # 2. Similarity scoring
    scores = {}
    for intent, lex in INTENT_LEXICON.items():
        scores[intent] = _cosine_similarity_proxy(utterance_lower, lex)
        
    for intent, score in scores.items():
        if score >= threshold:
            intents.add(intent)
            
    # Default fallback: if nothing is matched, assume they want a scan/status update
    if not intents:
        intents.add("scan")
        
    return intents
