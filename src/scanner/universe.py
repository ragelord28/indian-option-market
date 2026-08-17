"""
F&O Stock Universe Definitions.

Defines:
1. TOP_50_FNO: Curated Top 50 liquid Indian FnO stock symbols for Agent 1.5 Radar.
2. FULL_FNO_UNIVERSE: Complete universe (~160+ major FnO equities) for full backtesting.
"""

TOP_50_FNO = [
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
_FULL_LIST = TOP_50_FNO + [
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
    "GNFC",
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
    "PEL",
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
    "SBIKARD",
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
    "MANAPPURAM": "Financial Services", "MCX": "Financial Services", "PEL": "Financial Services",
    "SBIKARD": "Financial Services", "IEX": "Financial Services", "IRFC": "Financial Services",
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
    "TATACHEM": "Chemicals & Agri", "GNFC": "Chemicals & Agri", "COROMANDEL": "Chemicals & Agri",
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

