"""
Pipeline Orchestrator Module for coordinating Data -> Strategy -> Risk -> Logging -> Backtest execution.
"""

from src.orchestrator.runner import PipelineRunner

__all__ = ["PipelineRunner"]
