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
from stock_analysis.options import build_options_ideas
from stock_analysis.rules import CanonicalRule
from stock_analysis.screening import build_nightly_report, OptionIdea, ReportWatchlist
from stock_analysis.trending import build_trending_tickers

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_Condition = namedtuple("_Condition", ["reason"])


def _format_option_contract(idea) -> str:
    """Format an OptionIdea as a compact OCC-style contract label.

    e.g. NDAQ $89 put expiring 2026-05-08 → NDAQ260508P00089000
    Both cash-secured put and bear put spread strategies are puts (P).
    """
    symbol = idea.symbol
    exp = idea.expiration or ""
    strike = idea.strike

    try:
        from datetime import datetime as _dt
        date_str = _dt.strptime(exp, "%Y-%m-%d").strftime("%y%m%d")
    except Exception:
        date_str = exp.replace("-", "")[-6:]

    strike_int = round((strike or 0) * 1000)
    return f"{symbol}{date_str}P{strike_int:08d}"


def _option_strategy_abbrev(strategy: str) -> str:
    """Map a strategy description to a short 2-letter code.

    BC = Buy Call, BP = Buy Put, SC = Sell Call, SP = Sell Put
    """
    s = strategy.lower()
    if "cash-secured put" in s or ("sell" in s and "put" in s):
        return "SP"
    if "bear put spread" in s or ("buy" in s and "put" in s):
        return "BP"
    if "cash-secured call" in s or ("sell" in s and "call" in s):
        return "SC"
    if "bull call spread" in s or ("buy" in s and "call" in s):
        return "BC"
    return "OPT"


def _ticker_anchor(symbol: str, href: str, label: str = None) -> str:
    """Return a safe HTML anchor for a ticker symbol."""
    return f'<a href="{href}">{label or symbol}</a>'

# Sum of all rule weights — used to normalise weighted_score to 0–100
_MAX_WEIGHTED_SCORE = sum(cfg.get("weight", 1.0) for cfg in RULE_CONFIGS.values())


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
            "weighted_score": d.get("weighted_score", 0),
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
    all_chunk_symbols: set = set()
    ticker_metrics_map: Dict[str, Dict] = {}

    today = date.fromisoformat(run_date)
    week_monday, week_friday = _current_week_bounds(today)

    for key in chunk_keys:
        logger.debug("Reading chunk: %s", key)
        chunk = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
        for r in chunk.get("stock_results", []):
            sym = r["symbol"]
            metrics = r.get("metrics", {})
            all_chunk_symbols.add(sym)
            if sym not in ticker_metrics_map:
                ticker_metrics_map[sym] = metrics
            earnings_date_str = metrics.get("earnings_date")

            if earnings_date_str:
                try:
                    edate = date.fromisoformat(earnings_date_str)
                    if week_monday <= edate <= week_friday:
                        earnings_candidates.append({
                            "symbol": sym,
                            "companyName": metrics.get("company_name", sym),
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
            raw_weighted = sum(
                RULE_CONFIGS.get(mr.get("rule_key", ""), {}).get("weight", 1.0)
                for mr in matched_rules
            )
            weighted_score = round(raw_weighted / _MAX_WEIGHTED_SCORE * 100)
            logger.debug("Ticker %s: match_count=%d weighted_score=%d", sym, len(matched_rules), weighted_score)
            matched_results.append({
                "symbol": sym,
                "score": best["score"],
                "reasons": best["reasons"],
                "metrics": metrics,
                "match_count": len(matched_rules),
                "weighted_score": weighted_score,
                "rule_names": [mr["rule_name"] for mr in matched_rules],
                "watchlists": ticker_watchlists,
            })

    # Supplement earnings_candidates from Earnings API S3 cache for past days in the week
    # (workers may have missed them if they ran after the earnings date passed)
    supplemental = _supplement_earnings_from_api_cache(
        s3, bucket, week_monday, today, earnings_candidates,
        all_chunk_symbols, ticker_metrics_map,
    )
    earnings_candidates.extend(supplemental)

    matched_results.sort(key=lambda x: (-x["weighted_score"], -x["match_count"], x["symbol"]))
    logger.info("Total matched: %d signals, %d earnings candidates (%d supplemented from API cache)",
                len(matched_results), len(earnings_candidates), len(supplemental))

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

    # 6. Options ideas — real options chain analysis for liquid names that matched
    option_ideas: List[OptionIdea] = build_options_ideas(matched_results, max_ideas=5)

    # 7. Active rules
    active_rules = [CanonicalRule.from_mapping(cfg["rule_def"]) for cfg in RULE_CONFIGS.values()]

    # 8. Report history
    report_history = _build_report_history(s3, bucket, run_date)

    logger.info("Built %d option ideas, %d earnings watch entries", len(option_ideas), len(_build_earnings_watch(earnings_candidates)))

    # 9. Trending tickers from Yahoo Finance (fetched before highlights so we can include them)
    logger.info("Fetching trending tickers from Yahoo Finance")
    trending_tickers = build_trending_tickers(run_date)
    logger.info("Built %d trending tickers", len(trending_tickers))

    # 10. Build highlights
    total_symbols = len(all_chunk_symbols)
    total_matched = len(matched_results)
    breadth_pct = round(total_matched / total_symbols * 100, 1) if total_symbols else 0.0

    top_conviction = [r["symbol"] for r in matched_results if r["weighted_score"] >= 40]
    if top_conviction:
        top10_links = ", ".join(
            _ticker_anchor(s, f"#symbol/{s}") for s in top_conviction[:10]
        )
        top_conviction_highlight = (
            f"Top conviction (score ≥40): {len(top_conviction)} tickers — {top10_links}"
        )
    else:
        top_conviction_highlight = "No tickers reached conviction threshold today"

    imminent = sorted(
        {c["symbol"]: c for c in earnings_candidates if c["days"] <= 7}.values(),
        key=lambda c: c["days"],
    )
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

    if trending_tickers:
        trending_links = ", ".join(
            _ticker_anchor(t["symbol"], f"https://finance.yahoo.com/quote/{t['symbol']}/")
            for t in trending_tickers[:10]
        )
        trending_highlight = f"Yahoo trending from the past 3 days: {trending_links}"
    else:
        trending_highlight = "No Yahoo Finance trending tickers available today"
    logger.info("Trending highlight symbols: %s", ", ".join(t["symbol"] for t in trending_tickers[:10]))

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
    logger.info("Options highlight: %s", options_highlight)

    highlights = [
        f"{total_matched} of {total_symbols} stocks matched at least one rule — {breadth_pct}% breadth",
        top_conviction_highlight,
        earnings_highlight,
        trending_highlight,
        options_highlight,
    ]

    # 11. News summary — combine high-priority screener picks with trending tickers (already fetched)
    # so Gemini has context on both technically strong names and market buzz.
    high_priority_symbols = [
        r["symbol"] for r in matched_results
        if r["weighted_score"] >= 35
    ][:8]
    trending_symbols = [t["symbol"] for t in trending_tickers]
    # Merge, deduplicate, cap at 10 so the prompt stays focused
    news_symbols = list(dict.fromkeys(high_priority_symbols + trending_symbols))[:10]
    logger.info("Requesting news summary for %d symbols (high-priority + trending): %s",
                len(news_symbols), ", ".join(news_symbols) or "none")
    news_summary = generate_news_summary(news_symbols, run_date)
    logger.info("News summary: %d chars", len(news_summary))

    # 12. Build and publish the report
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
        trending_tickers=trending_tickers,
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


def _supplement_earnings_from_api_cache(
    s3,
    bucket: str,
    week_monday: date,
    today: date,
    existing_candidates: List[Dict[str, Any]],
    universe_symbols: set,
    ticker_metrics_map: Dict[str, Dict],
) -> List[Dict[str, Any]]:
    """Read the Earnings API S3 cache for past days in the current week and add any
    universe tickers whose earnings date workers missed (e.g. because the earnings
    date had already passed when the workers ran).  No live API calls are made here —
    only cached files that workers already wrote are used.
    """
    existing = {c["symbol"] for c in existing_candidates}
    supplemental: List[Dict[str, Any]] = []
    timing_map = [("pre", "Before Open"), ("after", "After Close"), ("notSupplied", "TBD")]

    d = week_monday
    while d < today:  # past days only; today's data comes from workers
        key = f"raw/earnings-api/date={d.isoformat()}/calendar.json"
        try:
            payload = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
        except Exception:
            d += timedelta(days=1)
            continue

        days_val = (d - today).days
        weekday_name = _WEEKDAY_NAMES[d.weekday()]
        for timing_key, timing_label in timing_map:
            for row in payload.get(timing_key, []):
                sym = str(row.get("symbol") or "").strip().upper()
                if not sym or sym not in universe_symbols or sym in existing:
                    continue
                metrics = ticker_metrics_map.get(sym, {})
                supplemental.append({
                    "symbol": sym,
                    "companyName": metrics.get("company_name", sym),
                    "close": metrics.get("close", 0),
                    "rsi": metrics.get("rsi_14", 0),
                    "days": days_val,
                    "date": d.isoformat(),
                    "weekday": weekday_name,
                    "timing": timing_label,
                })
                existing.add(sym)

        logger.info("API cache supplement: %s yielded %d new entries so far",
                    d.isoformat(), len(supplemental))
        d += timedelta(days=1)

    return supplemental
