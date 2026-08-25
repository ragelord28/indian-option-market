import pytest
from datetime import datetime
from src.api.hermes_bridge import check_system_status, get_premarket_shortlist, poll_actionable_triggers_diff

def test_status_schema():
    out = check_system_status()
    assert out["tool"] == "status"
    assert "as_of" in out
    assert "scope" in out
    assert "result" in out
    assert "note" in out
    
    res = out["result"]
    assert "status" in res
    assert "active_positions" in res
    if res["status"] == "DISCONNECTED":
        assert "auth_url" in res
        assert "listener_port" in res
    else:
        assert "user" in res
        assert "expiry" in res

def test_premarket_schema():
    out = get_premarket_shortlist(force_scan=False)
    assert out["tool"] == "premarket"
    assert "as_of" in out
    assert "scope" in out
    assert "result" in out
    assert "note" in out
    
    res = out["result"]
    assert "total_candidates" in res
    assert "bullish" in res
    assert "bearish" in res
    assert "volatility_harvest" in res
    assert "vetoed_candidates" in res
    assert "markdown" in res
    
    if res["bullish"]:
        row = res["bullish"][0]
        for key in ["symbol", "conviction", "atr", "hv20", "sector", "status", "veto_reason"]:
            assert key in row

def test_scan_schema(tmp_path):
    out = poll_actionable_triggers_diff(tracker_path=tmp_path / "tracker.json", watchlist_path=tmp_path / "wl.json", radar_path=tmp_path / "radar.json", force_session_evaluation=False)
    assert out["tool"] == "scan"
    assert "as_of" in out
    assert "scope" in out
    assert "result" in out
    assert "note" in out
    
    res = out["result"]
    assert "new_breakouts" in res
    assert "watchlist_size" in res
