#!/usr/bin/env python3
"""
Wrapper for the Upstox OAuth 2.0 Authentication Manager.
Delegates to src.data.upstox_auth.
"""

import sys
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.upstox_auth import run_auth_cli

if __name__ == "__main__":
    run_auth_cli()
