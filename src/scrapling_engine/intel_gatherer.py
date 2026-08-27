import os
import json
import asyncio
import time
import datetime
from pathlib import Path
from duckduckgo_search import DDGS
from scrapling import Fetcher
import yfinance as yf
from openai import AsyncOpenAI
import pandas as pd

CACHE_DIR = Path("data/cache/intel")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL = 4 * 3600

async def get_t_plus_3_return(symbol: str, event_date_str: str) -> float:
    try:
        event_date = datetime.datetime.strptime(event_date_str, "%Y-%m-%d").date()
    except Exception:
        return 0.0
    
    start_date = event_date - datetime.timedelta(days=10)
    end_date = event_date + datetime.timedelta(days=20)
    
    # Run yf.download in a separate thread so it doesn't block asyncio
    df = await asyncio.to_thread(yf.download, f"{symbol}.NS", start=start_date, end=end_date, progress=False)
    
    if df.empty:
        return 0.0
    
    idx_mask = df.index >= pd.to_datetime(event_date)
    if not idx_mask.any():
        return 0.0
    
    t_idx = df.index[idx_mask][0]
    loc_t = df.index.get_loc(t_idx)
    
    if loc_t + 3 >= len(df):
        return 0.0
    
    t_close = float(df['Close'].iloc[loc_t])
    t3_close = float(df['Close'].iloc[loc_t + 3])
    
    if t_close == 0:
        return 0.0
    return ((t3_close - t_close) / t_close) * 100.0


def extract_content(url: str) -> str:
    try:
        fetcher = Fetcher()
        page = fetcher.get(url)
        content = ""
        for el in page.css("script[type='application/ld+json']"):
            content += el.text + "\n"
        meta = page.css("meta[name='description']")
        if meta:
            content += meta[0].attrib.get('content', '') + "\n"
        
        body_text = page.css("body")[0].text_content() if page.css("body") else ""
        content += body_text[:1000]
        return content[:1500]
    except Exception:
        return ""


async def _call_llm(system_prompt: str, user_prompt: str) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        # Fallback mock when running in environments without the key
        if "category" in system_prompt.lower():
            return "Earnings Beat"
        elif "date" in system_prompt.lower():
            return "2023-10-15"
        else:
            return json.dumps({
                "catalyst_summary": "Mock summary of recent news.",
                "sentiment_score": 0.8,
                "historical_precedence": "In Oct 2023 on a similar catalyst, the stock rallied 4.2% over 3 days."
            })
    
    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )
    
    try:
        completion = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3
        )
        return completion.choices[0].message.content
    except Exception:
        return ""


async def gather_stock_intel(symbol: str) -> dict:
    cache_file = CACHE_DIR / f"{symbol}_intel.json"
    if cache_file.exists():
        if time.time() - cache_file.stat().st_mtime < CACHE_TTL:
            try:
                with open(cache_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass

    ddgs = DDGS()
    query = f"{symbol} stock news"
    
    # 1. Scrape News (last 48h)
    results = []
    try:
        results = await asyncio.to_thread(lambda: list(ddgs.text(query, timelimit='w', max_results=3)))
    except Exception:
        pass
    
    news_content = ""
    for r in results:
        news_content += f"Title: {r.get('title')}\nSnippet: {r.get('body')}\n"
        if r.get('href'):
            news_content += await asyncio.to_thread(extract_content, r.get('href')) + "\n\n"
    
    # 2. Catalyst Classification
    cat_sys = "You are a financial analyst. Identify the main catalyst category from the news. Output ONLY the category name (e.g., 'Earnings Beat', 'Contract Win', 'Regulatory', 'Market Momentum')."
    catalyst = await _call_llm(cat_sys, news_content)
    catalyst = catalyst.strip() if catalyst else "Market Momentum"
    
    # 3. Historical Precedence Hunt
    hist_query = f"{symbol} {catalyst} 2023 2024"
    hist_results = []
    try:
        hist_results = await asyncio.to_thread(lambda: list(ddgs.text(hist_query, max_results=3)))
    except Exception:
        pass
        
    date_sys = "Extract the most relevant past date (YYYY-MM-DD) from the text when a similar event occurred. If none, output '2023-01-01'. ONLY output the date string."
    hist_text = json.dumps(hist_results)
    extracted_date = await _call_llm(date_sys, hist_text)
    extracted_date = extracted_date.strip()
    if not extracted_date or len(extracted_date) > 10:
        extracted_date = "2023-01-01"
        
    # 4. T+3 Impact
    impact = await get_t_plus_3_return(symbol, extracted_date[:10])
    
    # 5. Final Synthesis
    synth_sys = "You are an expert analyst. Output strict JSON with keys: 'catalyst_summary' (string), 'sentiment_score' (float -1.0 to 1.0), 'historical_precedence' (string explaining the past event and price action)."
    prompt = f"News:\n{news_content[:1500]}\nCatalyst: {catalyst}\nPast Impact: {impact:.2f}% on {extracted_date[:10]}"
    
    final_resp = await _call_llm(synth_sys, prompt)
    try:
        if "```json" in final_resp:
            final_resp = final_resp.split("```json")[1].split("```")[0]
        elif "```" in final_resp:
            final_resp = final_resp.split("```")[1].split("```")[0]
        final_data = json.loads(final_resp.strip())
    except Exception:
        final_data = {
            "catalyst_summary": "Unable to generate summary due to parsing error.",
            "sentiment_score": 0.0,
            "historical_precedence": f"Past impact was {impact:.2f}%."
        }
        
    with open(cache_file, "w") as f:
        json.dump(final_data, f)
        
    return final_data
