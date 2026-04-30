"""Unit tests for aggregator helper functions."""
import json
import sys
from datetime import date
from types import ModuleType
from unittest.mock import MagicMock

# boto3 is not installed in the local dev environment; stub it before importing aggregator
if "boto3" not in sys.modules:
    sys.modules["boto3"] = MagicMock()

from stock_analysis.handlers.aggregator import (
    _current_week_bounds,
    _supplement_earnings_from_api_cache,
)


def test_current_week_bounds_wednesday():
    monday, friday = _current_week_bounds(date(2026, 4, 29))  # Wednesday
    assert monday == date(2026, 4, 27)
    assert friday == date(2026, 5, 1)


def test_current_week_bounds_weekend_advances_to_next_week():
    monday, friday = _current_week_bounds(date(2026, 4, 25))  # Saturday
    assert monday == date(2026, 4, 27)
    assert friday == date(2026, 5, 1)


def _make_s3(cache: dict):
    """Fake S3 client that serves cache dict keyed by S3 object key."""
    s3 = MagicMock()

    def get_object(Bucket, Key):
        if Key in cache:
            body = MagicMock()
            body.read.return_value = json.dumps(cache[Key]).encode()
            return {"Body": body}
        raise Exception(f"NoSuchKey: {Key}")

    s3.get_object.side_effect = get_object
    return s3


def test_supplement_adds_universe_tickers_from_past_day_cache():
    """Tickers in the API cache for a past day that are in the universe should be added."""
    cache = {
        "raw/earnings-api/date=2026-04-27/calendar.json": {
            "pre": [{"symbol": "AAPL"}],
            "after": [{"symbol": "MSFT"}],
            "notSupplied": [],
        }
    }
    s3 = _make_s3(cache)
    universe = {"AAPL", "MSFT", "GOOGL"}
    metrics_map = {
        "AAPL": {"company_name": "Apple", "close": 170.0, "rsi_14": 55.0},
        "MSFT": {"company_name": "Microsoft", "close": 400.0, "rsi_14": 60.0},
    }

    today = date(2026, 4, 29)  # Wednesday; April 27 = Monday = past day
    result = _supplement_earnings_from_api_cache(
        s3, "bucket", date(2026, 4, 27), today, [], universe, metrics_map
    )

    symbols = {e["symbol"] for e in result}
    assert symbols == {"AAPL", "MSFT"}
    aapl = next(e for e in result if e["symbol"] == "AAPL")
    assert aapl["date"] == "2026-04-27"
    assert aapl["weekday"] == "Monday"
    assert aapl["timing"] == "Before Open"
    assert aapl["days"] == -2
    assert aapl["companyName"] == "Apple"
    assert aapl["close"] == 170.0


def test_supplement_skips_tickers_not_in_universe():
    cache = {
        "raw/earnings-api/date=2026-04-27/calendar.json": {
            "pre": [{"symbol": "XOM"}, {"symbol": "AAPL"}],
            "after": [],
            "notSupplied": [],
        }
    }
    s3 = _make_s3(cache)
    universe = {"AAPL"}  # XOM not in universe

    result = _supplement_earnings_from_api_cache(
        s3, "bucket", date(2026, 4, 27), date(2026, 4, 29), [], universe, {}
    )
    assert all(e["symbol"] == "AAPL" for e in result)


def test_supplement_skips_already_present_candidates():
    cache = {
        "raw/earnings-api/date=2026-04-27/calendar.json": {
            "pre": [{"symbol": "AAPL"}],
            "after": [],
            "notSupplied": [],
        }
    }
    s3 = _make_s3(cache)
    existing = [{"symbol": "AAPL", "date": "2026-04-27", "weekday": "Monday",
                 "timing": "TBD", "days": -2, "companyName": "Apple",
                 "close": 170.0, "rsi": 55.0}]

    result = _supplement_earnings_from_api_cache(
        s3, "bucket", date(2026, 4, 27), date(2026, 4, 29), existing, {"AAPL"}, {}
    )
    assert result == []  # AAPL already present, should not be duplicated


def test_supplement_handles_missing_cache_gracefully():
    s3 = _make_s3({})  # empty cache → all S3 gets raise
    result = _supplement_earnings_from_api_cache(
        s3, "bucket", date(2026, 4, 27), date(2026, 4, 29), [], {"AAPL"}, {}
    )
    assert result == []


def test_supplement_does_not_include_today_or_future():
    """Only past days (d < today) should be scanned."""
    cache = {
        "raw/earnings-api/date=2026-04-29/calendar.json": {
            "pre": [{"symbol": "AAPL"}],
            "after": [],
            "notSupplied": [],
        }
    }
    s3 = _make_s3(cache)
    today = date(2026, 4, 29)  # Wednesday

    result = _supplement_earnings_from_api_cache(
        s3, "bucket", date(2026, 4, 29), today, [], {"AAPL"}, {}
    )
    assert result == []  # today not scanned; only d < today
