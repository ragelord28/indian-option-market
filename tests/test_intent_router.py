import pytest
from src.api.intent_router import route_intent

def test_route_status():
    assert "status" in route_intent("what is the system health?")
    assert "status" in route_intent("are we connected to upstox?")

def test_route_premarket():
    assert "premarket" in route_intent("show me the watchlist for today")
    assert "premarket" in route_intent("any vetoed candidates?")
    
def test_route_scan():
    assert "scan" in route_intent("any new breakouts now?")
    assert "scan" in route_intent("what's happening in the market?")

def test_route_log_trade():
    assert "log_trade" in route_intent("I bought 1 lot of HEROMOTOCO 5700 CE")
    assert "log_trade" in route_intent("log trade sold 1500 PE")

def test_fallback_scan():
    assert "scan" in route_intent("anything?")
    assert "scan" in route_intent("what is up?")

def test_multi_intent():
    intents = route_intent("check status and any new breakouts")
    assert "status" in intents
    assert "scan" in intents
