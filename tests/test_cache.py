from datetime import date

from stock_analysis.cache import CacheAction, CacheRequest, S3CachePlanner


def test_symbol_snapshot_key_and_reuse_decision():
    planner = S3CachePlanner(bucket="stock-analysis-prod")
    request = CacheRequest(
        dataset="stocks",
        trading_date=date(2026, 4, 23),
        source="alpaca",
        symbols=("AAPL", "MSFT"),
    )

    assert planner.cache_key_for_symbol(request, "AAPL") == (
        "raw/stocks/date=2026-04-23/source=alpaca/symbol=AAPL.json"
    )

    decision = planner.plan(request, existing_keys={planner.cache_key_for_symbol(request, "AAPL"), planner.cache_key_for_symbol(request, "MSFT")})

    assert decision.action is CacheAction.REUSE
    assert decision.missing_keys == ()
    assert decision.existing_keys == (
        "raw/stocks/date=2026-04-23/source=alpaca/symbol=AAPL.json",
        "raw/stocks/date=2026-04-23/source=alpaca/symbol=MSFT.json",
    )


def test_symbol_snapshot_plans_incremental_fetch_for_missing_symbols():
    planner = S3CachePlanner(bucket="stock-analysis-prod")
    request = CacheRequest(
        dataset="options",
        trading_date=date(2026, 4, 23),
        source="alpaca",
        symbols=("AAPL", "MSFT", "NVDA"),
    )

    existing_keys = {
        planner.cache_key_for_symbol(request, "AAPL"),
        planner.cache_key_for_symbol(request, "NVDA"),
    }
    decision = planner.plan(request, existing_keys=existing_keys)

    assert decision.action is CacheAction.FETCH_MISSING
    assert decision.missing_keys == (
        "raw/options/date=2026-04-23/source=alpaca/symbol=MSFT.json",
    )
    assert decision.reason == "partial raw cache hit"


def test_calendar_snapshot_uses_single_key():
    planner = S3CachePlanner(bucket="stock-analysis-prod")
    request = CacheRequest(
        dataset="earnings",
        trading_date=date(2026, 4, 23),
        source="fmp",
    )

    assert planner.cache_key_for_request(request) == (
        "raw/earnings/date=2026-04-23/source=fmp/calendar.json"
    )

    decision = planner.plan(
        request,
        existing_keys={"raw/earnings/date=2026-04-23/source=fmp/calendar.json"},
    )

    assert decision.action is CacheAction.REUSE
    assert decision.missing_keys == ()
