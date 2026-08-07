"""
Pipeline Orchestrator Runner.

Coordinates end-to-end processing across:
Data Ingestion (YahooFinanceProvider) -> Strategy Engine -> Risk Management -> Audit Logging -> Backtest Engine.
"""

from typing import Dict, Any, Optional
from src.data.yahoo_provider import YahooFinanceProvider
from src.strategies.sma_cross import SMACrossoverStrategy
from src.strategies.base_strategy import BaseStrategy
from src.risk.risk_manager import RiskManager
from src.audit_log.logger import AuditLogger
from src.backtester.engine import BacktestEngine


class PipelineRunner:
    """
    Orchestrates execution across all pipeline modules.
    """

    def __init__(
        self,
        provider: Optional[YahooFinanceProvider] = None,
        strategy: Optional[BaseStrategy] = None,
        risk_manager: Optional[RiskManager] = None,
        audit_logger: Optional[AuditLogger] = None,
        backtest_engine: Optional[BacktestEngine] = None,
    ):
        """
        Initialize the PipelineRunner with modular components.
        """
        self.provider = provider or YahooFinanceProvider()
        self.strategy = strategy or SMACrossoverStrategy()
        self.risk_manager = risk_manager or RiskManager()
        self.audit_logger = audit_logger or AuditLogger()
        self.backtest_engine = backtest_engine or BacktestEngine(
            strategy=self.strategy, risk_manager=self.risk_manager
        )

    def run_pipeline(
        self, symbol: str, start_date: str, end_date: str
    ) -> Dict[str, Any]:
        """
        Execute end-to-end pipeline for a given symbol and date range.

        Args:
            symbol: Standardized internal symbol string (e.g. 'RELIANCE').
            start_date: Start date YYYY-MM-DD.
            end_date: End date YYYY-MM-DD.

        Returns:
            Dictionary containing backtest metrics and list of trades.
        """
        # 1. Fetch data via Data Ingestion Layer
        df = self.provider.fetch_historical_data(
            symbol=symbol, start_date=start_date, end_date=end_date
        )

        # 2. Generate signals via Strategy Engine
        signals = self.strategy.generate_signals(df)

        # 3. Log signals via Audit Logger
        for signal in signals:
            self.audit_logger.log_signal(
                signal=signal,
                passed_rule_8=True,
                rejection_reason=None,
            )

        # 4. Run Backtesting Engine
        result = self.backtest_engine.run(df)
        return result
