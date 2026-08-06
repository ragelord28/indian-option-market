# CodingStandards.md — Code & Quality Conventions

## 1. Principles for AI Collaboration
1. **Plain-Language Documentation**: Every file, class, and function must include plain-English docstrings explaining *what* it does and *why*.
2. **Type Annotations**: All function parameters and return types must use explicit Python type hints (e.g., `def calculate_sma(df: pd.DataFrame, period: int) -> pd.Series:`).
3. **DRY (Don't Repeat Yourself)**: Shared utilities (e.g., indicator formulas, date parsing) must reside in dedicated helper functions, never duplicated across modules.
4. **Mandatory Testing**: Every code file in `src/` must have a corresponding unit test file in `tests/`.
5. **Test Location Convention**: Test files mirror `src/` structure exactly (e.g., `src/data/yahoo_provider.py` → `tests/test_data.py`), matching the test files already named per phase in
   Roadmap.md.

## 2. Naming Conventions
- **Files & Modules**: `snake_case` (e.g., `yahoo_provider.py`)
- **Classes**: `PascalCase` (e.g., `YahooFinanceProvider`)
- **Functions & Variables**: `snake_case` (e.g., `fetch_historical_data`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_CACHE_DIR`)

## 3. Error Handling & Security
- **Explicit Exceptions**: Handle potential errors (e.g., network failure, missing data) gracefully with clear error messages.
- **No Hardcoded Credentials**: API keys, passwords, and tokens must never appear in source code or documentation. Use `.env` files exclusively.
- **Logging**: Use Python's `logging` module instead of `print()` statements for tracking operational messages.
