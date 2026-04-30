"""
Fetches the Yahoo Finance daily trending ticker list and enriches each symbol
with 3-day price/volume data and recent news headlines.

Used by the aggregator to build the trendingTickers section of the nightly report.
Fault-tolerant: any per-ticker failure is skipped; total failure returns [].

Flow:
  fetch_yahoo_trending()        → list[str]   (symbols from Yahoo Finance trending API)
  _fetch_price_data(symbol)     → dict | None (3d return, vol ratio from yfinance)
  build_trending_tickers()      → list[dict]  (enriched ticker dicts for the report)
"""
import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional

from stock_analysis.data import COMPANY_NAMES
from stock_analysis.news import fetch_ticker_headlines

logger = logging.getLogger(__name__)

_TRENDING_URL = (
    "https://query1.finance.yahoo.com/v1/finance/trending/US"
    "?count=25&useQuotes=true"
)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockAnalysis/1.0)"}


def fetch_yahoo_trending(count: int = 20) -> List[str]:
    """Return up to `count` trending ticker symbols from Yahoo Finance."""
    try:
        req = urllib.request.Request(_TRENDING_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        quotes = data["finance"]["result"][0]["quotes"]
        symbols = [q["symbol"] for q in quotes if q.get("symbol")]
        logger.info("Fetched %d trending tickers from Yahoo Finance", len(symbols))
        return symbols[:count]
    except Exception as exc:
        logger.warning("Failed to fetch Yahoo Finance trending list: %s", exc)
        return []


def _fetch_price_data(symbol: str) -> Optional[Dict[str, Any]]:
    """Download 5 days of OHLCV for symbol and return key price metrics."""
    try:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period="5d", auto_adjust=True)
        if hist.empty or len(hist) < 2:
            return None

        closes = hist["Close"]
        last_close = float(closes.iloc[-1])
        prev_close = float(closes.iloc[-2])

        change_1d = (last_close / prev_close - 1) * 100 if prev_close else 0.0

        # 3-day: from the close 3 trading sessions before last to last
        idx_3d = max(0, len(closes) - 4)
        close_3d_ago = float(closes.iloc[idx_3d])
        change_3d = (last_close / close_3d_ago - 1) * 100 if close_3d_ago else 0.0

        vols = hist["Volume"]
        today_vol = float(vols.iloc[-1])
        avg_prior_vol = float(vols.iloc[:-1].mean()) if len(vols) > 1 else today_vol
        volume_ratio = today_vol / avg_prior_vol if avg_prior_vol > 0 else 1.0

        return {
            "lastPrice": round(last_close, 2),
            "change1d": round(change_1d, 2),
            "change3d": round(change_3d, 2),
            "volumeRatio": round(volume_ratio, 2),
        }
    except Exception as exc:
        logger.warning("Price data fetch failed for %s: %s", symbol, exc)
        return None


def build_trending_tickers(
    trade_date: str,
    max_tickers: int = 15,
    headlines_per_ticker: int = 2,
) -> List[Dict[str, Any]]:
    """
    Fetch trending tickers from Yahoo Finance and enrich with 3-day price data
    and recent headlines.  Returns up to max_tickers entries.
    Returns [] on complete failure.
    """
    raw_symbols = fetch_yahoo_trending(count=max_tickers + 5)
    if not raw_symbols:
        logger.info("No trending symbols fetched — skipping trending section")
        return []

    results: List[Dict[str, Any]] = []
    for rank, symbol in enumerate(raw_symbols, start=1):
        if len(results) >= max_tickers:
            break

        price_data = _fetch_price_data(symbol)
        if not price_data:
            logger.debug("Skipping trending ticker %s — no price data", symbol)
            continue

        headlines = fetch_ticker_headlines(symbol, max_items=headlines_per_ticker)
        company_name = COMPANY_NAMES.get(symbol, symbol)

        results.append({
            "symbol": symbol,
            "companyName": company_name,
            "trendRank": rank,
            "headlines": headlines,
            **price_data,
        })
        logger.debug(
            "Trending #%d: %s  1d=%.1f%%  3d=%.1f%%  volRatio=%.2f",
            rank, symbol,
            price_data["change1d"],
            price_data["change3d"],
            price_data["volumeRatio"],
        )

    logger.info("Built %d trending tickers for %s", len(results), trade_date)
    return results
