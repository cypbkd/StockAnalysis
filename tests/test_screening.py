from datetime import date

from stock_analysis.rules import CanonicalRule
from stock_analysis.screening import (
    DeterministicScreeningEngine,
    MarketSnapshot,
    OptionIdea,
    ReportWatchlist,
    build_nightly_report,
)


def test_screening_engine_returns_deterministic_ranked_results():
    engine = DeterministicScreeningEngine()
    rule = CanonicalRule.from_mapping(
        {
            "logic": "and",
            "conditions": [
                {"field": "close", "op": ">", "value_from": "sma_20"},
                {"field": "rsi_14", "op": "<", "value": 70},
            ],
        }
    )

    results = engine.screen(
        [
            MarketSnapshot(symbol="NVDA", metrics={"close": 100, "sma_20": 90, "rsi_14": 75}),
            MarketSnapshot(symbol="AAPL", metrics={"close": 100, "sma_20": 95, "rsi_14": 60}),
            MarketSnapshot(symbol="MSFT", metrics={"close": 120, "sma_20": 100}),
        ],
        rule,
    )

    assert [result.symbol for result in results] == ["AAPL", "MSFT", "NVDA"]
    assert results[0].matched is True
    assert results[0].score == 1.0
    assert results[1].matched is False
    assert results[1].score == 0.5
    assert results[1].failed_conditions[0].reason == "missing field: rsi_14"


def test_build_nightly_report_matches_web_contract_shape():
    engine = DeterministicScreeningEngine()
    rule = CanonicalRule.from_mapping(
        {
            "logic": "and",
            "name": "Trend Quality",
            "source_text": "Find names above the 20DMA and with RSI under 70.",
            "conditions": [
                {"field": "close", "op": ">", "value_from": "sma_20"},
                {"field": "rsi_14", "op": "<", "value": 70},
            ],
        }
    )
    watchlist = ReportWatchlist(
        watchlist_id="fang",
        name="FANG Watch",
        symbols=("AAPL", "MSFT", "NVDA"),
        priority="high",
        rule_summary="Trend continuation with earnings awareness",
    )

    report = build_nightly_report(
        trade_date=date(2026, 4, 23),
        timezone="America/Los_Angeles",
        watchlists=[watchlist],
        stock_results=engine.screen(
            [
                MarketSnapshot(
                    symbol="NVDA",
                    metrics={
                        "company_name": "NVIDIA",
                        "watchlist_id": "fang",
                        "close": 100,
                        "sma_20": 95,
                        "rsi_14": 60,
                        "change_percent": 2.1,
                    },
                ),
                MarketSnapshot(
                    symbol="MSFT",
                    metrics={
                        "company_name": "Microsoft",
                        "watchlist_id": "fang",
                        "close": 90,
                        "sma_20": 95,
                        "rsi_14": 61,
                        "change_percent": -0.4,
                    },
                ),
            ],
            rule,
        ),
        option_ideas=[
            OptionIdea(
                symbol="AAPL",
                strategy="Bull put spread",
                expiration="2026-04-26",
                score=84,
                reason="Liquid weekly chain with manageable earnings risk",
            )
        ],
        earnings_watch=[
            {
                "symbol": "META",
                "companyName": "Meta Platforms",
                "when": "After close",
                "priority": "very high",
                "focus": "Revenue reaction and gap continuation",
            }
        ],
        active_rules=[rule],
        highlights=["Momentum leadership remains concentrated in mega-cap tech."],
        report_history=[
            {"label": "Apr 23", "date": "2026-04-23", "href": "/latest/", "isActive": True},
            {"label": "Apr 22", "date": "2026-04-22", "href": "/runs/2026-04-22/"},
        ],
        universe_name="SPY 500",
        news_summary="NVDA extended its rally above the 20-day moving average on continued AI demand.",
    )

    assert report["reportLabel"] == "Nightly Stock Analysis Report"
    assert report["reportDate"] == "2026-04-23"
    assert report["summary"]["totalSymbols"] == 3
    assert report["summary"]["matchedSignals"] == 1
    assert report["summary"]["optionsCandidates"] == 1
    assert report["summary"]["earningsWatchCount"] == 1
    assert report["reportHistory"][0]["isActive"] is True
    assert report["stockSignals"][0]["symbol"] == "NVDA"
    assert report["stockSignals"][0]["status"] == "matched"
    assert report["ruleSets"][0]["naturalLanguage"] == rule.source_text
    assert report["watchlists"][0]["symbols"] == 3
    assert report["newsSummary"] == "NVDA extended its rally above the 20-day moving average on continued AI demand."


def test_signal_includes_technical_data_for_on_demand_analysis():
    """technicalData is included in each signal so the analysis Lambda can use it."""
    engine = DeterministicScreeningEngine()
    rule = CanonicalRule.from_mapping({
        "logic": "and",
        "name": "Pivot Test",
        "conditions": [{"field": "close", "op": ">", "value_from": "sma_20"}],
    })
    report = build_nightly_report(
        trade_date=date(2026, 4, 26),
        timezone="America/Los_Angeles",
        watchlists=[],
        stock_results=engine.screen(
            [MarketSnapshot(
                symbol="AAPL",
                metrics={
                    "close": 200.0, "sma_20": 190.0, "change_percent": 1.0,
                    "volume_ratio": 1.8, "rsi_14": 62.0,
                    "ema_20": 192.0, "sma_50": 180.0,
                    "high_52w": 210.0, "low_52w": 140.0,
                    "pivot_r1": 205.0, "pivot_r2": 212.0,
                    "pivot_s1": 195.0, "pivot_s2": 188.0,
                    "earnings_date": "2026-05-01",
                    "earnings_in_days": 5,
                    "earnings_timing": "After Close",
                },
            )],
            rule,
        ),
        option_ideas=[],
        earnings_watch=[],
        active_rules=[rule],
        highlights=[],
    )
    signal = report["stockSignals"][0]
    td = signal["technicalData"]
    assert td["volumeRatio"] == 1.8
    assert td["rsi14"] == 62.0
    assert td["ema20"] == 192.0
    assert td["sma50"] == 180.0
    assert td["pivotR1"] == 205.0
    assert td["pivotS1"] == 195.0
    assert td["earningsDate"] == "2026-05-01"
    assert td["earningsInDays"] == 5
    assert td["earningsTiming"] == "After Close"


def test_signal_technical_data_omits_missing_fields():
    """technicalData only includes fields present in metrics (no None values)."""
    engine = DeterministicScreeningEngine()
    rule = CanonicalRule.from_mapping({
        "logic": "and",
        "name": "Simple",
        "conditions": [{"field": "close", "op": ">", "value_from": "sma_20"}],
    })
    report = build_nightly_report(
        trade_date=date(2026, 4, 26),
        timezone="America/Los_Angeles",
        watchlists=[],
        stock_results=engine.screen(
            [MarketSnapshot(symbol="XYZ", metrics={"close": 50.0, "sma_20": 45.0, "change_percent": 0.5})],
            rule,
        ),
        option_ideas=[],
        earnings_watch=[],
        active_rules=[rule],
        highlights=[],
    )
    td = report["stockSignals"][0]["technicalData"]
    assert "volumeRatio" not in td
    assert "earningsDate" not in td


def test_build_nightly_report_defaults_news_summary_to_empty_string():
    report = build_nightly_report(
        trade_date=date(2026, 4, 23),
        timezone="America/Los_Angeles",
        watchlists=[],
        stock_results=[],
        option_ideas=[],
        earnings_watch=[],
        active_rules=[],
        highlights=[],
    )
    assert report["newsSummary"] == ""
