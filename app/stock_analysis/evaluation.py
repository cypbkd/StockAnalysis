"""
Signal evaluation: computes 3-day forward returns for screener signals
and builds a Ticker Compliance leaderboard.

S3 layout
---------
evaluations/YYYY-MM-DD.json          one record per non-mixed signal on that date
evaluations/compliance-summary.json  rolling 90-day aggregate, rewritten each night
evaluations/tickers/{TICKER}.json    per-ticker detail (signal timeline, rule breakdown,
                                     market breadth), rewritten each night for all
                                     qualifying tickers

Each daily file is a JSON array of records::

    {
      "signalDate":  "2026-05-01",
      "exitDate":    "2026-05-06",
      "ticker":      "AAPL",
      "direction":   "bullish",
      "ruleKeys":    ["ma_stack", "golden_cross"],
      "entryPrice":  175.42,
      "exitPrice":   180.10,
      "return3d":    2.67,
      "win":         true
    }

Deduplication: records are de-duped by (ticker, exitDate) before any aggregation.
Two signals sharing the same exit date measure the same price move, so they count
as one observation regardless of how many report runs produced them (e.g. weekend
test runs that replayed Friday's data).
"""
import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BULLISH_RULES = frozenset({
    "ma_stack", "golden_cross", "ath_breakout", "near_ath",
    "oversold_dip", "pre_earnings_momentum", "high_vol_day",
    "strong_trending_day", "near_52w_support", "pivot_s1_bounce",
    "pivot_r1_breakout", "td_buy",
})
BEARISH_RULES = frozenset({"dead_cross", "td_sell"})

RULE_DISPLAY_NAMES: Dict[str, str] = {
    "ma_stack":              "MA Stack",
    "golden_cross":          "Golden Cross",
    "dead_cross":            "Dead Cross",
    "ath_breakout":          "ATH Breakout",
    "near_ath":              "Near ATH",
    "oversold_dip":          "Oversold Dip",
    "pre_earnings_momentum": "Pre-Earnings",
    "high_vol_day":          "High Volume",
    "strong_trending_day":   "Strong Trend",
    "near_52w_support":      "52W Support",
    "pivot_s1_bounce":       "S1 Bounce",
    "pivot_r1_breakout":     "R1 Breakout",
    "td_buy":                "TD Buy (九转)",
    "td_sell":               "TD Sell (九转)",
}

# Lazily populated reverse map: rule display name → rule key, for old reports
_NAME_TO_KEY: Dict[str, str] = {}


def _get_name_to_key() -> Dict[str, str]:
    global _NAME_TO_KEY
    if not _NAME_TO_KEY:
        from stock_analysis.data import RULE_CONFIGS
        _NAME_TO_KEY = {
            cfg["rule_def"]["name"]: key
            for key, cfg in RULE_CONFIGS.items()
        }
    return _NAME_TO_KEY


def signal_direction(rule_keys: List[str]) -> str:
    """Return 'bullish', 'bearish', or 'mixed' based on net rule direction."""
    bullish = sum(1 for r in rule_keys if r in BULLISH_RULES)
    bearish = sum(1 for r in rule_keys if r in BEARISH_RULES)
    if bullish > bearish:
        return "bullish"
    if bearish > bullish:
        return "bearish"
    return "mixed"


def nth_trading_day_after(date_str: str, n: int) -> str:
    """Return the date string of the nth trading day after date_str (weekends skipped)."""
    d = date.fromisoformat(date_str)
    count = 0
    while count < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d.isoformat()


def nth_trading_day_before(date_str: str, n: int) -> str:
    """Return the date string of the nth trading day before date_str (weekends skipped)."""
    d = date.fromisoformat(date_str)
    count = 0
    while count < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d.isoformat()


def _resolve_rule_keys(signal: Dict[str, Any]) -> List[str]:
    """Extract rule keys from a signal dict.

    New reports carry a ruleKeys field.  Old reports only have ruleNames
    (display names), so we fall back to a reverse-map lookup.
    """
    if signal.get("ruleKeys"):
        return list(signal["ruleKeys"])
    name_map = _get_name_to_key()
    return [name_map[n] for n in signal.get("ruleNames", []) if n in name_map]


def _fetch_prices_batch(tickers: List[str], target_date: str) -> Dict[str, float]:
    """Fetch closing prices for a list of tickers on target_date via yfinance."""
    import yfinance as yf

    if not tickers:
        return {}

    target = date.fromisoformat(target_date)
    end = (target + timedelta(days=1)).isoformat()

    try:
        df = yf.download(
            tickers,
            start=target_date,
            end=end,
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            logger.warning("No price data for %d tickers on %s", len(tickers), target_date)
            return {}

        close = df["Close"]

        if len(tickers) == 1:
            if not close.empty:
                return {tickers[0]: float(close.iloc[-1])}
            return {}

        result: Dict[str, float] = {}
        for ticker in tickers:
            if ticker in close.columns:
                series = close[ticker].dropna()
                if not series.empty:
                    result[ticker] = float(series.iloc[-1])
        return result

    except Exception as exc:
        logger.error("Price batch fetch failed for %s on %s: %s", tickers, target_date, exc)
        return {}


def _dedup_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate evaluation records by (ticker, exitDate).

    Two records sharing the same exit date measure the identical 3-day price move —
    they count as one observation.  This collapses signals from duplicate/weekend
    report runs that replayed the same market data.

    When duplicates exist, we keep the record with the latest signalDate so the
    timeline entry reflects the most recent trigger.
    """
    best: Dict[tuple, Dict[str, Any]] = {}
    for rec in records:
        key = (rec["ticker"], rec["exitDate"])
        if key not in best or rec["signalDate"] > best[key]["signalDate"]:
            best[key] = rec
    return list(best.values())


def _compute_market_breadth(deduped_records: List[Dict[str, Any]]) -> Dict[str, float]:
    """For each exitDate, compute the fraction of all tickers that won.

    This is the market-wide "breadth" on that date — a high value means the
    overall market was rising (so individual wins are less remarkable), while
    a low value means FFIV winning was genuinely against the tide.
    """
    by_exit: Dict[str, List[bool]] = defaultdict(list)
    for rec in deduped_records:
        by_exit[rec["exitDate"]].append(rec["win"])
    return {
        exit_date: round(sum(wins) / len(wins), 3)
        for exit_date, wins in by_exit.items()
        if wins
    }


def evaluate_report_date(
    s3,
    bucket: str,
    signal_date: str,
    exit_date: str,
) -> List[Dict[str, Any]]:
    """Load the report for signal_date, fetch closing prices on exit_date,
    and return evaluation records (one per non-mixed signal).
    """
    report_key = f"reports/runs/{signal_date}/report.json"
    try:
        report = json.loads(s3.get_object(Bucket=bucket, Key=report_key)["Body"].read())
    except Exception as exc:
        logger.warning("No report found for signal_date=%s: %s", signal_date, exc)
        return []

    signals = report.get("stockSignals", [])
    if not signals:
        logger.info("No stockSignals in report for %s", signal_date)
        return []

    directional = []
    for sig in signals:
        rule_keys = _resolve_rule_keys(sig)
        if not rule_keys:
            continue
        direction = signal_direction(rule_keys)
        if direction == "mixed":
            continue
        directional.append({
            "ticker": sig["symbol"],
            "direction": direction,
            "ruleKeys": rule_keys,
            "entryPrice": sig.get("lastPrice"),
        })

    if not directional:
        logger.info("All signals mixed or empty for signal_date=%s", signal_date)
        return []

    tickers = [d["ticker"] for d in directional]
    logger.info(
        "Fetching %d exit prices for signal_date=%s exit_date=%s",
        len(tickers), signal_date, exit_date,
    )
    exit_prices = _fetch_prices_batch(tickers, exit_date)

    records: List[Dict[str, Any]] = []
    for item in directional:
        ticker = item["ticker"]
        entry = item["entryPrice"]
        exit_ = exit_prices.get(ticker)

        if exit_ is None or not entry or entry <= 0:
            logger.debug("Skipping %s: missing price (entry=%s, exit=%s)", ticker, entry, exit_)
            continue

        ret3d = (exit_ - entry) / entry * 100
        win = (ret3d > 0) if item["direction"] == "bullish" else (ret3d < 0)

        records.append({
            "signalDate": signal_date,
            "exitDate": exit_date,
            "ticker": ticker,
            "direction": item["direction"],
            "ruleKeys": item["ruleKeys"],
            "entryPrice": round(entry, 4),
            "exitPrice": round(exit_, 4),
            "return3d": round(ret3d, 4),
            "win": win,
        })

    logger.info(
        "Evaluated %d/%d signals for signal_date=%s (exit=%s)",
        len(records), len(directional), signal_date, exit_date,
    )
    return records


def load_eval_files(s3, bucket: str, lookback_days: int = 90) -> List[Dict[str, Any]]:
    """Load evaluation daily files from the past lookback_days out of S3."""
    today = date.today()
    all_records: List[Dict[str, Any]] = []

    for i in range(lookback_days):
        d = (today - timedelta(days=i)).isoformat()
        key = f"evaluations/{d}.json"
        try:
            data = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
            all_records.extend(data)
        except Exception:
            pass

    logger.info("Loaded %d raw evaluation records from past %d days", len(all_records), lookback_days)
    return all_records


def build_compliance_summary(
    all_records: List[Dict[str, Any]],
    min_signals: int = 3,
) -> Dict[str, Any]:
    """Aggregate evaluation records into per-ticker compliance stats.

    Records are first deduplicated by (ticker, exitDate) to prevent weekend
    duplicate runs from inflating counts. Tickers with fewer than min_signals
    unique observations are excluded.
    """
    deduped = _dedup_records(all_records)
    logger.info("Deduplicated %d raw records → %d unique (ticker, exitDate) pairs",
                len(all_records), len(deduped))

    by_ticker: Dict[str, List[Dict]] = defaultdict(list)
    for rec in deduped:
        by_ticker[rec["ticker"]].append(rec)

    tickers_out = []
    for ticker, recs in by_ticker.items():
        total = len(recs)
        if total < min_signals:
            continue
        wins = sum(1 for r in recs if r["win"])
        avg_ret = sum(r["return3d"] for r in recs) / total
        last_date = max(r["signalDate"] for r in recs)
        tickers_out.append({
            "ticker": ticker,
            "totalSignals": total,
            "wins": wins,
            "winRate": round(wins / total, 3),
            "avgReturn3d": round(avg_ret, 2),
            "lastSignalDate": last_date,
        })

    tickers_out.sort(key=lambda t: (-t["winRate"], -t["totalSignals"]))

    return {
        "updatedAt": date.today().isoformat(),
        "lookbackDays": 90,
        "minSignals": min_signals,
        "tickers": tickers_out,
    }


def build_ticker_detail(
    ticker: str,
    recs: List[Dict[str, Any]],
    market_breadth: Dict[str, float],
) -> Dict[str, Any]:
    """Build a detailed breakdown for one ticker.

    Includes: per-signal timeline with market breadth, per-rule win stats,
    dominant rule, and earnings-catalyst flag count.
    """
    total = len(recs)
    wins = sum(1 for r in recs if r["win"])

    # Per-rule statistics
    rule_stats: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "wins": 0, "returns": []})
    for rec in recs:
        for rk in rec["ruleKeys"]:
            rule_stats[rk]["count"] += 1
            if rec["win"]:
                rule_stats[rk]["wins"] += 1
            rule_stats[rk]["returns"].append(rec["return3d"])

    rule_breakdown = []
    for rk, stats in sorted(rule_stats.items(), key=lambda x: -x[1]["count"]):
        cnt = stats["count"]
        rule_breakdown.append({
            "ruleKey": rk,
            "display": RULE_DISPLAY_NAMES.get(rk, rk),
            "count": cnt,
            "wins": stats["wins"],
            "winRate": round(stats["wins"] / cnt, 3),
            "avgReturn3d": round(sum(stats["returns"]) / cnt, 2),
        })

    dominant_rule = rule_breakdown[0]["ruleKey"] if rule_breakdown else None
    dominant_rule_display = rule_breakdown[0]["display"] if rule_breakdown else None
    earnings_signals = sum(
        1 for r in recs if "pre_earnings_momentum" in r["ruleKeys"]
    )

    signals = []
    for rec in sorted(recs, key=lambda r: r["signalDate"]):
        signals.append({
            "signalDate": rec["signalDate"],
            "exitDate": rec["exitDate"],
            "direction": rec["direction"],
            "ruleKeys": rec["ruleKeys"],
            "ruleDisplays": [RULE_DISPLAY_NAMES.get(rk, rk) for rk in rec["ruleKeys"]],
            "entryPrice": rec["entryPrice"],
            "exitPrice": rec["exitPrice"],
            "return3d": rec["return3d"],
            "win": rec["win"],
            "hasEarnings": "pre_earnings_momentum" in rec["ruleKeys"],
            "marketBreadth": market_breadth.get(rec["exitDate"]),
        })

    return {
        "ticker": ticker,
        "totalSignals": total,
        "wins": wins,
        "winRate": round(wins / total, 3),
        "avgReturn3d": round(sum(r["return3d"] for r in recs) / total, 2),
        "lastSignalDate": max(r["signalDate"] for r in recs),
        "dominantRule": dominant_rule,
        "dominantRuleDisplay": dominant_rule_display,
        "earningsSignals": earnings_signals,
        "ruleBreakdown": rule_breakdown,
        "signals": signals,
        "updatedAt": date.today().isoformat(),
    }


def write_ticker_details(
    s3,
    bucket: str,
    all_records: List[Dict[str, Any]],
    qualifying_tickers: List[str],
    market_breadth: Dict[str, float],
) -> int:
    """Write per-ticker detail files to S3 for all qualifying tickers.

    Returns the number of files written.
    """
    deduped = _dedup_records(all_records)
    by_ticker: Dict[str, List[Dict]] = defaultdict(list)
    for rec in deduped:
        by_ticker[rec["ticker"]].append(rec)

    written = 0
    ticker_set = set(qualifying_tickers)
    for ticker in ticker_set:
        recs = by_ticker.get(ticker)
        if not recs:
            continue
        detail = build_ticker_detail(ticker, recs, market_breadth)
        s3.put_object(
            Bucket=bucket,
            Key=f"evaluations/tickers/{ticker}.json",
            Body=json.dumps(detail, indent=2),
            ContentType="application/json",
        )
        written += 1

    logger.info("Wrote %d ticker detail files to evaluations/tickers/", written)
    return written


def run_nightly_evaluation(s3, bucket: str, run_date: str) -> Optional[Dict[str, Any]]:
    """Main entry point called by the aggregator after publishing the report.

    1. Determines signal_date = 3 trading days before run_date.
    2. Writes evaluations/{signal_date}.json if it doesn't already exist.
    3. Loads all eval files from the past 90 days.
    4. Builds and writes compliance summary + per-ticker detail files.
    5. Returns the compliance summary dict (caller embeds as tickerCompliance).
    """
    signal_date = nth_trading_day_before(run_date, 3)
    exit_date = run_date

    logger.info(
        "run_nightly_evaluation: run_date=%s signal_date=%s exit_date=%s",
        run_date, signal_date, exit_date,
    )

    eval_key = f"evaluations/{signal_date}.json"
    exit_weekday = date.fromisoformat(exit_date).weekday()

    # Determine whether we've already evaluated this signal_date.
    # Weekend runs (Sat/Sun) write empty placeholder files to prevent yfinance
    # thundering-herd retries. The same signal_date is reused by the following
    # Monday run, so we must NOT let an empty placeholder block Monday's real
    # evaluation: only treat the file as "done" if it contains actual records
    # OR if today is also a weekend (no new data is available anyway).
    already_done = False
    try:
        existing_data = json.loads(s3.get_object(Bucket=bucket, Key=eval_key)["Body"].read())
        if exit_weekday >= 5:
            already_done = True  # Weekend: placeholder is sufficient
        else:
            already_done = len(existing_data) > 0  # Weekday: need real records
        if already_done:
            logger.info(
                "Evaluation for signal_date=%s already exists (%d records) — skipping write",
                signal_date, len(existing_data),
            )
        else:
            logger.info(
                "Eval file for signal_date=%s exists but is empty (weekend placeholder) — re-evaluating on weekday exit_date=%s",
                signal_date, exit_date,
            )
    except Exception:
        pass

    if not already_done:
        if exit_weekday >= 5:
            # Weekend — no market data; write an empty placeholder so future
            # weekend retries skip the yfinance download.
            logger.info(
                "exit_date=%s is a weekend (weekday=%d) — skipping price fetch, writing empty eval file",
                exit_date, exit_weekday,
            )
            records = []
        else:
            records = evaluate_report_date(s3, bucket, signal_date, exit_date)
        # Always write the file so already_done=True on same-run-date retries.
        s3.put_object(
            Bucket=bucket,
            Key=eval_key,
            Body=json.dumps(records, indent=2),
            ContentType="application/json",
        )
        logger.info("Wrote %d evaluation records to %s", len(records), eval_key)

    all_records = load_eval_files(s3, bucket, lookback_days=90)
    if not all_records:
        logger.info("No evaluation records in the past 90 days — skipping compliance summary")
        return None

    summary = build_compliance_summary(all_records)

    s3.put_object(
        Bucket=bucket,
        Key="evaluations/compliance-summary.json",
        Body=json.dumps(summary, indent=2),
        ContentType="application/json",
    )
    logger.info(
        "Wrote compliance summary: %d tickers qualify (min %d signals)",
        len(summary["tickers"]), summary["minSignals"],
    )

    # Per-ticker detail files
    deduped = _dedup_records(all_records)
    market_breadth = _compute_market_breadth(deduped)
    qualifying = [t["ticker"] for t in summary["tickers"]]
    write_ticker_details(s3, bucket, all_records, qualifying, market_breadth)

    return summary


def backfill_evaluations(s3, bucket: str, from_date: str, to_date: str) -> int:
    """Backfill evaluation files for all historical reports in [from_date, to_date].

    Returns the number of dates successfully evaluated.
    """
    today = date.today()
    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)

    evaluated = 0
    d = start
    while d <= end:
        d_str = d.isoformat()
        exit_date_str = nth_trading_day_after(d_str, 3)

        if date.fromisoformat(exit_date_str) > today:
            logger.info("Skipping %s — exit date %s is in the future", d_str, exit_date_str)
            d += timedelta(days=1)
            continue

        eval_key = f"evaluations/{d_str}.json"
        try:
            existing_data = json.loads(s3.get_object(Bucket=bucket, Key=eval_key)["Body"].read())
            if existing_data:
                logger.info("Already evaluated %s (%d records) — skipping", d_str, len(existing_data))
                d += timedelta(days=1)
                continue
            logger.info("Eval file for %s exists but is empty (weekend placeholder) — re-evaluating", d_str)
        except Exception:
            pass

        records = evaluate_report_date(s3, bucket, d_str, exit_date_str)
        if records:
            s3.put_object(
                Bucket=bucket,
                Key=eval_key,
                Body=json.dumps(records, indent=2),
                ContentType="application/json",
            )
            logger.info("Backfilled %d records for %s (exit=%s)", len(records), d_str, exit_date_str)
            evaluated += 1
        else:
            logger.info("No records for %s — skipping", d_str)

        d += timedelta(days=1)

    if evaluated > 0:
        all_records = load_eval_files(s3, bucket, lookback_days=90)
        summary = build_compliance_summary(all_records)
        s3.put_object(
            Bucket=bucket,
            Key="evaluations/compliance-summary.json",
            Body=json.dumps(summary, indent=2),
            ContentType="application/json",
        )

        deduped = _dedup_records(all_records)
        market_breadth = _compute_market_breadth(deduped)
        qualifying = [t["ticker"] for t in summary["tickers"]]
        write_ticker_details(s3, bucket, all_records, qualifying, market_breadth)

        logger.info(
            "Backfill complete: %d dates evaluated, compliance summary has %d tickers, %d detail files written",
            evaluated, len(summary["tickers"]), len(qualifying),
        )

    return evaluated
