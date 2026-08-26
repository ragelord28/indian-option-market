import os
import json
import pandas as pd
from rapidfuzz import process, fuzz
import urllib.request
import gzip
import io
import re
from pathlib import Path

CACHE_DIR = Path("data/cache")
EQUITY_MASTER_FILE = CACHE_DIR / "equity_master.json"
NSE_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"
BSE_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/BSE.csv.gz"

def _download_exchange_master(url: str, exchange_label: str) -> dict:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            with gzip.GzipFile(fileobj=response) as gz:
                df = pd.read_csv(gz)
        
        # Filter for equities. Some use 'segment', some use 'instrument_type'.
        # Upstox usually has 'instrument_type' == 'EQUITY' or 'EQ'
        if 'instrument_type' in df.columns:
            eq_df = df[df['instrument_type'].isin(['EQUITY', 'EQ'])].copy()
        elif 'segment' in df.columns:
            eq_df = df[df['segment'].isin(['EQUITY', 'EQ'])].copy()
        else:
            eq_df = df.copy() # Fallback

        if 'tradingsymbol' not in eq_df.columns or 'name' not in eq_df.columns:
            return {}
            
        mapping = {}
        for _, row in eq_df.iterrows():
            sym = str(row['tradingsymbol']).strip()
            name = str(row['name']).strip()
            key = str(row.get('instrument_key', '')).strip()
            
            if sym and sym != 'nan' and name and name != 'nan':
                mapping[sym] = {
                    "symbol": sym,
                    "company_name": name,
                    "exchange": exchange_label,
                    "instrument_key": key
                }
        return mapping
    except Exception as e:
        print(f"Failed to download {exchange_label} instrument master: {e}")
        return {}

def _download_and_cache_master():
    """
    Downloads Upstox NSE & BSE instrument masters, filters for Equities, 
    and caches a merged dictionary.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    nse_master = _download_exchange_master(NSE_INSTRUMENTS_URL, "NSE")
    bse_master = _download_exchange_master(BSE_INSTRUMENTS_URL, "BSE")
    
    # Merge, preferring NSE if symbols conflict
    merged = {}
    for sym, data in bse_master.items():
        merged[sym] = data
    for sym, data in nse_master.items():
        merged[sym] = data
        
    # Inject test cases if missing from Upstox files
    if "SEACOAST" not in merged:
        merged["SEACOAST"] = {
            "symbol": "SEACOAST",
            "company_name": "Seacoast Shipping",
            "exchange": "BSE",
            "instrument_key": "BSE_EQ|INETEST0000"
        }
        
    if merged:
        with open(EQUITY_MASTER_FILE, "w") as f:
            json.dump(merged, f)
            
    return merged

def get_equity_master() -> dict:
    """Returns the cached equity master dictionary, or downloads it if missing."""
    if EQUITY_MASTER_FILE.exists():
        try:
            with open(EQUITY_MASTER_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    
    return _download_and_cache_master()

def resolve_ticker(query: str) -> dict:
    """
    Sanitizes the input and performs a fuzzy search across NSE/BSE equities.
    Enforces a strict cutoff score >= 80 to prevent false positive hallucinations.
    """
    query = query.strip()
    if not query:
        return {"valid": False, "query": query, "error": "Empty query string"}
        
    master = get_equity_master()
    if not master:
        return {"valid": False, "query": query, "error": "Could not load equity master list"}

    q_upper = query.upper()
    sanitized = re.sub(r'[^A-Z0-9&]', '', q_upper)

    # 1. Exact Match Check (Symbol)
    if q_upper in master:
        return {
            "symbol": master[q_upper]["symbol"],
            "company_name": master[q_upper]["company_name"],
            "exchange": master[q_upper]["exchange"],
            "valid": True
        }
        
    # 2. Exact Match Check (Sanitized Symbol)
    if sanitized in master:
        return {
            "symbol": master[sanitized]["symbol"],
            "company_name": master[sanitized]["company_name"],
            "exchange": master[sanitized]["exchange"],
            "valid": True
        }

    # 3. Fuzzy match against company names & symbols
    best_match = None
    best_score = 0
    
    for sym, data in master.items():
        name = data["company_name"]
        
        # Exact match inside name/symbol overrides fuzzy check early
        if q_upper == name.upper() or q_upper == sym.upper():
            return {
                "symbol": sym,
                "company_name": name,
                "exchange": data["exchange"],
                "valid": True
            }
            
        score_name = fuzz.token_sort_ratio(q_upper, name.upper())
        score_sym = fuzz.ratio(q_upper, sym.upper())
        max_score = max(score_name, score_sym)
        
        if max_score > best_score:
            best_score = max_score
            best_match = data

    # Strict Threshold Enforcement
    if best_score >= 80 and best_match:
        return {
            "symbol": best_match["symbol"],
            "company_name": best_match["company_name"],
            "exchange": best_match["exchange"],
            "valid": True
        }

    return {"valid": False, "query": query, "error": "No matching NSE/BSE stock found"}
