"""
Unit tests for Audit Logging System (src/audit_log/).

Per CodingStandards.md:
- Tests mirror src/ structure (src/audit_log/ -> tests/test_audit_log.py).
- Tests cover JSONL log file writing and record formatting.
"""

import json
from pathlib import Path
import tempfile
import pandas as pd
import pytest

from src.audit_log.logger import AuditLogger
from src.strategies.base_strategy import Signal


def test_audit_logger_write():
    """Test that AuditLogger appends JSON-Lines records correctly."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_file = Path(tmp_dir) / "signals.jsonl"
        logger = AuditLogger(log_path=log_file)

        ts = pd.Timestamp("2024-01-01 09:15:00", tz="Asia/Kolkata")
        sig = Signal(
            symbol="RELIANCE",
            timestamp=ts,
            action="BUY",
            strategy_name="SMACrossover",
            confidence=0.80,
            entry_price=2500.0,
            target_price=2550.0,
            stop_loss=2475.0,
        )

        record = logger.log_signal(sig, passed_rule_8=True, rejection_reason=None)

        assert log_file.exists()
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["symbol"] == "RELIANCE"
        assert data["strategy_name"] == "SMACrossover"
        assert data["confidence"] == 0.80
        assert data["passed_rule_8"] is True
        assert data["rejection_reason"] is None
