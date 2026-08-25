import pytest
from src.api.validator import validate_provenance

def test_validate_provenance_clean():
    context = '{"symbol": "RELIANCE", "price": 2500.50, "volume": "45,000"}'
    llm_output = "The price of RELIANCE is 2500.50 and the volume is 45,000."
    validated = validate_provenance(llm_output, context)
    assert validated == llm_output

def test_validate_provenance_hallucinated():
    context = '{"symbol": "RELIANCE", "price": 2500.50}'
    llm_output = "The price of RELIANCE is 2500.50.\nThe volume is 45,000."
    validated = validate_provenance(llm_output, context)
    assert "The price of RELIANCE is 2500.50." in validated
    assert "Redacted hallucinated line containing ungrounded numbers: 45,000" in validated

def test_validate_provenance_safe_indices():
    context = '{"results": ["a", "b"]}'
    llm_output = "1. Item a\n2. Item b"
    validated = validate_provenance(llm_output, context)
    assert "1. Item a" in validated
    assert "2. Item b" in validated
