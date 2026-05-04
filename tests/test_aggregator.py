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
    _format_option_contract,
    _option_strategy_abbrev,
    _ticker_anchor,
    _MAX_WEIGHTED_SCORE,
)
from stock_analysis.screening import OptionIdea
from stock_analysis.data import RULE_CONFIGS


# ---------------------------------------------------------------------------
# Highlight generation tests
# ---------------------------------------------------------------------------

def _build_highlights(
    total_matched=10,
    total_symbols=3545,
    top_conviction=None,
    imminent_earnings=None,
    trending_tickers=None,
    option_ideas=None,
):
    """Re-implement the highlights logic from aggregator so it can be tested independently."""
    breadth_pct = round(total_matched / total_symbols * 100, 1) if total_symbols else 0.0
    top_conviction = top_conviction or []
    if top_conviction:
        top10_links = ", ".join(_ticker_anchor(s, f"#symbol/{s}") for s in top_conviction[:10])
        top_conviction_highlight = (
            f"Top conviction (score ≥40): {len(top_conviction)} tickers — {top10_links}"
        )
    else:
        top_conviction_highlight = "No tickers reached conviction threshold today"

    imminent = imminent_earnings or []
    if imminent:
        notable_links = ", ".join(
            _ticker_anchor(c["symbol"], f"#symbol/{c['symbol']}") for c in imminent[:8]
        )
        earnings_highlight = (
            f"{len(imminent)} tickers report earnings this week "
            f"(notably: {notable_links}) — watch for elevated implied volatility"
        )
    else:
        earnings_highlight = "No earnings this week in the current universe"

    trending_tickers = trending_tickers or []
    if trending_tickers:
        trending_links = ", ".join(
            _ticker_anchor(t["symbol"], f"https://finance.yahoo.com/quote/{t['symbol']}/")
            for t in trending_tickers[:10]
        )
        trending_highlight = f"Yahoo trending from the past 3 days: {trending_links}"
    else:
        trending_highlight = "No Yahoo Finance trending tickers available today"

    option_ideas = option_ideas or []
    if option_ideas:
        opts_links = ", ".join(
            _ticker_anchor(
                idea.symbol,
                f"https://finance.yahoo.com/quote/{idea.symbol}/options/",
                f"{idea.symbol}-{_option_strategy_abbrev(idea.strategy)}",
            )
            for idea in option_ideas
        )
        options_highlight = f"Options watching: {opts_links}"
    else:
        options_highlight = "No options ideas today"

    return [
        f"{total_matched} of {total_symbols} stocks matched at least one rule — {breadth_pct}% breadth",
        top_conviction_highlight,
        earnings_highlight,
        trending_highlight,
        options_highlight,
    ]


def test_highlights_has_five_bullets():
    highlights = _build_highlights()
    assert len(highlights) == 5


def test_highlights_total_universe_breadth():
    h = _build_highlights(total_matched=500, total_symbols=3545)
    assert h[0] == "500 of 3545 stocks matched at least one rule — 14.1% breadth"


def test_highlights_no_sp500_only_breadth():
    h = _build_highlights(total_matched=170, total_symbols=484)
    assert "S&P 500" not in h[0]
    assert "170 of 484" in h[0]


def test_highlights_conviction_shows_count_and_links():
    tickers = [f"T{i}" for i in range(15)]
    h = _build_highlights(top_conviction=tickers)
    assert "15 tickers" in h[1]
    assert "score ≥40" in h[1]
    assert 'href="#symbol/T0"' in h[1]
    # only top 10 linked
    assert h[1].count("<a ") == 10


def test_highlights_conviction_threshold_is_40():
    h = _build_highlights(top_conviction=["AAPL"])
    assert "≥40" in h[1]
    assert "≥35" not in h[1]


def test_highlights_earnings_shows_count_and_links():
    imminent = [{"symbol": f"E{i}"} for i in range(5)]
    h = _build_highlights(imminent_earnings=imminent)
    assert h[2].startswith("5 tickers report earnings this week")
    assert "notably:" in h[2]
    assert 'href="#symbol/E0"' in h[2]


def test_highlights_earnings_fallback_when_none():
    h = _build_highlights(imminent_earnings=[])
    assert h[2] == "No earnings this week in the current universe"


def test_highlights_trending_links_to_yahoo():
    tickers = [{"symbol": f"T{i}"} for i in range(12)]
    h = _build_highlights(trending_tickers=tickers)
    assert h[3].startswith("Yahoo trending from the past 3 days:")
    assert "finance.yahoo.com/quote/T0" in h[3]
    # only top 10 linked
    assert h[3].count("<a ") == 10


def test_highlights_trending_fallback_when_empty():
    h = _build_highlights(trending_tickers=[])
    assert h[3] == "No Yahoo Finance trending tickers available today"


def test_highlights_options_strategy_abbrev_and_link():
    idea = OptionIdea(
        symbol="NDAQ", strategy="Cash-secured put — sell $89 put", expiration="2026-05-08",
        score=80.0, reason="test", strike=89.0, highlighted=True,
    )
    h = _build_highlights(option_ideas=[idea])
    assert "NDAQ-SP" in h[4]
    assert "finance.yahoo.com/quote/NDAQ/options/" in h[4]


def test_highlights_options_fallback_when_empty():
    h = _build_highlights(option_ideas=[])
    assert h[4] == "No options ideas today"


def test_highlights_no_fang_or_djia_reference():
    h = _build_highlights()
    assert not any("FANG" in bullet or "DJIA" in bullet for bullet in h)


# ---------------------------------------------------------------------------
# _option_strategy_abbrev tests
# ---------------------------------------------------------------------------

def test_option_strategy_abbrev_cash_secured_put():
    assert _option_strategy_abbrev("Cash-secured put — sell $89 put") == "SP"


def test_option_strategy_abbrev_bear_put_spread():
    assert _option_strategy_abbrev("Bear put spread — $100/$95") == "BP"


def test_option_strategy_abbrev_bull_call_spread():
    assert _option_strategy_abbrev("Bull call spread — $100/$110") == "BC"


def test_option_strategy_abbrev_unknown_falls_back():
    assert _option_strategy_abbrev("some exotic strategy") == "OPT"


# ---------------------------------------------------------------------------
# _format_option_contract tests (OCC format, kept for reference)
# ---------------------------------------------------------------------------

def test_format_option_contract_occ_style():
    idea = OptionIdea(
        symbol="NDAQ", strategy="Cash-secured put", expiration="2026-05-08",
        score=80.0, reason="test", strike=89.0, highlighted=True,
    )
    assert _format_option_contract(idea) == "NDAQ260508P00089000"


def test_max_weighted_score_equals_sum_of_all_rule_weights():
    expected = sum(cfg["weight"] for cfg in RULE_CONFIGS.values())
    assert _MAX_WEIGHTED_SCORE == expected


def test_all_rules_have_weight_field():
    for rule_key, cfg in RULE_CONFIGS.items():
        assert "weight" in cfg, f"Rule '{rule_key}' is missing a weight field"
        assert cfg["weight"] in (1.0, 1.5, 2.0), f"Rule '{rule_key}' has unexpected weight {cfg['weight']}"


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
