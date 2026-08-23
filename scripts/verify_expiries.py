import urllib.request
import gzip
import io
import pandas as pd

print("Fetching live Upstox NSE F&O Instrument Master...")
url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"

req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req) as response:
    with gzip.GzipFile(fileobj=io.BytesIO(response.read())) as gz:
        df = pd.read_csv(gz)

# Filter for F&O contracts (OPTSTK = Stock Options, OPTIDX = Index Options)
fo_df = df[df['instrument_type'].isin(['OPTSTK', 'FUTSTK', 'OPTIDX', 'FUTIDX'])].copy()

# Convert expiry timestamp to datetime
fo_df['expiry_dt'] = pd.to_datetime(fo_df['expiry'])
fo_df['day_of_week'] = fo_df['expiry_dt'].dt.day_name()
fo_df['expiry_date_str'] = fo_df['expiry_dt'].dt.strftime('%Y-%m-%d')

print("\n" + "="*80)
print("1. NSE SINGLE-STOCK OPTIONS (OPTSTK) - ACTIVE EXPIRIES")
print("="*80)
stock_samples = ['RELIANCE', 'HDFCBANK', 'TCS', 'INFY', 'HAL', 'GNFC', 'ASHOKLEY']
stock_df = fo_df[(fo_df['tradingsymbol'].str.startswith(tuple(stock_samples))) & (fo_df['instrument_type'] == 'OPTSTK')]

stock_expiries = stock_df.groupby(['name', 'expiry_date_str', 'day_of_week']).size().reset_index(name='contract_count')
print(stock_expiries.to_markdown(index=False))

print("\n" + "="*80)
print("2. NSE INDEX OPTIONS (NIFTY / BANKNIFTY) - ACTIVE EXPIRIES")
print("="*80)
index_df = fo_df[(fo_df['name'].isin(['NIFTY', 'BANKNIFTY'])) & (fo_df['instrument_type'] == 'OPTIDX')]
index_expiries = index_df.groupby(['name', 'expiry_date_str', 'day_of_week']).size().reset_index(name='contract_count')
print(index_expiries.head(15).to_markdown(index=False))
print("="*80)
