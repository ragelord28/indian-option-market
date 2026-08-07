"""
Audit Logger for recording signals and quality filter outcomes in JSON-Lines format.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any
from src.strategies.base_strategy import Signal

DEFAULT_LOG_PATH = Path("logs/signals.jsonl")


class AuditLogger:
    """
    Records all generated signals and Rule 8 evaluation outcomes to a local JSONL file.
    """

    def __init__(self, log_path: Path | str = DEFAULT_LOG_PATH):
        """
        Initialize the AuditLogger.

        Args:
            log_path: File path to append signal JSON records.
        """
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_signal(
        self,
        signal: Signal,
        passed_rule_8: bool,
        rejection_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Appends a JSON-lines record for a trade signal.

        Args:
            signal: The Signal dataclass instance.
            passed_rule_8: Boolean flag indicating if signal passed Rule 8 filter.
            rejection_reason: Optional string reason if suppressed.

        Returns:
            The dictionary record logged to disk.
        """
        record = {
            "timestamp": str(signal.timestamp),
            "symbol": signal.symbol,
            "strategy_name": signal.strategy_name,
            "action": signal.action,
            "confidence": float(signal.confidence),
            "entry_price": float(signal.entry_price) if signal.entry_price else None,
            "stop_loss": float(signal.stop_loss) if signal.stop_loss else None,
            "target_price": float(signal.target_price) if signal.target_price else None,
            "passed_rule_8": passed_rule_8,
            "rejection_reason": rejection_reason,
            "metadata": signal.metadata if hasattr(signal, "metadata") else {},
        }

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        return record
