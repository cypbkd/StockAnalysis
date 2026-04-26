"""
Earnings calendar fetching via yfinance.
Returns days until next earnings, the actual date, and timing (Before Open / After Close)
for each ticker in a list.
"""
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Dict, List, Set
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_EARNINGS_API_URL = "https://api.earningsapi.com/v1/calendar/earnings"
_EARNINGS_API_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockAnalysis/1.0)"}
_api_key_cache: str = ""


def fetch_earnings_dates(tickers: List[str], max_workers: int = 10) -> Dict[str, Dict]:
    """
    Return a dict mapping ticker → {"days": int, "date": "YYYY-MM-DD", "timing": str}.
    Tickers with no upcoming earnings data or errors are excluded from the result.
    """
    today = date.today()
    raw_results: Dict[str, Dict] = {}

    def _get_info(ticker: str) -> tuple:
        try:
            import yfinance as yf
            cal = yf.Ticker(ticker).calendar
            if not isinstance(cal, dict):
                return ticker, None
            earnings_dates = cal.get("Earnings Date")
            if not earnings_dates:
                return ticker, None
            for ts in earnings_dates:
                d = ts.date() if hasattr(ts, "date") else datetime.fromisoformat(str(ts)).date()
                days = (d - today).days
                if days >= -1:
                    return ticker, {"days": days, "date": d.isoformat(), "timing": _infer_timing(ts)}
            return ticker, None
        except Exception as exc:
            logger.debug("Earnings fetch failed for %s: %s", ticker, exc)
            return ticker, None

    logger.info("Fetching earnings dates for %d tickers", len(tickers))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_get_info, t): t for t in tickers}
        for future in as_completed(futures, timeout=60):
            try:
                ticker, info = future.result()
                if info is not None:
                    raw_results[ticker] = info
            except Exception:
                pass

    results = _enrich_earnings_timing(raw_results)
    logger.info("Earnings dates resolved: %d/%d tickers have upcoming dates", len(results), len(tickers))
    return results


def _enrich_earnings_timing(results: Dict[str, Dict]) -> Dict[str, Dict]:
    dates: Set[str] = {info["date"] for info in results.values() if info.get("date")}
    if not dates:
        return results

    timing_calendar = fetch_earnings_api_calendar_dates(dates)
    for ticker, info in results.items():
        timing_info = timing_calendar.get(ticker.upper())
        if timing_info and timing_info.get("date") == info.get("date"):
            info["timing"] = timing_info["timing"]
    return results


def fetch_earnings_api_calendar_dates(dates: Set[str]) -> Dict[str, Dict]:
    """Best-effort Earnings API lookup for only the dates yfinance returned."""
    api_key = _get_earnings_api_key()
    if not api_key:
        logger.info("EARNINGS_API_KEY/EARNINGS_API_SECRET_NAME not set — skipping timing enrichment")
        return {}

    results: Dict[str, Dict] = {}
    for iso_date in sorted(dates):
        day = date.fromisoformat(iso_date)
        payload = _fetch_earnings_api_day_cached(day, api_key)
        _add_earnings_api_rows(results, day, payload.get("pre", []), "Before Open")
        _add_earnings_api_rows(results, day, payload.get("after", []), "After Close")
        _add_earnings_api_rows(results, day, payload.get("notSupplied", []), "TBD")
    return results


def _get_earnings_api_key() -> str:
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache

    direct = os.environ.get("EARNINGS_API_KEY", "")
    if direct:
        _api_key_cache = direct
        return _api_key_cache

    secret_name = os.environ.get("EARNINGS_API_SECRET_NAME", "")
    if not secret_name:
        return ""

    try:
        import boto3
        sm = boto3.client("secretsmanager")
        resp = sm.get_secret_value(SecretId=secret_name)
        _api_key_cache = resp["SecretString"]
        return _api_key_cache
    except Exception as exc:
        logger.error("Failed to fetch Earnings API key from Secrets Manager (%s): %s", secret_name, exc)
        return ""


def _fetch_earnings_api_day(day: date, api_key: str) -> Dict:
    params = urllib.parse.urlencode({"date": day.isoformat(), "apikey": api_key})
    url = f"{_EARNINGS_API_URL}?{params}"
    try:
        req = urllib.request.Request(url, headers=_EARNINGS_API_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("Earnings API fetch failed for %s: %s", day.isoformat(), exc)
        return {}


def _fetch_earnings_api_day_cached(day: date, api_key: str) -> Dict:
    bucket = os.environ.get("CACHE_BUCKET", "")
    if not bucket:
        return _fetch_earnings_api_day(day, api_key)

    key = f"raw/earnings-api/date={day.isoformat()}/calendar.json"
    try:
        import boto3
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read())
    except Exception:
        payload = _fetch_earnings_api_day(day, api_key)
        if payload:
            try:
                s3.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=json.dumps(payload),
                    ContentType="application/json",
                )
            except Exception as exc:
                logger.debug("Failed to cache Earnings API response for %s: %s", day.isoformat(), exc)
        return payload


def _add_earnings_api_rows(results: Dict[str, Dict], day: date, rows: List[Dict], timing: str) -> None:
    for row in rows:
        ticker = str(row.get("symbol") or "").strip().upper()
        if ticker:
            results[ticker] = {"date": day.isoformat(), "timing": timing}


def _infer_timing(ts) -> str:
    """Guess before/after market from a yfinance timestamp's hour component.
    yfinance uses midnight UTC for date-only entries (unknown timing).
    Non-midnight hours can hint at AM/PM reporting windows.
    """
    try:
        hour = ts.hour if hasattr(ts, "hour") else datetime.fromisoformat(str(ts)).hour
        if hour == 0:
            return "TBD"
        # Roughly: ≤ 13 UTC ≈ morning ET → Before Open; > 13 UTC ≈ afternoon ET → After Close
        return "Before Open" if hour <= 13 else "After Close"
    except Exception:
        return "TBD"
