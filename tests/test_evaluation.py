"""Unit tests for signal evaluation logic."""
import json
import sys
from datetime import date
from unittest.mock import MagicMock, patch

from stock_analysis.evaluation import (
    BULLISH_RULES,
    BEARISH_RULES,
    signal_direction,
    nth_trading_day_after,
    nth_trading_day_before,
    build_compliance_summary,
    evaluate_report_date,
    run_nightly_evaluation,
    backfill_evaluations,
)


# ---------------------------------------------------------------------------
# signal_direction
# ---------------------------------------------------------------------------

def test_signal_direction_bullish():
    assert signal_direction(["ma_stack", "golden_cross"]) == "bullish"


def test_signal_direction_bearish():
    assert signal_direction(["td_sell", "dead_cross"]) == "bearish"


def test_signal_direction_mixed():
    assert signal_direction(["ma_stack", "td_sell"]) == "mixed"


def test_signal_direction_single_bullish():
    assert signal_direction(["td_buy"]) == "bullish"


def test_signal_direction_single_bearish():
    assert signal_direction(["dead_cross"]) == "bearish"


def test_signal_direction_empty():
    # No rules → bullish count == bearish count (both 0) → mixed
    assert signal_direction([]) == "mixed"


def test_all_bullish_rules_classified():
    for rule in BULLISH_RULES:
        assert signal_direction([rule]) == "bullish", f"{rule} should be bullish"


def test_all_bearish_rules_classified():
    for rule in BEARISH_RULES:
        assert signal_direction([rule]) == "bearish", f"{rule} should be bearish"


# ---------------------------------------------------------------------------
# nth_trading_day_after / nth_trading_day_before
# ---------------------------------------------------------------------------

def test_nth_trading_day_after_skips_weekend():
    # 2026-05-07 is Thursday; +3 trading days = Tue 2026-05-12
    result = nth_trading_day_after("2026-05-07", 3)
    assert result == "2026-05-12"


def test_nth_trading_day_after_over_weekend():
    # 2026-05-08 Friday; +1 = Mon 2026-05-11
    result = nth_trading_day_after("2026-05-08", 1)
    assert result == "2026-05-11"


def test_nth_trading_day_before_skips_weekend():
    # 2026-05-12 Tuesday; -3 = Thu 2026-05-07
    result = nth_trading_day_before("2026-05-12", 3)
    assert result == "2026-05-07"


def test_nth_trading_day_before_over_weekend():
    # 2026-05-11 Monday; -1 = Fri 2026-05-08
    result = nth_trading_day_before("2026-05-11", 1)
    assert result == "2026-05-08"


def test_roundtrip_after_before():
    start = "2026-05-05"
    ahead = nth_trading_day_after(start, 3)
    back = nth_trading_day_before(ahead, 3)
    assert back == start


# ---------------------------------------------------------------------------
# build_compliance_summary
# ---------------------------------------------------------------------------

def _make_record(ticker, direction, win, ret3d, signal_date="2026-04-01"):
    return {
        "ticker": ticker,
        "direction": direction,
        "win": win,
        "return3d": ret3d,
        "signalDate": signal_date,
        "exitDate": "2026-04-04",
        "ruleKeys": [],
        "entryPrice": 100.0,
        "exitPrice": 100.0 + ret3d,
    }


def test_build_compliance_summary_basic():
    records = [
        _make_record("AAPL", "bullish", True, 2.0),
        _make_record("AAPL", "bullish", True, 1.5),
        _make_record("AAPL", "bullish", False, -0.5),
        _make_record("NVDA", "bullish", True, 3.0),
        _make_record("NVDA", "bullish", True, 2.5),
        _make_record("NVDA", "bullish", True, 4.0),
    ]
    summary = build_compliance_summary(records, min_signals=3)
    assert summary["lookbackDays"] == 90
    assert summary["minSignals"] == 3

    tickers = {t["ticker"]: t for t in summary["tickers"]}
    assert "AAPL" in tickers
    assert "NVDA" in tickers

    aapl = tickers["AAPL"]
    assert aapl["totalSignals"] == 3
    assert aapl["wins"] == 2
    assert abs(aapl["winRate"] - 0.667) < 0.01

    nvda = tickers["NVDA"]
    assert nvda["winRate"] == 1.0
    assert abs(nvda["avgReturn3d"] - 3.167) < 0.01


def test_build_compliance_summary_min_signals_filter():
    records = [
        _make_record("AAPL", "bullish", True, 2.0),
        _make_record("AAPL", "bullish", True, 1.5),
        # Only 2 records — below min_signals=3
    ]
    summary = build_compliance_summary(records, min_signals=3)
    assert summary["tickers"] == []


def test_build_compliance_summary_sorted_by_win_rate():
    records = (
        [_make_record("LOW", "bullish", False, -1.0)] * 3 +   # 0% win rate
        [_make_record("MID", "bullish", True, 1.0)] * 2 +
        [_make_record("MID", "bullish", False, -1.0)] * 1 +   # 67% win rate (3 total)
        [_make_record("TOP", "bullish", True, 2.0)] * 4 +     # 80% win rate
        [_make_record("TOP", "bullish", False, -1.0)] * 1
    )
    summary = build_compliance_summary(records, min_signals=3)
    names = [t["ticker"] for t in summary["tickers"]]
    assert names.index("TOP") < names.index("MID")
    assert names.index("MID") < names.index("LOW")


# ---------------------------------------------------------------------------
# evaluate_report_date
# ---------------------------------------------------------------------------

def _make_s3_with_report(signals):
    """Return a mock s3 client that serves a fake report JSON."""
    report = {
        "reportDate": "2026-04-01",
        "stockSignals": signals,
    }
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": MagicMock(read=lambda: json.dumps(report).encode())}
    return s3


def test_evaluate_report_date_bullish_win():
    signals = [
        {"symbol": "AAPL", "ruleKeys": ["ma_stack"], "lastPrice": 100.0, "ruleNames": []},
    ]
    s3 = _make_s3_with_report(signals)

    with patch("stock_analysis.evaluation._fetch_prices_batch", return_value={"AAPL": 103.0}):
        records = evaluate_report_date(s3, "test-bucket", "2026-04-01", "2026-04-04")

    assert len(records) == 1
    rec = records[0]
    assert rec["ticker"] == "AAPL"
    assert rec["direction"] == "bullish"
    assert rec["win"] is True
    assert abs(rec["return3d"] - 3.0) < 0.01


def test_evaluate_report_date_bearish_win():
    signals = [
        {"symbol": "XYZ", "ruleKeys": ["td_sell"], "lastPrice": 50.0, "ruleNames": []},
    ]
    s3 = _make_s3_with_report(signals)

    with patch("stock_analysis.evaluation._fetch_prices_batch", return_value={"XYZ": 47.0}):
        records = evaluate_report_date(s3, "test-bucket", "2026-04-01", "2026-04-04")

    assert len(records) == 1
    assert records[0]["win"] is True
    assert records[0]["return3d"] < 0


def test_evaluate_report_date_mixed_skipped():
    signals = [
        # Both bullish and bearish — net 0 → mixed → excluded
        {"symbol": "MIXED", "ruleKeys": ["ma_stack", "td_sell"], "lastPrice": 100.0, "ruleNames": []},
    ]
    s3 = _make_s3_with_report(signals)

    with patch("stock_analysis.evaluation._fetch_prices_batch", return_value={"MIXED": 102.0}):
        records = evaluate_report_date(s3, "test-bucket", "2026-04-01", "2026-04-04")

    assert records == []


def test_evaluate_report_date_missing_exit_price_excluded():
    signals = [
        {"symbol": "AAPL", "ruleKeys": ["ma_stack"], "lastPrice": 100.0, "ruleNames": []},
    ]
    s3 = _make_s3_with_report(signals)

    # yfinance returned no price for AAPL
    with patch("stock_analysis.evaluation._fetch_prices_batch", return_value={}):
        records = evaluate_report_date(s3, "test-bucket", "2026-04-01", "2026-04-04")

    assert records == []


def test_evaluate_report_date_falls_back_to_rule_names():
    """Old reports without ruleKeys should fall back to ruleNames mapping."""
    signals = [
        {
            "symbol": "AAPL",
            "ruleKeys": [],
            "ruleNames": ["Bullish MA Stack"],
            "lastPrice": 100.0,
        },
    ]
    s3 = _make_s3_with_report(signals)

    with patch("stock_analysis.evaluation._fetch_prices_batch", return_value={"AAPL": 101.0}):
        records = evaluate_report_date(s3, "test-bucket", "2026-04-01", "2026-04-04")

    assert len(records) == 1
    assert records[0]["direction"] == "bullish"


def test_evaluate_report_date_no_report():
    s3 = MagicMock()
    s3.get_object.side_effect = Exception("NoSuchKey")

    records = evaluate_report_date(s3, "test-bucket", "2026-04-01", "2026-04-04")
    assert records == []


# ---------------------------------------------------------------------------
# run_nightly_evaluation
# ---------------------------------------------------------------------------

def test_run_nightly_evaluation_writes_eval_and_summary():
    signal_date = nth_trading_day_before("2026-05-10", 3)
    report = {
        "reportDate": signal_date,
        "stockSignals": [
            {"symbol": "AAPL", "ruleKeys": ["ma_stack"], "lastPrice": 100.0, "ruleNames": []},
            {"symbol": "AAPL", "ruleKeys": ["ma_stack"], "lastPrice": 100.0, "ruleNames": []},
            {"symbol": "AAPL", "ruleKeys": ["ma_stack"], "lastPrice": 100.0, "ruleNames": []},
        ],
    }
    eval_records = [
        {"ticker": "AAPL", "direction": "bullish", "win": True, "return3d": 2.0,
         "signalDate": signal_date, "exitDate": "2026-05-10",
         "ruleKeys": ["ma_stack"], "entryPrice": 100.0, "exitPrice": 102.0},
        {"ticker": "AAPL", "direction": "bullish", "win": True, "return3d": 1.5,
         "signalDate": signal_date, "exitDate": "2026-05-10",
         "ruleKeys": ["ma_stack"], "entryPrice": 100.0, "exitPrice": 101.5},
        {"ticker": "AAPL", "direction": "bullish", "win": False, "return3d": -0.5,
         "signalDate": signal_date, "exitDate": "2026-05-10",
         "ruleKeys": ["ma_stack"], "entryPrice": 100.0, "exitPrice": 99.5},
    ]

    s3 = MagicMock()
    # head_object raises to indicate the eval file doesn't exist yet
    s3.head_object.side_effect = Exception("NoSuchKey")
    s3.get_object.side_effect = [
        # First call: report for signal_date
        {"Body": MagicMock(read=lambda: json.dumps(report).encode())},
        # Subsequent calls: no eval files in the 90-day window
        *[Exception("NoSuchKey")] * 90,
    ]

    with patch("stock_analysis.evaluation._fetch_prices_batch", return_value={"AAPL": 102.0}):
        with patch("stock_analysis.evaluation.load_eval_files", return_value=eval_records):
            result = run_nightly_evaluation(s3, "test-bucket", "2026-05-10")

    assert result is not None
    assert "tickers" in result
    # Summary file written
    put_keys = [call[1]["Key"] for call in s3.put_object.call_args_list]
    assert any("evaluations/" in k and k.endswith(".json") for k in put_keys)
    assert any(k == "evaluations/compliance-summary.json" for k in put_keys)


def test_run_nightly_evaluation_skips_already_evaluated():
    s3 = MagicMock()
    # head_object succeeds → already evaluated
    s3.head_object.return_value = {}

    with patch("stock_analysis.evaluation.load_eval_files", return_value=[]):
        result = run_nightly_evaluation(s3, "test-bucket", "2026-05-10")

    # No new eval file written (put_object only called for summary if records exist)
    put_keys = [call[1].get("Key", "") for call in s3.put_object.call_args_list]
    # The daily eval file should NOT be in put_keys
    signal_date = nth_trading_day_before("2026-05-10", 3)
    assert f"evaluations/{signal_date}.json" not in put_keys


# ---------------------------------------------------------------------------
# backfill_evaluations
# ---------------------------------------------------------------------------

def test_backfill_skips_future_exit_dates():
    s3 = MagicMock()
    s3.head_object.side_effect = Exception("NoSuchKey")

    # Use a future from_date so exit_date would be in the future
    future_date = "2099-01-01"
    count = backfill_evaluations(s3, "test-bucket", future_date, future_date)
    assert count == 0
    s3.put_object.assert_not_called()


def test_backfill_skips_already_evaluated():
    s3 = MagicMock()
    s3.head_object.return_value = {}  # All dates already evaluated

    count = backfill_evaluations(s3, "test-bucket", "2026-04-01", "2026-04-03")
    assert count == 0
