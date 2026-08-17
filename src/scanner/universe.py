import gzip
import io
import json
import logging
import re
import urllib.request
from pathlib import Path
from typing import List, Dict, Set

import pandas as pd

logger = logging.getLogger(__name__)

_TOP_50_RAW = [
    "RELIANCE",
    "HDFCBANK",
    "ICICIBANK",
    "INFY",
    "ITC",
    "TCS",
    "LT",
    "BHARTIARTL",
    "AXISBANK",
    "SBIN",
    "KOTAKBANK",
    "BAJFINANCE",
    "HINDUNILVR",
    "M&M",
    "TATAMOTORS",
    "MARUTI",
    "SUNPHARMA",
    "NTPC",
    "TATASTEEL",
    "POWERGRID",
    "ULTRACEMCO",
    "ASIANPAINT",
    "COALINDIA",
    "TITAN",
    "ADANIENT",
    "ADANIPORTS",
    "BAJAJFINSV",
    "ONGC",
    "HCLTECH",
    "WIPRO",
    "DRREDDY",
    "GRASIM",
    "TECHM",
    "HINDALCO",
    "JSWSTEEL",
    "CIPLA",
    "TATACONSUM",
    "EICHERMOT",
    "APOLLOHOSP",
    "DIVISLAB",
    "BRITANNIA",
    "HEROMOTOCO",
    "SHRIRAMFIN",
    "BPCL",
    "LTIM",
    "TRENT",
    "INDUSINDBK",
    "BAJAJ-AUTO",
    "HDFCLIFE",
    "SBILIFE",
]

# Combined unique list of full NSE F&O universe
_FULL_LIST = _TOP_50_RAW + [
    "AARTIIND",
    "ABB",
    "ABBOTINDIA",
    "ABCAPITAL",
    "ACC",
    "ADANIENSOL",
    "ALKEM",
    "AMBUJACEM",
    "APOLLOTYRE",
    "ASHOKLEY",
    "ASTRAL",
    "ATUL",
    "AUBANK",
    "AUROPHARMA",
    "BALKRISIND",
    "BALRAMCHIN",
    "BANDHANBNK",
    "BANKBARODA",
    "BATAINDIA",
    "BEL",
    "BERGEPAINT",
    "BHARATFORG",
    "BHEL",
    "BIOCON",
    "BSOFT",
    "CANBK",
    "CANFINHOME",
    "CHAMBLFERT",
    "CHOLAFIN",
    "COFORGE",
    "COLPAL",
    "CONCOR",
    "COROMANDEL",
    "CROMPTON",
    "CUB",
    "CUMMINSIND",
    "DABUR",
    "DALBHARAT",
    "DEEPAKNTR",
    "DELTACORP",
    "DIXON",
    "DLF",
    "ESCORTS",
    "FEDERALBNK",
    "GAIL",
    "GLENMARK",
    "GODREJCP",
    "GODREJPROP",
    "GRANULES",
    "HAVELLS",
    "HAL",
    "IDEA",
    "IDFCFIRSTB",
    "IEX",
    "IPCALAB",
    "IRCTC",
    "IRFC",
    "JINDALSTEL",
    "JKCEMENT",
    "LAURUSLABS",
    "LICHSGFIN",
    "LICI",
    "LUPIN",
    "M&MFIN",
    "MANAPPURAM",
    "MARICO",
    "MAXHEALTH",
    "MCX",
    "METROPOLIS",
    "MFSL",
    "MGL",
    "MOTHERSON",
    "MPHASIS",
    "MRF",
    "MUTHOOTFIN",
    "NATIONALUM",
    "NAUKRI",
    "NAVINFLUOR",
    "NCC",
    "NESTLEIND",
    "NHPC",
    "NMDC",
    "NYKAA",
    "OBEROIRLTY",
    "OFSS",
    "OIL",
    "PAGEIND",
    "PERSISTENT",
    "PETRONET",
    "PFC",
    "PIDILITIND",
    "PIIND",
    "PNB",
    "POLYCAB",
    "POONAWALLA",
    "PVRINOX",
    "RAMCOCEM",
    "RBLBANK",
    "RECLTD",
    "SAIL",
    "SBICARD",
    "SIEMENS",
    "SRF",
    "SYNGENE",
    "TATACHEM",
    "TATACOMM",
    "TVSMOTOR",
    "UBL",
    "VOLTAS",
    "ZEEL",
]

# Deduplicate while preserving order
FULL_FNO_UNIVERSE = list(dict.fromkeys(_FULL_LIST))

SECTOR_MAP = {
    # Auto
    "TATAMOTORS": "Auto", "M&M": "Auto", "MARUTI": "Auto", "ASHOKLEY": "Auto", "BAJAJ-AUTO": "Auto",
    "EICHERMOT": "Auto", "HEROMOTOCO": "Auto", "TVSMOTOR": "Auto", "BHARATFORG": "Auto",
    "MOTHERSON": "Auto", "BALKRISIND": "Auto", "ESCORTS": "Auto", "APOLLOTYRE": "Auto", "MRF": "Auto",

    # Banking
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking", "KOTAKBANK": "Banking",
    "AXISBANK": "Banking", "INDUSINDBK": "Banking", "BANKBARODA": "Banking", "PNB": "Banking",
    "CANBK": "Banking", "AUBANK": "Banking", "FEDERALBNK": "Banking", "IDFCFIRSTB": "Banking",
    "BANDHANBNK": "Banking", "CUB": "Banking", "RBLBANK": "Banking",

    # Financial Services / NBFC
    "BAJFINANCE": "Financial Services", "BAJAJFINSV": "Financial Services", "CHOLAFIN": "Financial Services",
    "MUTHOOTFIN": "Financial Services", "SHRIRAMFIN": "Financial Services", "RECLTD": "Financial Services",
    "PFC": "Financial Services", "LICHSGFIN": "Financial Services", "SBILIFE": "Financial Services",
    "HDFCLIFE": "Financial Services", "ICICIPRULI": "Financial Services", "HDFCAMC": "Financial Services",
    "ABCAPITAL": "Financial Services", "CANFINHOME": "Financial Services", "M&MFIN": "Financial Services",
    "MANAPPURAM": "Financial Services", "MCX": "Financial Services",
    "SBICARD": "Financial Services", "IEX": "Financial Services", "IRFC": "Financial Services",
    "LICI": "Financial Services", "MFSL": "Financial Services", "POONAWALLA": "Financial Services",

    # IT
    "TCS": "IT", "INFY": "IT", "HCLTECH": "IT", "WIPRO": "IT", "TECHM": "IT", "LTIM": "IT",
    "COFORGE": "IT", "PERSISTENT": "IT", "LTTS": "IT", "MPHASIS": "IT", "BSOFT": "IT", "OFSS": "IT",
    "NAUKRI": "IT",

    # Oil, Gas & Energy
    "RELIANCE": "Oil, Gas & Energy", "ONGC": "Oil, Gas & Energy", "BPCL": "Oil, Gas & Energy",
    "IOC": "Oil, Gas & Energy", "GAIL": "Oil, Gas & Energy", "NTPC": "Oil, Gas & Energy",
    "POWERGRID": "Oil, Gas & Energy", "TATAPOWER": "Oil, Gas & Energy", "ADANIGREEN": "Oil, Gas & Energy",
    "ADANIPOWER": "Oil, Gas & Energy", "IGL": "Oil, Gas & Energy", "MGL": "Oil, Gas & Energy",
    "PETRONET": "Oil, Gas & Energy", "ADANIENSOL": "Oil, Gas & Energy", "NHPC": "Oil, Gas & Energy",
    "OIL": "Oil, Gas & Energy",

    # Metals & Mining
    "TATASTEEL": "Metals & Mining", "JSWSTEEL": "Metals & Mining", "HINDALCO": "Metals & Mining",
    "VEDL": "Metals & Mining", "JINDALSTEL": "Metals & Mining", "NATIONALUM": "Metals & Mining",
    "NMDC": "Metals & Mining", "COALINDIA": "Metals & Mining", "SAIL": "Metals & Mining",

    # Pharma & Healthcare
    "SUNPHARMA": "Pharma & Healthcare", "DRREDDY": "Pharma & Healthcare", "CIPLA": "Pharma & Healthcare",
    "DIVISLAB": "Pharma & Healthcare", "LUPIN": "Pharma & Healthcare", "APOLLOHOSP": "Pharma & Healthcare",
    "BIOCON": "Pharma & Healthcare", "TORNTPHARM": "Pharma & Healthcare", "AUROPHARMA": "Pharma & Healthcare",
    "MAXHEALTH": "Pharma & Healthcare", "ABBOTINDIA": "Pharma & Healthcare", "ALKEM": "Pharma & Healthcare",
    "GLENMARK": "Pharma & Healthcare", "GRANULES": "Pharma & Healthcare", "IPCALAB": "Pharma & Healthcare",
    "LAURUSLABS": "Pharma & Healthcare", "SYNGENE": "Pharma & Healthcare", "METROPOLIS": "Pharma & Healthcare",

    # FMCG & Consumption
    "ITC": "FMCG & Consumption", "HINDUNILVR": "FMCG & Consumption", "NESTLEIND": "FMCG & Consumption",
    "BRITANNIA": "FMCG & Consumption", "TATACONSUM": "FMCG & Consumption", "DABUR": "FMCG & Consumption",
    "MARICO": "FMCG & Consumption", "GODREJCP": "FMCG & Consumption", "COLPAL": "FMCG & Consumption",
    "VBL": "FMCG & Consumption", "TITAN": "FMCG & Consumption", "ASIANPAINT": "FMCG & Consumption",
    "BERGEPAINT": "FMCG & Consumption", "PIDILITIND": "FMCG & Consumption", "PAGEIND": "FMCG & Consumption",
    "BATAINDIA": "FMCG & Consumption", "TRENT": "FMCG & Consumption", "BALRAMCHIN": "FMCG & Consumption",
    "UBL": "FMCG & Consumption", "NYKAA": "FMCG & Consumption",

    # Chemicals & Agri
    "PIIND": "Chemicals & Agri", "AARTIIND": "Chemicals & Agri", "DEEPAKNTR": "Chemicals & Agri",
    "SRF": "Chemicals & Agri", "NAVINFLUOR": "Chemicals & Agri", "UPL": "Chemicals & Agri",
    "TATACHEM": "Chemicals & Agri", "COROMANDEL": "Chemicals & Agri",
    "CHAMBLFERT": "Chemicals & Agri", "ATUL": "Chemicals & Agri",

    # Capital Goods & Defence
    "LT": "Capital Goods & Defence", "HAL": "Capital Goods & Defence", "BEL": "Capital Goods & Defence",
    "BHEL": "Capital Goods & Defence", "SIEMENS": "Capital Goods & Defence", "ABB": "Capital Goods & Defence",
    "CUMMINSIND": "Capital Goods & Defence", "POLYCAB": "Capital Goods & Defence", "KEI": "Capital Goods & Defence",
    "HAVELLS": "Capital Goods & Defence", "CONCOR": "Capital Goods & Defence", "CROMPTON": "Capital Goods & Defence",
    "VOLTAS": "Capital Goods & Defence", "ASTRAL": "Capital Goods & Defence", "DIXON": "Capital Goods & Defence",

    # Cement & Real Estate
    "ULTRACEMCO": "Cement & Real Estate", "AMBUJACEM": "Cement & Real Estate", "GRASIM": "Cement & Real Estate",
    "ACC": "Cement & Real Estate", "DLF": "Cement & Real Estate", "GODREJPROP": "Cement & Real Estate",
    "OBEROIRLTY": "Cement & Real Estate", "DALBHARAT": "Cement & Real Estate", "JKCEMENT": "Cement & Real Estate",
    "RAMCOCEM": "Cement & Real Estate", "NCC": "Cement & Real Estate",

    # Telecom & Media
    "BHARTIARTL": "Telecom & Media", "INDUSTOWER": "Telecom & Media", "SUNTV": "Telecom & Media",
    "PVRINOX": "Telecom & Media", "ZEEL": "Telecom & Media", "DELTACORP": "Telecom & Media",
    "IDEA": "Telecom & Media", "TATACOMM": "Telecom & Media",

    # Services & Infrastructure
    "ADANIENT": "Services & Infra", "ADANIPORTS": "Services & Infra", "IRCTC": "Services & Infra",

    # Indices
    "NIFTY50": "Index", "NIFTY": "Index", "BANKNIFTY": "Index", "FINNIFTY": "Index",
}


def get_sector(symbol: str) -> str:
    """
    Resolve industry sector classification for an NSE F&O symbol.
    If unmapped, defaults to the clean uppercase ticker name so it never shares
    a generic "Diversified" bucket with another stock.
    """
    clean_sym = symbol.replace(".NS", "").replace("^", "").strip().upper()
    return SECTOR_MAP.get(clean_sym, clean_sym)


LOT_SIZE_MAP = {
    "RELIANCE": 250, "HDFCBANK": 550, "ICICIBANK": 700, "INFY": 400, "ITC": 1600,
    "TCS": 175, "LT": 150, "BHARTIARTL": 475, "AXISBANK": 625, "SBIN": 750,
    "KOTAKBANK": 400, "BAJFINANCE": 125, "HINDUNILVR": 300, "M&M": 350, "TATAMOTORS": 550,
    "MARUTI": 100, "SUNPHARMA": 350, "NTPC": 1500, "TATASTEEL": 5500, "POWERGRID": 1800,
    "ULTRACEMCO": 100, "ASIANPAINT": 200, "COALINDIA": 2100, "TITAN": 175, "ADANIENT": 300,
    "ADANIPORTS": 400, "BAJAJFINSV": 500, "ONGC": 1925, "HCLTECH": 350, "WIPRO": 1500,
    "DRREDDY": 125, "GRASIM": 250, "TECHM": 600, "HINDALCO": 1400, "JSWSTEEL": 675,
    "CIPLA": 650, "TATACONSUM": 450, "EICHERMOT": 175, "APOLLOHOSP": 125, "DIVISLAB": 150,
    "BRITANNIA": 200, "HEROMOTOCO": 150, "SHRIRAMFIN": 300, "BPCL": 1800, "LTIM": 150,
    "TRENT": 100, "INDUSINDBK": 500, "BAJAJ-AUTO": 125, "HDFCLIFE": 1100, "SBILIFE": 375,
    "AARTIIND": 1000, "ABB": 125, "ABBOTINDIA": 40, "ABCAPITAL": 2700, "ACC": 300,
    "ADANIENSOL": 700, "ALKEM": 125, "AMBUJACEM": 1800, "APOLLOTYRE": 1700, "ASHOKLEY": 5000,
    "ASTRAL": 375, "ATUL": 150, "AUBANK": 1000, "AUROPHARMA": 550, "BALKRISIND": 300,
    "BALRAMCHIN": 1600, "BANDHANBNK": 2500, "BANKBARODA": 2925, "BATAINDIA": 375, "BEL": 2850,
    "BERGEPAINT": 1100, "BHARATFORG": 500, "BHEL": 2625, "BIOCON": 2500, "BSOFT": 1000,
    "CANBK": 2700, "CANFINHOME": 900, "CHAMBLFERT": 1500, "CHOLAFIN": 625, "COFORGE": 150,
    "COLPAL": 350, "CONCOR": 1000, "COROMANDEL": 700, "CROMPTON": 1500, "CUB": 5000,
    "CUMMINSIND": 300, "DABUR": 1250, "DALBHARAT": 275, "DEEPAKNTR": 300, "DELTACORP": 2800,
    "DIXON": 100, "DLF": 825, "ESCORTS": 175, "FEDERALBNK": 5000, "GAIL": 2700,
    "GLENMARK": 725, "GODREJCP": 500, "GODREJPROP": 225, "GRANULES": 2000,
    "HAVELLS": 500, "HAL": 150, "IDEA": 80000, "IDFCFIRSTB": 7500, "IEX": 3750,
    "IPCALAB": 650, "IRCTC": 875, "IRFC": 4000, "JINDALSTEL": 625, "JKCEMENT": 250,
    "LAURUSLABS": 1700, "LICHSGFIN": 1000, "LICI": 600, "LUPIN": 425, "M&MFIN": 2000,
    "MANAPPURAM": 3000, "MARICO": 1200, "MAXHEALTH": 1000, "MCX": 125, "METROPOLIS": 200,
    "MFSL": 800, "MGL": 400, "MOTHERSON": 3150, "MPHASIS": 275, "MRF": 10,
    "MUTHOOTFIN": 550, "NATIONALUM": 3750, "NAUKRI": 150, "NAVINFLUOR": 175, "NCC": 3000,
    "NESTLEIND": 250, "NHPC": 6000, "NMDC": 4500, "NYKAA": 1875, "OBEROIRLTY": 350,
    "OFSS": 100, "OIL": 2100, "PAGEIND": 15, "PERSISTENT": 100,
    "PETRONET": 3000, "PFC": 1300, "PIDILITIND": 250, "PIIND": 250, "PNB": 4000,
    "POLYCAB": 125, "POONAWALLA": 1500, "PVRINOX": 407, "RAMCOCEM": 850, "RBLBANK": 2500,
    "RECLTD": 1400, "SAIL": 4000, "SBICARD": 800, "SIEMENS": 150, "SRF": 375,
    "SYNGENE": 1000, "TATACHEM": 1000, "TATACOMM": 500, "TATAPOWER": 1650, "TVSMOTOR": 350,
    "UBL": 400, "UPL": 1300, "VEDL": 2300, "VOLTAS": 600, "ZEEL": 3000,
    "NIFTY50": 25, "NIFTY": 25, "BANKNIFTY": 15, "FINNIFTY": 25,
}


def sync_universe_from_exchange_master(
    cache_path: Path | str = Path("data/cache/valid_optstk_symbols.json"),
) -> List[str]:
    """
    Download and parse Upstox NSE Instrument Master GZ CSV, filter OPTSTK instruments,
    extract valid underlying symbols and exact lot sizes, cache to JSON, and return
    the sorted list of verified OPTSTK symbols.
    """
    c_path = Path(cache_path)
    c_path.parent.mkdir(parents=True, exist_ok=True)

    url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"
    symbols_map: Dict[str, int] = {}

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            with gzip.GzipFile(fileobj=io.BytesIO(response.read())) as gz:
                df = pd.read_csv(gz)

        optstk = df[df["instrument_type"] == "OPTSTK"]
        pattern = re.compile(r"^([A-Z0-9\&\-]+?)\d{2}[A-Z]{3}")

        for _, row in optstk.iterrows():
            ts = str(row.get("tradingsymbol", ""))
            m = pattern.match(ts)
            if m:
                sym = m.group(1)
                lot = int(row.get("lot_size", 250))
                symbols_map[sym] = lot

        if symbols_map:
            with open(c_path, "w", encoding="utf-8") as f:
                json.dump(symbols_map, f, indent=2)
            LOT_SIZE_MAP.update(symbols_map)
    except Exception as err:
        logger.warning(f"Could not fetch Upstox exchange master: {err}")
        if c_path.exists():
            try:
                with open(c_path, "r", encoding="utf-8") as f:
                    symbols_map = json.load(f)
                    LOT_SIZE_MAP.update(symbols_map)
            except Exception:
                pass

    valid_symbols = set(symbols_map.keys()) if symbols_map else set()
    return sorted(list(valid_symbols))


def _get_verified_universe(raw_list: List[str]) -> List[str]:
    c_path = Path("data/cache/valid_optstk_symbols.json")
    if c_path.exists() and c_path.stat().st_size > 0:
        try:
            with open(c_path, "r", encoding="utf-8") as f:
                valid_map = json.load(f)
                valid_set = set(valid_map.keys())
                LOT_SIZE_MAP.update(valid_map)
                indices = {"NIFTY50", "NIFTY", "BANKNIFTY", "FINNIFTY"}
                return [s for s in raw_list if s in valid_set or s in indices]
        except Exception:
            pass
    return raw_list


FULL_FNO_UNIVERSE = _get_verified_universe(list(dict.fromkeys(_FULL_LIST)))
TOP_50_FNO = _get_verified_universe(_TOP_50_RAW)


def get_lot_size(symbol: str) -> int:
    """Resolve official NSE lot size for symbol."""
    clean_sym = symbol.replace(".NS", "").replace("^", "").strip().upper()
    return LOT_SIZE_MAP.get(clean_sym, 250)



