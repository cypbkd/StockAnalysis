"""
Tests for stock_analysis.options — real options chain analysis.
"""
import math
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from stock_analysis.options import (
    _pick_expiration,
    _nearest_strike,
    _safe_float,
    _safe_int,
    _options_quality_score,
    _composite_score,
    build_options_ideas,
)


# ---------------------------------------------------------------------------
# Helpers shared by multiple tests
# ---------------------------------------------------------------------------

def _make_puts(strikes, base_iv=0.35, base_oi=500, base_bid=2.0, base_ask=2.2):
    rows = [
        {
            "strike": float(s),
            "bid": base_bid,
            "ask": base_ask,
            "impliedVolatility": base_iv,
            "openInterest": base_oi,
            "volume": 200,
            "inTheMoney": False,
        }
        for s in strikes
    ]
    return pd.DataFrame(rows)


def _fake_ticker(expirations, puts_df):
    chain = SimpleNamespace(calls=pd.DataFrame(), puts=puts_df)
    ticker = MagicMock()
    ticker.options = expirations
    ticker.option_chain.return_value = chain
    return ticker


def _matched_result(symbol, close=150.0, change_pct=1.0, rsi=55.0, sma_20=145.0,
                    score=0.8, match_count=5):
    return {
        "symbol": symbol,
        "score": score,
        "match_count": match_count,
        "metrics": {
            "close": close,
            "change_percent": change_pct,
            "rsi_14": rsi,
            "sma_20": sma_20,
        },
    }


def _inject_yf(ticker_obj):
    """Inject a mock yfinance module and return cleanup callable."""
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = ticker_obj
    orig = sys.modules.get("yfinance")
    sys.modules["yfinance"] = fake_yf

    def cleanup():
        if orig is not None:
            sys.modules["yfinance"] = orig
        else:
            sys.modules.pop("yfinance", None)

    return cleanup


@pytest.fixture()
def exp_21dte():
    from datetime import datetime, timedelta
    return (datetime.now().date() + timedelta(days=21)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Unit tests — pure helpers
# ---------------------------------------------------------------------------

def test_pick_expiration_chooses_nearest_to_21dte():
    from datetime import datetime, timedelta
    today = datetime.now().date()
    exp_20 = (today + timedelta(days=20)).strftime("%Y-%m-%d")
    exp_45 = (today + timedelta(days=45)).strftime("%Y-%m-%d")
    exp_3 = (today + timedelta(days=3)).strftime("%Y-%m-%d")

    result = _pick_expiration((exp_3, exp_20, exp_45))
    assert result == exp_20


def test_pick_expiration_skips_too_close():
    from datetime import datetime, timedelta
    today = datetime.now().date()
    exp_5 = (today + timedelta(days=5)).strftime("%Y-%m-%d")
    exp_6 = (today + timedelta(days=6)).strftime("%Y-%m-%d")
    assert _pick_expiration((exp_5, exp_6)) is None


def test_pick_expiration_returns_none_for_empty():
    assert _pick_expiration(()) is None


def test_nearest_strike_returns_closest():
    df = pd.DataFrame({"strike": [100.0, 105.0, 110.0, 115.0]})
    assert _nearest_strike(df, 107.0) == 105.0
    assert _nearest_strike(df, 112.0) == 110.0


def test_nearest_strike_empty_df():
    assert _nearest_strike(pd.DataFrame({"strike": []}), 100.0) is None


def test_safe_float_handles_nan():
    assert _safe_float(float("nan")) == 0.0
    assert _safe_float(None) == 0.0
    assert _safe_float("bad") == 0.0
    assert _safe_float(1.5) == 1.5


def test_safe_int_handles_nan():
    assert _safe_int(float("nan")) == 0
    assert _safe_int(None) == 0
    assert _safe_int(42.9) == 42


def test_options_quality_score_iv_sweet_spot():
    # IV in sweet spot 25-65%: should earn full 25 IV points
    score_sweet = _options_quality_score(45, 1000, 55, True, 100, 95, 5)
    score_low_iv = _options_quality_score(10, 1000, 55, True, 100, 95, 5)
    assert score_sweet > score_low_iv


def test_options_quality_score_oi_liquidity():
    # Higher OI should score higher
    score_high_oi = _options_quality_score(40, 5000, 55, True, 100, 95, 5)
    score_low_oi = _options_quality_score(40, 50, 55, True, 100, 95, 5)
    assert score_high_oi > score_low_oi


def test_options_quality_score_rsi_alignment_bullish():
    # RSI 40-65 should score highest for bullish
    score_aligned = _options_quality_score(40, 500, 55, True, 100, 95, 5)
    score_overbought = _options_quality_score(40, 500, 80, True, 100, 95, 5)
    assert score_aligned > score_overbought


def test_options_quality_score_caps_at_100():
    score = _options_quality_score(40, 9999, 55, True, 100, 90, 6)
    assert score <= 100


def test_composite_score_blends_options_and_screening():
    # High match_count should boost composite above options_score alone
    comp_high = _composite_score(70, 14)  # full screening strength
    comp_low = _composite_score(70, 1)   # weak screening
    assert comp_high > comp_low
    assert comp_high <= 100


# ---------------------------------------------------------------------------
# Unit tests — build_options_ideas with mocked yfinance
# ---------------------------------------------------------------------------

def test_build_options_ideas_bullish_cash_secured_put(exp_21dte):
    strikes = [130.0, 135.0, 140.0, 145.0, 150.0, 155.0, 160.0]
    ticker = _fake_ticker((exp_21dte,), _make_puts(strikes))

    cleanup = _inject_yf(ticker)
    import stock_analysis.options as opts
    try:
        results = opts.build_options_ideas([_matched_result("AAPL", change_pct=1.5)], max_ideas=5)
    finally:
        cleanup()

    assert len(results) == 1
    idea = results[0]
    assert idea.symbol == "AAPL"
    assert "put" in idea.strategy.lower()
    assert exp_21dte in idea.expiration
    assert "OI" in idea.reason
    assert idea.score > 0


def test_build_options_ideas_bearish_bear_put_spread(exp_21dte):
    strikes = [130.0, 135.0, 140.0, 145.0, 150.0, 155.0, 160.0]
    ticker = _fake_ticker((exp_21dte,), _make_puts(strikes, base_bid=3.0, base_ask=3.2))

    cleanup = _inject_yf(ticker)
    import stock_analysis.options as opts
    try:
        results = opts.build_options_ideas([_matched_result("NVDA", change_pct=-2.0)], max_ideas=5)
    finally:
        cleanup()

    assert len(results) == 1
    idea = results[0]
    assert idea.symbol == "NVDA"
    assert "put" in idea.strategy.lower()


def test_build_options_ideas_all_tickers_are_candidates(exp_21dte):
    """Any matched ticker should be a candidate — no fixed liquid filter."""
    strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
    ticker = _fake_ticker((exp_21dte,), _make_puts(strikes))

    cleanup = _inject_yf(ticker)
    import stock_analysis.options as opts
    try:
        # XYZ is not in any hardcoded universe — should still be attempted
        results = opts.build_options_ideas(
            [_matched_result("XYZ", close=100.0, change_pct=0.5)], max_ideas=5
        )
    finally:
        cleanup()

    assert len(results) == 1
    assert results[0].symbol == "XYZ"


def test_build_options_ideas_top_3_get_highlighted(exp_21dte):
    strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
    ticker = _fake_ticker((exp_21dte,), _make_puts(strikes))

    cleanup = _inject_yf(ticker)
    import stock_analysis.options as opts
    try:
        matched = [
            _matched_result("AAPL", close=100.0, match_count=8),
            _matched_result("NVDA", close=100.0, match_count=7),
            _matched_result("META", close=100.0, match_count=6),
            _matched_result("TSLA", close=100.0, match_count=5),
            _matched_result("MSFT", close=100.0, match_count=4),
        ]
        results = opts.build_options_ideas(matched, max_ideas=10)
    finally:
        cleanup()

    highlighted = [r for r in results if r.highlighted]
    non_highlighted = [r for r in results if not r.highlighted]
    assert len(highlighted) == 3
    assert len(non_highlighted) == 2


def test_build_options_ideas_fewer_than_3_all_get_highlighted(exp_21dte):
    """When fewer than 3 ideas are generated all of them should be highlighted."""
    strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
    ticker = _fake_ticker((exp_21dte,), _make_puts(strikes))

    cleanup = _inject_yf(ticker)
    import stock_analysis.options as opts
    try:
        matched = [
            _matched_result("AAPL", close=100.0, match_count=8),
            _matched_result("NVDA", close=100.0, match_count=7),
        ]
        results = opts.build_options_ideas(matched, max_ideas=10)
    finally:
        cleanup()

    assert all(r.highlighted for r in results)


def test_build_options_ideas_respects_max_ideas(exp_21dte):
    strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
    ticker = _fake_ticker((exp_21dte,), _make_puts(strikes))

    cleanup = _inject_yf(ticker)
    import stock_analysis.options as opts
    try:
        matched = [
            _matched_result(sym, close=100.0)
            for sym in ["AAPL", "NVDA", "META", "TSLA", "MSFT", "AMZN"]
        ]
        results = opts.build_options_ideas(matched, max_ideas=3)
    finally:
        cleanup()

    assert len(results) <= 3


def test_build_options_ideas_handles_yfinance_error():
    fake_yf = MagicMock()
    fake_yf.Ticker.side_effect = RuntimeError("network error")

    cleanup = _inject_yf(MagicMock())
    # Override with error-raising mock
    fake_yf2 = MagicMock()
    fake_yf2.Ticker.side_effect = RuntimeError("network error")
    sys.modules["yfinance"] = fake_yf2

    import stock_analysis.options as opts
    try:
        results = opts.build_options_ideas([_matched_result("AAPL")], max_ideas=5)
    finally:
        cleanup()

    assert results == []


def test_build_options_ideas_max_candidates_limits_api_calls(exp_21dte):
    """max_candidates should cap how many tickers we attempt."""
    strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
    ticker = _fake_ticker((exp_21dte,), _make_puts(strikes))

    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = ticker
    orig = sys.modules.get("yfinance")
    sys.modules["yfinance"] = fake_yf

    import stock_analysis.options as opts
    try:
        matched = [_matched_result(f"SYM{i}", close=100.0) for i in range(20)]
        opts.build_options_ideas(matched, max_candidates=5, max_ideas=10)
    finally:
        if orig is not None:
            sys.modules["yfinance"] = orig
        else:
            sys.modules.pop("yfinance", None)

    assert fake_yf.Ticker.call_count <= 5


# ---------------------------------------------------------------------------
# Integration test — live yfinance call (skipped in CI without network)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_build_options_ideas_live_aapl():
    """
    Live integration test: fetches real AAPL options chain from yfinance.
    Requires internet access. Run with: pytest -m integration tests/test_options.py
    """
    matched = [_matched_result("AAPL", close=200.0, change_pct=0.5, match_count=6)]
    results = build_options_ideas(matched, max_ideas=1)

    assert isinstance(results, list)
    if results:
        idea = results[0]
        assert idea.symbol == "AAPL"
        assert idea.expiration != ""
        assert "$" in idea.reason
        assert idea.score > 0
        assert idea.highlighted is True  # only 1 idea, so it's in the top 3
        print(f"\nLive AAPL option idea: {idea.strategy}")
        print(f"  {idea.reason}")
