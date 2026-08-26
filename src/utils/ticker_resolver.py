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
EQUITY_MASTER_FILE = CACHE_DIR / "nse_equity_master.json"
NSE_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"

def _download_and_cache_master():
    """
    Downloads Upstox NSE instrument master, filters for Equities (EQ), 
    and caches a dictionary of {symbol: company_name}.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        req = urllib.request.Request(NSE_INSTRUMENTS_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            with gzip.GzipFile(fileobj=response) as gz:
                df = pd.read_csv(gz)
        
        # Filter for equities (EQ)
        # Instrument type is 'EQUITY' for equity shares
        if 'instrument_type' in df.columns:
            eq_df = df[df['instrument_type'] == 'EQUITY'].copy()
        else:
            eq_df = df.copy() # Fallback

        if 'tradingsymbol' not in eq_df.columns or 'name' not in eq_df.columns:
            return {}

        # Create mapping of symbol -> name
        mapping = {}
        for _, row in eq_df.iterrows():
            sym = str(row['tradingsymbol']).strip()
            name = str(row['name']).strip()
            if sym and sym != 'nan' and name and name != 'nan':
                mapping[sym] = name
        
        with open(EQUITY_MASTER_FILE, "w") as f:
            json.dump(mapping, f)
            
        return mapping
        
    except Exception as e:
        print(f"Failed to download instrument master: {e}")
        return {}

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
    Sanitizes the input and performs a fuzzy search across NSE equities.
    Returns: {"symbol": "...", "company_name": "...", "valid": bool}
    """
    query = query.strip()
    if not query:
        return {"symbol": "", "company_name": "", "valid": False}
        
    master = get_equity_master()
    if not master:
        # Fallback if we can't load the master list
        sanitized = re.sub(r'[^A-Z0-9&]', '', query.upper())
        return {"symbol": sanitized, "company_name": "Unknown (Fallback)", "valid": True}

    # 1. Exact Match Check (Symbol)
    q_upper = query.upper()
    if q_upper in master:
        return {"symbol": q_upper, "company_name": master[q_upper], "valid": True}
        
    # 2. Exact Match Check (Sanitized Symbol)
    sanitized = re.sub(r'[^A-Z0-9&]', '', q_upper)
    if sanitized in master:
        return {"symbol": sanitized, "company_name": master[sanitized], "valid": True}

    # 3. Fuzzy match against company names
    # Create a list of tuples: (symbol, name)
    choices = [(sym, name) for sym, name in master.items()]
    
    # We want to fuzzy match against the 'name' (index 1 of the tuple)
    # rapidfuzz process.extractOne can take a processor or we can just extract manually
    best_match = None
    best_score = 0
    
    for sym, name in choices:
        # Check if the query is exactly in the name or symbol for a quick high score
        if q_upper == name.upper() or q_upper == sym.upper():
            return {"symbol": sym, "company_name": name, "valid": True}
            
        # Token sort ratio is good for "rolex rings" -> "Rolex Rings Limited"
        score = fuzz.token_sort_ratio(q_upper, name.upper())
        # Also check symbol
        sym_score = fuzz.ratio(q_upper, sym.upper())
        
        max_score = max(score, sym_score)
        
        if max_score > best_score:
            best_score = max_score
            best_match = (sym, name)

    # Threshold for a valid match (e.g. 60)
    if best_score > 60 and best_match:
        return {"symbol": best_match[0], "company_name": best_match[1], "valid": True}

    return {"symbol": sanitized, "company_name": "Not Found", "valid": False}

if __name__ == "__main__":
    # Test
    print(resolve_ticker("rolex rings"))
    print(resolve_ticker("tata motors"))
    print(resolve_ticker("hdfcbank"))
