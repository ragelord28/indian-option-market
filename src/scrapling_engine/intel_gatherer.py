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
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

CACHE_DIR = Path("data/cache/intel")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL = 4 * 3600

async def get_t_plus_3_return(symbol: str, event_date_str: str) -> tuple[float, str]:
    """Returns (return_pct, actual_t_date_str)"""
    try:
        event_date = datetime.datetime.strptime(event_date_str, "%Y-%m-%d").date()
    except Exception:
        return 0.0, ""
    
    start_date = event_date - datetime.timedelta(days=730)
    end_date = datetime.date.today()
    
    df = await asyncio.to_thread(yf.download, f"{symbol}.NS", start=start_date, end=end_date, progress=False)
    
    if df.empty:
        return 0.0, ""
    
    idx_mask = df.index >= pd.to_datetime(event_date)
    if not idx_mask.any():
        return 0.0, ""
    
    t_idx = df.index[idx_mask][0]
    loc_t = df.index.get_loc(t_idx)
    
    if loc_t + 3 >= len(df):
        return 0.0, t_idx.strftime("%Y-%m-%d")
    
    t_close = float(df['Close'].iloc[loc_t])
    t3_close = float(df['Close'].iloc[loc_t + 3])
    
    if t_close == 0:
        return 0.0, t_idx.strftime("%Y-%m-%d")
    return ((t3_close - t_close) / t_close) * 100.0, t_idx.strftime("%Y-%m-%d")


def extract_content(url: str, title: str, snippet: str) -> dict:
    try:
        fetcher = Fetcher()
        page = fetcher.get(url)
        content = ""
        for el in page.css("script[type='application/ld+json']"):
            content += el.text + "\n"
        meta_desc = page.css("meta[name='description'], meta[property='og:description']")
        if meta_desc:
            content += meta_desc[0].attrib.get('content', '') + "\n"
        
        body_text = page.css("body")[0].text_content() if page.css("body") else ""
        content += body_text[:1000]
        content = content.strip()
        
        if not content:
            content = snippet
            
        return {"url": url, "title": title, "snippet": snippet, "content": content[:1500]}
    except Exception:
        return {"url": url, "title": title, "snippet": snippet, "content": snippet}


async def _call_llm(system_prompt: str, user_prompt: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        if "category" in system_prompt.lower() or "catalyst_summary" in system_prompt.lower():
            return json.dumps({
                "catalyst_summary": "Mock summary: Strong earnings reported.",
                "catalyst_category": "Earnings Beat",
                "sentiment_score": 0.8
            })
        elif "date" in system_prompt.lower():
            return "2023-10-15"
        else:
            return json.dumps({
                "catalyst_summary": "Mock summary.",
                "sentiment_score": 0.8,
                "historical_precedence": "Mock history."
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
    except Exception as e:
        print(f"LLM Error: {e}")
        return ""


async def gather_stock_intel(symbol: str, company_name: str = "") -> dict:
    cache_file = CACHE_DIR / f"{symbol}_intel.json"
    if cache_file.exists():
        if time.time() - cache_file.stat().st_mtime < CACHE_TTL:
            try:
                with open(cache_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass

    ddgs = DDGS()
    query_name = company_name if company_name else symbol
    query = f"{symbol} {query_name} stock news"
    
    # 1. Scrape News (last 24-48h, top 10-15)
    results = []
    try:
        results = await asyncio.to_thread(lambda: list(ddgs.text(query, timelimit='d', max_results=15)))
    except Exception:
        pass
    
    if not results:
        # fallback to 'w' if 'd' returns nothing
        try:
            results = await asyncio.to_thread(lambda: list(ddgs.text(query, timelimit='w', max_results=15)))
        except Exception:
            pass
            
    # Concurrently scrape top 6
    tasks = []
    top_results = results[:6]
    for r in top_results:
        if r.get('href'):
            tasks.append(asyncio.to_thread(extract_content, r.get('href'), r.get('title', ''), r.get('body', '')))
            
    scraped_data = await asyncio.gather(*tasks) if tasks else []
    
    # Add remaining DDG results as just title/snippet
    all_articles = []
    for data in scraped_data:
        all_articles.append(data)
    for r in results[6:]:
        all_articles.append({
            "url": r.get("href", ""),
            "title": r.get("title", ""),
            "snippet": r.get("body", ""),
            "content": r.get("body", "")
        })
        
    news_content = ""
    for idx, art in enumerate(all_articles):
        news_content += f"[{idx+1}] Title: {art['title']}\nURL: {art['url']}\nContent: {art['content']}\n\n"
    
    # 2. Catalyst Classification
    cat_sys = """You are an elite financial analyst. Read the news articles and output strict JSON with:
- "catalyst_summary": (string) concise bullet points of verified news (<48h).
- "catalyst_category": (string) e.g., "Earnings Beat", "Contract Win", "SEBI Regulatory", "Block Deal", "Management Exit", or "General Market Noise".
- "sentiment_score": (float) between -1.0 (Bearish) and +1.0 (Bullish)."""
    
    classification_resp = await _call_llm(cat_sys, news_content[:8000]) # roughly limit to avoid huge prompts
    try:
        if "```json" in classification_resp:
            classification_resp = classification_resp.split("```json")[1].split("```")[0]
        elif "```" in classification_resp:
            classification_resp = classification_resp.split("```")[1].split("```")[0]
        class_data = json.loads(classification_resp.strip())
    except Exception:
        class_data = {
            "catalyst_summary": "Unable to generate summary due to parsing error.",
            "catalyst_category": "General Market Noise",
            "sentiment_score": 0.0
        }
        
    catalyst_cat = class_data.get("catalyst_category", "General Market Noise")
    
    # 3. Historical Precedence Hunt
    impact = 0.0
    extracted_date = ""
    actual_date = ""
    historical_precedence = "No identical historical catalyst found in past 2 years."
    
    if "noise" not in catalyst_cat.lower():
        hist_query = f"{symbol} {query_name} {catalyst_cat} 2023 2024"
        hist_results = []
        try:
            hist_results = await asyncio.to_thread(lambda: list(ddgs.text(hist_query, max_results=5)))
        except Exception:
            pass
            
        date_sys = "Extract the most relevant past date (YYYY-MM-DD) from the text when a similar event occurred 1-2 years ago. If none, output 'NONE'. ONLY output the date string or 'NONE'."
        hist_text = json.dumps(hist_results)
        extracted_date = await _call_llm(date_sys, hist_text)
        extracted_date = extracted_date.strip()
        
        if extracted_date and "NONE" not in extracted_date.upper() and len(extracted_date) >= 10:
            impact, actual_date = await get_t_plus_3_return(symbol, extracted_date[:10])
            if actual_date:
                historical_precedence = f"In {actual_date} on a similar '{catalyst_cat}' catalyst, the stock experienced a {impact:+.2f}% return over the subsequent 3 trading days."
    
    # 4. Final Output Construction
    final_data = {
        "catalyst_summary": class_data.get("catalyst_summary", ""),
        "catalyst_category": catalyst_cat,
        "sentiment_score": float(class_data.get("sentiment_score", 0.0)),
        "historical_precedence": historical_precedence,
        "articles": all_articles
    }
        
    with open(cache_file, "w") as f:
        json.dump(final_data, f)
        
    return final_data
