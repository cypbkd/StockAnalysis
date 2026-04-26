"""
Fetches recent news headlines for a list of tickers via Yahoo Finance RSS,
then uses Gemini to write a short plain-English market summary.

API key resolution order (module-level cached after first successful fetch):
  1. GEMINI_API_KEY  env var  — for local dev / unit tests
  2. GEMINI_SECRET_NAME env var → AWS Secrets Manager fetch at runtime

Designed to be fault-tolerant: every external call is wrapped so a network
failure or missing credentials produces an empty string rather than crashing
the aggregator.
"""
import logging
import os
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Tuple

logger = logging.getLogger(__name__)

_YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockAnalysis/1.0)"}

_api_key_cache: str = ""


def _get_api_key() -> str:
    """Return the Gemini API key, fetching from Secrets Manager if needed."""
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache

    # Direct env var — local dev / CI
    direct = os.environ.get("GEMINI_API_KEY", "")
    if direct:
        _api_key_cache = direct
        return _api_key_cache

    # Secrets Manager — production Lambda
    secret_name = os.environ.get("GEMINI_SECRET_NAME", "")
    if not secret_name:
        logger.warning("Neither GEMINI_API_KEY nor GEMINI_SECRET_NAME is set")
        return ""

    try:
        import boto3
        sm = boto3.client("secretsmanager")
        resp = sm.get_secret_value(SecretId=secret_name)
        _api_key_cache = resp["SecretString"]
        logger.info("Loaded Gemini API key from Secrets Manager (%s)", secret_name)
        return _api_key_cache
    except Exception as exc:
        logger.error("Failed to fetch API key from Secrets Manager (%s): %s", secret_name, exc)
        return ""


def fetch_ticker_headlines(symbol: str, max_items: int = 3) -> List[str]:
    """Return up to max_items headline strings for symbol from Yahoo Finance RSS."""
    url = _YAHOO_RSS.format(symbol=symbol)
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=6) as resp:
            root = ET.fromstring(resp.read())
        headlines = []
        for item in root.findall(".//item")[:max_items]:
            title = (item.findtext("title") or "").strip()
            if title:
                headlines.append(title)
        return headlines
    except Exception as exc:
        logger.warning("News fetch failed for %s: %s", symbol, exc)
        return []


def generate_news_summary(
    high_priority_symbols: List[str],
    trade_date: str,
    max_tickers: int = 8,
    headlines_per_ticker: int = 3,
) -> str:
    """
    Fetch headlines for the top high-priority tickers and ask Gemini to
    write a 2-3 sentence market summary.  Returns '' on any failure.
    """
    api_key = _get_api_key()
    if not api_key:
        return ""

    symbols = high_priority_symbols[:max_tickers]
    if not symbols:
        return ""

    all_headlines: List[Tuple[str, str]] = []
    for symbol in symbols:
        for headline in fetch_ticker_headlines(symbol, max_items=headlines_per_ticker):
            all_headlines.append((symbol, headline))

    if not all_headlines:
        logger.info("No headlines fetched — skipping Gemini summarization")
        return ""

    ticker_list = ", ".join(symbols)
    headlines_block = "\n".join(f"[{sym}] {h}" for sym, h in all_headlines)

    prompt = (
        f"Today is {trade_date}. The following are recent news headlines for today's "
        f"high-priority stock picks: {ticker_list}.\n\n"
        f"{headlines_block}\n\n"
        "Write a 6-8 sentence plain-English market summary of what is driving these stocks today. "
        "Mention specific tickers where newsworthy. Be factual and cover the key themes across the group. "
        "Do not use bullet points, headers, or investment advice disclaimers."
    )

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=800,
                # Disable thinking — not needed for simple summarization,
                # and thinking tokens would consume the output budget.
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        summary = response.text.strip()
        logger.info("News summary generated (%d chars)", len(summary))
        return summary
    except Exception as exc:
        logger.error("Gemini news summary failed: %s", exc)
        return ""
