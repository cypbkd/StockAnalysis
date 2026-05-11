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
    _dedup_records,
    _compute_market_breadth,
    build_compliance_summary,
    build_ticker_detail,
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
# _dedup_records
# ---------------------------------------------------------------------------

def test_dedup_records_removes_same_exit_date():
    records = [
        _make_record("FFIV", "bullish", True, 8.24, "2026-04-24"),
        _make_record("FFIV", "bullish", True, 8.24, "2026-04-25"),  # same exitDate → dup
        _make_record("FFIV", "bullish", True, 8.24, "2026-04-26"),  # same exitDate → dup
    ]
    # All three have exitDate derived from entryPrice+ret3d — force same exitDate manually
    for r in records:
        r["exitDate"] = "2026-04-29"
    deduped = _dedup_records(records)
    assert len(deduped) == 1
    # Keeps the latest signalDate
    assert deduped[0]["signalDate"] == "2026-04-26"


def test_dedup_records_keeps_different_exit_dates():
    r1 = _make_record("AAPL", "bullish", True, 2.0, "2026-04-24")
    r1["exitDate"] = "2026-04-29"
    r2 = _make_record("AAPL", "bullish", True, 1.5, "2026-04-27")
    r2["exitDate"] = "2026-04-30"
    deduped = _dedup_records([r1, r2])
    assert len(deduped) == 2


def test_dedup_records_different_tickers_same_exit_date_kept():
    r1 = _make_record("AAPL", "bullish", True, 2.0, "2026-04-24")
    r2 = _make_record("MSFT", "bullish", True, 1.5, "2026-04-24")
    for r in [r1, r2]:
        r["exitDate"] = "2026-04-29"
    deduped = _dedup_records([r1, r2])
    assert len(deduped) == 2  # different tickers → both kept


# ---------------------------------------------------------------------------
# _compute_market_breadth
# ---------------------------------------------------------------------------

def test_compute_market_breadth_basic():
    records = [
        {**_make_record("A", "bullish", True, 1.0), "exitDate": "2026-04-29"},
        {**_make_record("B", "bullish", True, 2.0), "exitDate": "2026-04-29"},
        {**_make_record("C", "bullish", False, -1.0), "exitDate": "2026-04-29"},
        {**_make_record("D", "bullish", True, 3.0), "exitDate": "2026-04-30"},
    ]
    breadth = _compute_market_breadth(records)
    assert abs(breadth["2026-04-29"] - 2/3) < 0.01
    assert breadth["2026-04-30"] == 1.0


# ---------------------------------------------------------------------------
# build_compliance_summary (with dedup)
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


def test_build_compliance_summary_deduplicates_same_exit_date():
    # Three signal dates all exiting on the same day → should count as 1
    records = [
        _make_record("FFIV", "bullish", True, 8.24, "2026-04-24"),
        _make_record("FFIV", "bullish", True, 8.24, "2026-04-25"),
        _make_record("FFIV", "bullish", True, 8.24, "2026-04-26"),
    ]
    for r in records:
        r["exitDate"] = "2026-04-29"
    # Add 2 more distinct signals so min_signals=3 is met
    r2 = _make_record("FFIV", "bullish", True, 4.0, "2026-04-28")
    r2["exitDate"] = "2026-05-01"
    r3 = _make_record("FFIV", "bullish", True, 3.0, "2026-05-01")
    r3["exitDate"] = "2026-05-06"
    all_records = records + [r2, r3]

    summary = build_compliance_summary(all_records, min_signals=3)
    tickers = {t["ticker"]: t for t in summary["tickers"]}
    # After dedup: Apr 29 (×1) + May 1 + May 6 = 3 unique observations
    assert tickers["FFIV"]["totalSignals"] == 3


def test_build_compliance_summary_basic():
    records = [
        _make_record("AAPL", "bullish", True, 2.0),
        _make_record("AAPL", "bullish", True, 1.5),
        _make_record("AAPL", "bullish", False, -0.5),
        _make_record("NVDA", "bullish", True, 3.0),
        _make_record("NVDA", "bullish", True, 2.5),
        _make_record("NVDA", "bullish", True, 4.0),
    ]
    # Give each record a unique exitDate so dedup doesn't collapse them
    for i, r in enumerate(records):
        r["exitDate"] = f"2026-04-{20 + i:02d}"
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
    for i, r in enumerate(records):
        r["exitDate"] = f"2026-04-{20 + i:02d}"
    summary = build_compliance_summary(records, min_signals=3)
    assert summary["tickers"] == []


def test_build_compliance_summary_sorted_by_win_rate():
    # Use list comprehensions (not * N) so each dict is a fresh object
    base = (
        [_make_record("LOW", "bullish", False, -1.0) for _ in range(3)] +
        [_make_record("MID", "bullish", True,  1.0) for _ in range(2)] +
        [_make_record("MID", "bullish", False, -1.0) for _ in range(1)] +
        [_make_record("TOP", "bullish", True,  2.0) for _ in range(4)] +
        [_make_record("TOP", "bullish", False, -1.0) for _ in range(1)]
    )
    for i, r in enumerate(base):
        r["exitDate"] = f"2026-04-{10 + i:02d}"
    summary = build_compliance_summary(base, min_signals=3)
    names = [t["ticker"] for t in summary["tickers"]]
    assert names.index("TOP") < names.index("MID")
    assert names.index("MID") < names.index("LOW")


# ---------------------------------------------------------------------------
# build_ticker_detail
# ---------------------------------------------------------------------------

def test_build_ticker_detail_dominant_rule_and_earnings():
    recs = [
        {**_make_record("FFIV", "bullish", True, 8.24, "2026-04-24"),
         "exitDate": "2026-04-29", "ruleKeys": ["ma_stack"]},
        {**_make_record("FFIV", "bullish", True, 5.29, "2026-05-01"),
         "exitDate": "2026-05-06", "ruleKeys": ["ma_stack", "pre_earnings_momentum"]},
        {**_make_record("FFIV", "bullish", True, 7.30, "2026-05-05"),
         "exitDate": "2026-05-08", "ruleKeys": ["ma_stack", "pre_earnings_momentum"]},
    ]
    breadth = {"2026-04-29": 0.72, "2026-05-06": 0.58, "2026-05-08": 0.65}
    detail = build_ticker_detail("FFIV", recs, breadth)

    assert detail["ticker"] == "FFIV"
    assert detail["totalSignals"] == 3
    assert detail["wins"] == 3
    assert detail["dominantRule"] == "ma_stack"
    assert detail["dominantRuleDisplay"] == "MA Stack"
    assert detail["earningsSignals"] == 2

    # ma_stack should be first in rule breakdown (appears 3 times)
    assert detail["ruleBreakdown"][0]["ruleKey"] == "ma_stack"
    assert detail["ruleBreakdown"][0]["count"] == 3

    # Signals have marketBreadth populated
    assert detail["signals"][0]["marketBreadth"] == 0.72
    assert detail["signals"][0]["hasEarnings"] is False
    assert detail["signals"][1]["hasEarnings"] is True

    # ruleDisplays populated
    assert "MA Stack" in detail["signals"][0]["ruleDisplays"]


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
    # 2026-05-09 is a Friday (weekday=4) — normal weekday path
    run_date = "2026-05-09"
    signal_date = nth_trading_day_before(run_date, 3)
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
         "signalDate": signal_date, "exitDate": run_date,
         "ruleKeys": ["ma_stack"], "entryPrice": 100.0, "exitPrice": 102.0},
        {"ticker": "AAPL", "direction": "bullish", "win": True, "return3d": 1.5,
         "signalDate": signal_date, "exitDate": run_date,
         "ruleKeys": ["ma_stack"], "entryPrice": 100.0, "exitPrice": 101.5},
        {"ticker": "AAPL", "direction": "bullish", "win": False, "return3d": -0.5,
         "signalDate": signal_date, "exitDate": run_date,
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
            result = run_nightly_evaluation(s3, "test-bucket", run_date)

    assert result is not None
    assert "tickers" in result
    # Both the daily eval file and the summary file should be written
    put_keys = [call[1]["Key"] for call in s3.put_object.call_args_list]
    assert any("evaluations/" in k and k.endswith(".json") for k in put_keys)
    assert any(k == "evaluations/compliance-summary.json" for k in put_keys)


def test_run_nightly_evaluation_weekend_skips_price_fetch_and_writes_empty_file():
    """Weekend run_date must write an empty eval file without calling yfinance."""
    # 2026-05-11 is a Sunday (weekday=6)
    run_date = "2026-05-11"
    signal_date = nth_trading_day_before(run_date, 3)

    s3 = MagicMock()
    s3.head_object.side_effect = Exception("NoSuchKey")  # eval file doesn't exist yet

    with patch("stock_analysis.evaluation._fetch_prices_batch") as mock_fetch:
        with patch("stock_analysis.evaluation.load_eval_files", return_value=[]):
            run_nightly_evaluation(s3, "test-bucket", run_date)

    # yfinance must NOT be called on weekends
    mock_fetch.assert_not_called()

    # Empty eval file must be written so future runs see already_done=True
    put_keys = [call[1]["Key"] for call in s3.put_object.call_args_list]
    assert f"evaluations/{signal_date}.json" in put_keys
    eval_body = next(
        call[1]["Body"]
        for call in s3.put_object.call_args_list
        if call[1]["Key"] == f"evaluations/{signal_date}.json"
    )
    assert json.loads(eval_body) == []


def test_run_nightly_evaluation_skips_already_evaluated():
    s3 = MagicMock()
    # head_object succeeds → already evaluated
    s3.head_object.return_value = {}

    with patch("stock_analysis.evaluation.load_eval_files", return_value=[]):
        result = run_nightly_evaluation(s3, "test-bucket", "2026-05-09")

    # No new eval file written (already_done=True skips the write block)
    put_keys = [call[1].get("Key", "") for call in s3.put_object.call_args_list]
    signal_date = nth_trading_day_before("2026-05-09", 3)
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
