import sys
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_analysis import earnings


def test_normalize_timing_maps_yahoo_codes():
    rows = {}
    earnings._add_earnings_api_rows(rows, date(2026, 4, 27), [{"symbol": "AAPL"}], "Before Open")
    earnings._add_earnings_api_rows(rows, date(2026, 4, 27), [{"symbol": "MSFT"}], "After Close")
    earnings._add_earnings_api_rows(rows, date(2026, 4, 27), [{"symbol": "BK"}], "TBD")

    assert rows == {
        "AAPL": {"date": "2026-04-27", "timing": "Before Open"},
        "MSFT": {"date": "2026-04-27", "timing": "After Close"},
        "BK": {"date": "2026-04-27", "timing": "TBD"},
    }


def test_fetch_earnings_api_calendar_builds_symbol_timing_map(monkeypatch):
    def fake_day(day, api_key):
        if day == date(2026, 4, 27):
            return {
                "pre": [{"symbol": "MSFT"}],
                "after": [{"symbol": "AAPL"}],
                "notSupplied": [{"symbol": "BK"}],
            }
        return {"pre": [], "after": [], "notSupplied": []}

    monkeypatch.setenv("EARNINGS_API_KEY", "test-key")
    monkeypatch.setattr(earnings, "_api_key_cache", "")
    monkeypatch.setattr(earnings, "_fetch_earnings_api_day_cached", fake_day)

    result = earnings.fetch_earnings_api_calendar_dates({"2026-04-27", "2026-04-28"})

    assert result == {
        "AAPL": {"date": "2026-04-27", "timing": "After Close"},
        "MSFT": {"date": "2026-04-27", "timing": "Before Open"},
        "BK": {"date": "2026-04-27", "timing": "TBD"},
    }


def test_fetch_earnings_dates_uses_earnings_api_timing_when_dates_match(monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 4, 25)

    fake_yfinance = SimpleNamespace()
    fake_ticker = MagicMock()
    fake_ticker.calendar = {"Earnings Date": [datetime(2026, 4, 27, 0, 0)]}
    fake_yfinance.Ticker = MagicMock(return_value=fake_ticker)

    monkeypatch.setattr(earnings, "date", FixedDate)
    monkeypatch.setattr(
        earnings,
        "fetch_earnings_api_calendar_dates",
        lambda dates: {"AAPL": {"date": "2026-04-27", "timing": "After Close"}},
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    result = earnings.fetch_earnings_dates(["AAPL"], max_workers=1)

    assert result["AAPL"] == {"days": 2, "date": "2026-04-27", "timing": "After Close"}


def test_fetch_earnings_dates_run_date_overrides_today(monkeypatch):
    """run_date must be used as the reference instead of date.today() so that
    earnings_in_days is relative to the trading day, not the UTC wall clock
    (which is already +1 day after 5 PM PT when nightly workers execute)."""
    fake_yfinance = SimpleNamespace()
    fake_ticker = MagicMock()
    # Ticker reports on Tuesday April 28 — 1 day away from trading day April 27
    fake_ticker.calendar = {"Earnings Date": [datetime(2026, 4, 28, 0, 0)]}
    fake_yfinance.Ticker = MagicMock(return_value=fake_ticker)

    monkeypatch.setattr(
        earnings,
        "fetch_earnings_api_calendar_dates",
        lambda dates: {},
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    # Simulate worker running after midnight UTC (April 28) for trading day April 27
    result = earnings.fetch_earnings_dates(["AAPL"], run_date="2026-04-27", max_workers=1)

    # days should be 1 (relative to trading day April 27), not 0 (UTC wall clock April 28)
    assert result["AAPL"]["days"] == 1
    assert result["AAPL"]["date"] == "2026-04-28"


def test_fetch_earnings_dates_includes_past_week_days(monkeypatch):
    """days >= -7 so Monday earnings (days=-2) are captured on a Wednesday run."""
    fake_yfinance = SimpleNamespace()
    fake_ticker = MagicMock()
    # Company reported Monday April 27; run is Wednesday April 29 (days = -2)
    fake_ticker.calendar = {"Earnings Date": [datetime(2026, 4, 27, 0, 0)]}
    fake_yfinance.Ticker = MagicMock(return_value=fake_ticker)

    monkeypatch.setattr(earnings, "fetch_earnings_api_calendar_dates", lambda dates: {})
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    result = earnings.fetch_earnings_dates(["AAPL"], run_date="2026-04-29", max_workers=1)

    assert "AAPL" in result, "Past-week earnings (days=-2) should be captured"
    assert result["AAPL"]["days"] == -2
    assert result["AAPL"]["date"] == "2026-04-27"


def test_fetch_earnings_dates_only_fetches_timing_for_actual_earnings_dates(monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 4, 25)

    fake_yfinance = SimpleNamespace()

    def fake_ticker(symbol):
        fake = MagicMock()
        fake.calendar = {"Earnings Date": [datetime(2026, 4, 27, 0, 0)]}
        return fake

    requested_dates = []

    def fake_calendar(dates):
        requested_dates.extend(sorted(dates))
        return {}

    fake_yfinance.Ticker = MagicMock(side_effect=fake_ticker)
    monkeypatch.setattr(earnings, "date", FixedDate)
    monkeypatch.setattr(earnings, "fetch_earnings_api_calendar_dates", fake_calendar)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    earnings.fetch_earnings_dates(["AAPL", "MSFT"], max_workers=1)

    assert requested_dates == ["2026-04-27"]
