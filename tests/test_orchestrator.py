import pytest
from unittest.mock import patch, MagicMock
from src.api.orchestrator import orchestrate

@patch("src.api.orchestrator.requests.post")
@patch("src.api.orchestrator.os.getenv")
def test_orchestrate_status(mock_getenv, mock_post):
    mock_getenv.return_value = "fake_key"
    
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "System is connected."}}]
    }
    mock_post.return_value = mock_resp
    
    res = orchestrate("what is the system status?")
    
    assert "System is connected." in res
    
    # Check that requests.post was called
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args[1]["json"]["model"] == "deepseek/deepseek-chat"
    
    # Check that the intent router included the status payload
    messages = call_args[1]["json"]["messages"]
    assert "VERBATIM_TOOL_PAYLOADS_JSON" in messages[1]["content"]
    assert "status" in messages[1]["content"]

@patch("src.api.orchestrator.os.getenv")
def test_orchestrate_no_api_key(mock_getenv):
    mock_getenv.return_value = None
    res = orchestrate("what is the system status?")
    assert "OPENROUTER_API_KEY not set" in res
    assert "Raw Ground Truth" in res
