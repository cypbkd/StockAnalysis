"""
Aggregator Lambda handler.

Triggered by EventBridge ~25 minutes after the coordinator so all worker
chunks have time to finish. Reads every chunk JSON from S3, combines the
screening results, builds the final nightly report, and writes it to:

  reports/latest/report.json          (what the website loads)
  reports/runs/{run_date}/report.json  (historical archive)
"""
import json
import logging
import os
from collections import namedtuple
from datetime import date, datetime, timedelta

_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
from typing import Any, Dict, List

import boto3

from stock_analysis.data import RULE_CONFIGS
from stock_analysis.news import generate_news_summary
from stock_analysis.rules import CanonicalRule
from stock_analysis.screening import build_nightly_report, OptionIdea, ReportWatchlist

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_Condition = namedtuple("_Condition", ["reason"])


class _SignalProxy:
    """Duck-type ScreeningResult so aggregated chunk dicts work with build_nightly_report."""
    __slots__ = ("symbol", "matched", "score", "metrics", "matched_conditions")

    def __init__(self, d: Dict[str, Any]) -> None:
        self.symbol = d["symbol"]
        self.matched = True
        self.score = d["score"]
        self.metrics = {
            **d["metrics"],
            "rule_names": d.get("rule_names", []),
            "match_count": d.get("match_count", 1),
            "watchlists": d.get("watchlists", []),
        }
        self.matched_conditions = [_Condition(r) for r in d["reasons"]]


def handler(event: dict, context: object) -> dict:
    s3 = boto3.client("s3")
    bucket = os.environ["CACHE_BUCKET"]
    run_date = event.get("run_date", date.today().isoformat())

    logger.info("Aggregating chunks for run_date=%s", run_date)

    # 1. Read run manifest (written by coordinator)
    manifest = _read_manifest(s3, bucket, run_date)
    manifest_watchlists = manifest.get("watchlists", {}) if manifest else {}

    # 2. List all chunk files
    paginator = s3.get_paginator("list_objects_v2")
    chunk_keys = [
        obj["Key"]
        for page in paginator.paginate(Bucket=bucket, Prefix=f"derived/chunks/{run_date}/")
        for obj in page.get("Contents", [])
    ]

    logger.info("Found %d chunk files", len(chunk_keys))
    if not chunk_keys:
        logger.warning("No chunks found for %s — skipping report generation", run_date)
        return {"run_date": run_date, "chunks_found": 0}

    # 3. Aggregate results across all chunks
    matched_results: List[Dict[str, Any]] = []
    watchlist_signal_counts: Dict[str, int] = {}
    earnings_candidates: List[Dict[str, Any]] = []

    today = date.fromisoformat(run_date)
    week_monday, week_friday = _current_week_bounds(today)

    for key in chunk_keys:
        logger.debug("Reading chunk: %s", key)
        chunk = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
        for r in chunk.get("stock_results", []):
            metrics = r.get("metrics", {})
            earnings_date_str = metrics.get("earnings_date")

            if earnings_date_str:
                try:
                    edate = date.fromisoformat(earnings_date_str)
                    if week_monday <= edate <= week_friday:
                        earnings_candidates.append({
                            "symbol": r["symbol"],
                            "companyName": metrics.get("company_name", r["symbol"]),
                            "close": metrics.get("close", 0),
                            "rsi": metrics.get("rsi_14", 0),
                            "days": metrics.get("earnings_in_days", (edate - today).days),
                            "date": earnings_date_str,
                            "weekday": _WEEKDAY_NAMES[edate.weekday()],
                            "timing": metrics.get("earnings_timing", "TBD"),
                        })
                except ValueError:
                    pass
            matched_rules = r.get("matched_rules", [])
            if not matched_rules:
                continue
            ticker_watchlists = r.get("watchlists", [])
            for wl_id in ticker_watchlists:
                watchlist_signal_counts[wl_id] = watchlist_signal_counts.get(wl_id, 0) + 1
            best = max(matched_rules, key=lambda x: x["score"])
            matched_results.append({
                "symbol": r["symbol"],
                "score": best["score"],
                "reasons": best["reasons"],
                "metrics": metrics,
                "match_count": len(matched_rules),
                "rule_names": [mr["rule_name"] for mr in matched_rules],
                "watchlists": ticker_watchlists,
            })

    matched_results.sort(key=lambda x: (-x["match_count"], -x["score"], x["symbol"]))
    logger.info("Total matched: %d signals, %d earnings candidates", len(matched_results), len(earnings_candidates))

    # 4. Build ReportWatchlist objects from manifest watchlists
    watchlists: List[ReportWatchlist] = [
        ReportWatchlist(
            watchlist_id=wl_id,
            name=wl_data["name"],
            symbols=tuple(wl_data.get("tickers", [])),
            priority="high",
            rule_summary="",
        )
        for wl_id, wl_data in manifest_watchlists.items()
    ]

    # 5. Wrap aggregated dicts as proxies for build_nightly_report
    proxies = [_SignalProxy(item) for item in matched_results]

    # 6. Options ideas — top liquid names from matched set
    liquid = {"AAPL", "NVDA", "META", "TSLA", "MSFT", "AMZN", "GOOGL"}
    option_ideas: List[OptionIdea] = []
    for item in matched_results:
        if item["symbol"] not in liquid:
            continue
        m = item["metrics"]
        chg = m.get("change_percent", 0)
        option_ideas.append(OptionIdea(
            symbol=item["symbol"],
            strategy="Bullish call spread" if chg >= 0 else "Cash-secured put",
            expiration=_next_friday_str(run_date),
            score=round(item["score"] * 100),
            reason=(
                f"Price ${m.get('close', 0):.2f} above 20DMA ${m.get('sma_20', 0):.2f}, "
                f"RSI {m.get('rsi_14', 0):.1f}, day chg {chg:+.1f}%"
            ),
        ))
        if len(option_ideas) >= 4:
            break

    # 7. Build highlights
    sp500_signals = watchlist_signal_counts.get("spy500", 0)
    sp500_total = len(manifest_watchlists.get("spy500", {}).get("tickers", [])) or 484
    fang_signals = watchlist_signal_counts.get("fang", 0)
    fang_total = len(manifest_watchlists.get("fang", {}).get("tickers", [])) or 8
    breadth_pct = round(sp500_signals / sp500_total * 100, 1) if sp500_total else 0.0

    top_conviction = [r["symbol"] for r in matched_results if r["match_count"] > 4]
    top_conviction_highlight = (
        f"Top conviction (5+ rules): {', '.join(top_conviction[:8])}"
        if top_conviction else "No tickers matched more than 4 rules today"
    )

    imminent = sorted(
        {c["symbol"]: c for c in earnings_candidates if c["days"] <= 7}.values(),
        key=lambda c: c["days"],
    )
    earnings_highlight = (
        f"Earnings this week: {', '.join(c['symbol'] for c in imminent[:8])} — watch for elevated implied volatility"
        if imminent else "No earnings this week in the current universe"
    )

    highlights = [
        f"{sp500_signals} of {sp500_total} S&P 500 stocks matched at least one rule — {breadth_pct}% breadth",
        f"FANG+: {fang_signals} of {fang_total} names matched at least one rule",
        top_conviction_highlight,
        earnings_highlight,
    ]

    # 8. Active rules
    active_rules = [CanonicalRule.from_mapping(cfg["rule_def"]) for cfg in RULE_CONFIGS.values()]

    # 9. Report history
    report_history = _build_report_history(s3, bucket, run_date)

    logger.info("Built %d option ideas, %d earnings watch entries", len(option_ideas), len(_build_earnings_watch(earnings_candidates)))

    # 10. News summary for high-priority tickers
    high_priority_symbols = [
        r["symbol"] for r in matched_results
        if r["match_count"] >= 5
    ][:8]
    logger.info("Requesting news summary for %d high-priority symbols: %s",
                len(high_priority_symbols), ", ".join(high_priority_symbols) or "none")
    news_summary = generate_news_summary(high_priority_symbols, run_date)
    logger.info("News summary: %d chars", len(news_summary))

    # 11. Build and publish the report
    report = build_nightly_report(
        trade_date=date.fromisoformat(run_date),
        timezone="America/Los_Angeles",
        watchlists=watchlists,
        stock_results=proxies,
        option_ideas=option_ideas,
        earnings_watch=_build_earnings_watch(earnings_candidates),
        active_rules=active_rules,
        highlights=highlights,
        report_history=report_history,
        universe_name="SPY 500",
        news_summary=news_summary,
    )

    report_json = json.dumps(report, indent=2)
    s3.put_object(Bucket=bucket, Key="reports/latest/report.json",
                  Body=report_json, ContentType="application/json",
                  CacheControl="no-cache, no-store, must-revalidate")
    s3.put_object(Bucket=bucket, Key=f"reports/runs/{run_date}/report.json",
                  Body=report_json, ContentType="application/json")

    _invalidate_cloudfront(run_date)

    logger.info(
        "Published report: %d signals, %d high-priority, %d options",
        len(matched_results), report["summary"]["highPrioritySignals"], len(option_ideas),
    )

    return {
        "run_date": run_date,
        "chunks_found": len(chunk_keys),
        "matched_signals": len(matched_results),
        "high_priority": report["summary"]["highPrioritySignals"],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_manifest(s3, bucket: str, run_date: str):
    try:
        obj = s3.get_object(Bucket=bucket, Key=f"derived/manifests/{run_date}/manifest.json")
        return json.loads(obj["Body"].read())
    except Exception:
        logger.warning("No manifest found for %s", run_date)
        return None


def _next_friday_str(run_date: str) -> str:
    d = date.fromisoformat(run_date)
    days_ahead = (4 - d.weekday()) % 7 or 7
    return (d + timedelta(days=days_ahead)).isoformat()


def _build_report_history(s3, bucket: str, run_date: str) -> list:
    history = [{"label": _fmt_label(run_date), "date": run_date, "href": "/", "isActive": True}]
    try:
        paginator = s3.get_paginator("list_objects_v2")
        keys = [
            obj["Key"]
            for page in paginator.paginate(Bucket=bucket, Prefix="reports/runs/")
            for obj in page.get("Contents", [])
            if obj["Key"].endswith("report.json")
        ]
        for d in sorted({k.split("/")[2] for k in keys if k.split("/")[2] != run_date}, reverse=True)[:4]:
            history.append({"label": _fmt_label(d), "date": d, "href": f"/?date={d}"})
    except Exception:
        pass
    return history


def _fmt_label(iso_date: str) -> str:
    return date.fromisoformat(iso_date).strftime("%b %-d")


def _invalidate_cloudfront(run_date: str) -> None:
    dist_id = os.environ.get("CLOUDFRONT_DISTRIBUTION_ID")
    if not dist_id:
        logger.warning("CLOUDFRONT_DISTRIBUTION_ID not set — skipping invalidation")
        return
    try:
        cf = boto3.client("cloudfront")
        cf.create_invalidation(
            DistributionId=dist_id,
            InvalidationBatch={
                "Paths": {"Quantity": 1, "Items": ["/reports/latest/report.json"]},
                "CallerReference": f"{run_date}-{int(datetime.now().timestamp())}",
            },
        )
        logger.info("CloudFront invalidation created for distribution %s", dist_id)
    except Exception as exc:
        logger.error("CloudFront invalidation failed: %s", exc)


def _build_earnings_watch(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique = sorted(
        {c["symbol"]: c for c in candidates}.values(),
        key=lambda c: (c["date"], c["symbol"]),
    )
    watch = []
    for item in unique:
        days = item["days"]
        watch.append({
            "symbol": item["symbol"],
            "companyName": item["companyName"],
            "date": item["date"],
            "weekday": item["weekday"],
            "timing": item["timing"],
            "when": "Today" if days <= 0 else ("Tomorrow" if days == 1 else f"In {days} days"),
            "priority": "very high" if days <= 1 else ("high" if days <= 3 else "medium"),
            "focus": f"RSI {item['rsi']:.0f}, price ${item['close']:.2f}",
        })
    return watch


def _current_week_bounds(today: date):
    """Return (monday, friday) of the week containing today.
    If today is a weekend, advance to the next week.
    """
    weekday = today.weekday()  # 0=Mon … 6=Sun
    if weekday >= 5:  # Saturday or Sunday → next week
        days_to_monday = 7 - weekday
        monday = today + timedelta(days=days_to_monday)
    else:
        monday = today - timedelta(days=weekday)
    return monday, monday + timedelta(days=4)
