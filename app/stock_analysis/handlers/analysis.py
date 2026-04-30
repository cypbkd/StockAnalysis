"""
On-demand ticker analysis Lambda handler.

Called by the frontend when a user opens a ticker detail page.
Checks S3 for a cached analysis first; generates via Gemini on a cache miss.

Invoked via Lambda Function URL:
  GET <function-url>?ticker=AMD&date=2026-04-26

Response body: { summary, rules, priceTargets, verdict }
Errors:        { error: "..." }

CORS is handled by the Lambda Function URL configuration — do NOT set
Access-Control-Allow-Origin in the handler response or the browser will see
duplicate header values and block the request.
"""
import json
import logging
import os
from datetime import date as _date

from stock_analysis.data import RULE_CONFIGS
from stock_analysis.details import generate_ticker_analysis

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_RESPONSE_HEADERS = {
    "Content-Type": "application/json",
}


def handler(event: dict, context: object) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET").upper()

    # CORS preflight is handled by the Function URL — return 200 so it passes through
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": _RESPONSE_HEADERS, "body": ""}

    params = event.get("queryStringParameters") or {}
    ticker = (params.get("ticker") or "").upper().strip()
    report_date = (params.get("date") or "").strip() or _date.today().isoformat()

    if not ticker:
        return _response(400, {"error": "ticker query param is required"})

    bucket = os.environ.get("CACHE_BUCKET", "")
    if not bucket:
        return _response(500, {"error": "CACHE_BUCKET not configured"})

    import boto3
    s3 = boto3.client("s3")
    cache_key = f"analyses/{report_date}/{ticker}.json"

    # Check S3 cache — a hit means we already paid for this Gemini call
    try:
        obj = s3.get_object(Bucket=bucket, Key=cache_key)
        cached = json.loads(obj["Body"].read())
        logger.info("Cache hit: %s/%s", report_date, ticker)
        # Backfill fundamentals into cached analyses that predate this feature
        if "fundamentals" not in cached:
            fundamentals = _fetch_fundamentals(ticker)
            if fundamentals:
                cached["fundamentals"] = fundamentals
                try:
                    s3.put_object(
                        Bucket=bucket,
                        Key=cache_key,
                        Body=json.dumps(cached),
                        ContentType="application/json",
                    )
                    logger.info("Backfilled fundamentals into cache: %s/%s", report_date, ticker)
                except Exception as exc:
                    logger.warning("Cache backfill write error for %s/%s: %s", report_date, ticker, exc)
        return _response(200, cached)
    except s3.exceptions.NoSuchKey:
        pass
    except Exception as exc:
        logger.warning("Cache read error for %s/%s: %s", report_date, ticker, exc)

    # Find the ticker's metrics and rule names from the published report
    metrics, rule_names = _find_signal_data(s3, bucket, report_date, ticker)
    if metrics is None:
        return _response(404, {"error": f"No signal data found for {ticker} on {report_date}"})

    # Fetch fundamentals (PE, fair price) and generate Gemini analysis in parallel
    fundamentals = _fetch_fundamentals(ticker)

    # Generate analysis via Gemini
    analysis = generate_ticker_analysis(
        ticker=ticker,
        metrics=metrics,
        rule_names=rule_names,
        rule_configs=RULE_CONFIGS,
        trade_date=report_date,
    )
    if analysis is None:
        return _response(503, {"error": "Analysis generation failed — check Lambda logs"})

    if fundamentals:
        analysis["fundamentals"] = fundamentals
        logger.info("Fundamentals attached for %s: PE=%s fwdPE=%s fairPrice=%s",
                    ticker, fundamentals.get("pe"), fundamentals.get("forwardPe"), fundamentals.get("fairPrice"))

    # Cache result so repeat views are free
    try:
        s3.put_object(
            Bucket=bucket,
            Key=cache_key,
            Body=json.dumps(analysis),
            ContentType="application/json",
        )
        logger.info("Cached analysis: %s/%s", report_date, ticker)
    except Exception as exc:
        logger.warning("Cache write error for %s/%s: %s", report_date, ticker, exc)

    return _response(200, analysis)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_signal_data(s3, bucket: str, report_date: str, ticker: str):
    """Return (metrics_dict, rule_names) for ticker from the published report.

    Checks the date-specific report first, then latest.  Returns (None, []) if
    the ticker has no signal in either report.
    """
    for key in [
        f"reports/runs/{report_date}/report.json",
        "reports/latest/report.json",
    ]:
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            report = json.loads(obj["Body"].read())
        except Exception as exc:
            logger.debug("Could not read %s: %s", key, exc)
            continue

        for signal in report.get("stockSignals", []):
            if signal.get("symbol") != ticker:
                continue

            tech = signal.get("technicalData") or {}
            metrics = {
                "company_name": signal.get("companyName", ticker),
                "close": signal.get("lastPrice", 0),
                "change_percent": signal.get("changePercent", 0),
                # Map camelCase technicalData keys back to snake_case metric names
                "open":           tech.get("sessionOpen"),
                "high":           tech.get("sessionHigh"),
                "low":            tech.get("sessionLow"),
                "prev_open":      tech.get("prevOpen"),
                "prev_close":     tech.get("prevClose"),
                "prev_high":      tech.get("prevHigh"),
                "prev_low":       tech.get("prevLow"),
                "volume_ratio":   tech.get("volumeRatio"),
                "rsi_14":         tech.get("rsi14"),
                "ema_20":         tech.get("ema20"),
                "sma_20":         tech.get("sma20"),
                "sma_50":         tech.get("sma50"),
                "sma_200":        tech.get("sma200"),
                "prev_sma_20":    tech.get("prevSma20"),
                "prev_sma_50":    tech.get("prevSma50"),
                "high_52w":       tech.get("high52w"),
                "low_52w":        tech.get("low52w"),
                "pivot_r1":       tech.get("pivotR1"),
                "pivot_r2":       tech.get("pivotR2"),
                "pivot_s1":       tech.get("pivotS1"),
                "pivot_s2":       tech.get("pivotS2"),
                "high_200d":      tech.get("high200d"),
                "low_200d":       tech.get("low200d"),
                "open_200d":      tech.get("open200d"),
                "lt_pivot_r1":    tech.get("ltR1"),
                "lt_pivot_r2":    tech.get("ltR2"),
                "lt_pivot_s1":    tech.get("ltS1"),
                "lt_pivot_s2":    tech.get("ltS2"),
                "earnings_date":  tech.get("earningsDate"),
                "earnings_in_days": tech.get("earningsInDays"),
                "earnings_timing": tech.get("earningsTiming"),
            }
            return {k: v for k, v in metrics.items() if v is not None}, signal.get("ruleNames", [])

    return None, []


def _fetch_fundamentals(ticker: str) -> dict:
    """Fetch PE, EPS, and Revised Graham fair value.

    Growth rate g uses the analyst 5-year EPS growth estimate from
    yfinance growth_estimates["+5y"]. If that data is unavailable,
    earningsGrowth and fairPrice are both omitted from the result.

    Revised Graham formula: V = EPS × (8.5 + 2g) × 4.4 / Y
    where Y is the current 10-yr Treasury yield (fallback 4.4%).

    Returns an empty dict on any failure so the caller can degrade gracefully.
    """
    try:
        import yfinance as yf
        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info
        trailing_pe = info.get("trailingPE")
        forward_pe = info.get("forwardPE")
        trailing_eps = info.get("trailingEps")
        forward_eps = info.get("forwardEps")

        # 5-year analyst EPS growth estimate (decimal, e.g. 0.08 = 8%)
        earnings_growth = None
        try:
            growth_df = yf_ticker.growth_estimates
            if growth_df is not None and not growth_df.empty and "+5y" in growth_df.index:
                row = growth_df.loc["+5y"].dropna()
                if not row.empty:
                    earnings_growth = float(row.iloc[0])
        except Exception as exc:
            logger.debug("growth_estimates unavailable for %s: %s", ticker, exc)

        # Revised Graham formula: V = EPS × (8.5 + 2g) × 4.4 / Y
        bond_yield = 4.4  # fallback
        try:
            tnx = yf.Ticker("^TNX")
            tnx_price = tnx.info.get("regularMarketPrice") or getattr(tnx.fast_info, "lastPrice", None)
            if tnx_price:
                bond_yield = float(tnx_price)
        except Exception:
            pass

        fair_price = None
        if trailing_eps and earnings_growth is not None:
            g = max(0.0, min(50.0, earnings_growth * 100))
            fair_price = round(float(trailing_eps) * (8.5 + 2 * g) * 4.4 / bond_yield, 2)

        result: dict = {}
        if trailing_pe is not None:
            result["pe"] = round(float(trailing_pe), 1)
        if forward_pe is not None:
            result["forwardPe"] = round(float(forward_pe), 1)
        if trailing_eps is not None:
            result["eps"] = round(float(trailing_eps), 2)
        if forward_eps is not None:
            result["forwardEps"] = round(float(forward_eps), 2)
        if earnings_growth is not None:
            result["earningsGrowth"] = round(earnings_growth * 100, 1)
        if fair_price is not None:
            result["fairPrice"] = fair_price
            result["bondYield"] = round(bond_yield, 2)

        logger.info("Fundamentals for %s: PE=%s fwdPE=%s EPS=%s growth5y=%s fairPrice=%s bondYield=%s",
                    ticker, result.get("pe"), result.get("forwardPe"),
                    result.get("eps"), result.get("earningsGrowth"), result.get("fairPrice"), result.get("bondYield"))
        return result
    except Exception as exc:
        logger.warning("Failed to fetch fundamentals for %s: %s", ticker, exc)
        return {}


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": _RESPONSE_HEADERS,
        "body": json.dumps(body),
    }
