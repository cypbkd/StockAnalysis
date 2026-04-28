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
        return _response(200, cached)
    except s3.exceptions.NoSuchKey:
        pass
    except Exception as exc:
        logger.warning("Cache read error for %s/%s: %s", report_date, ticker, exc)

    # Find the ticker's metrics and rule names from the published report
    metrics, rule_names = _find_signal_data(s3, bucket, report_date, ticker)
    if metrics is None:
        return _response(404, {"error": f"No signal data found for {ticker} on {report_date}"})

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
                "volume_ratio":    tech.get("volumeRatio"),
                "rsi_14":          tech.get("rsi14"),
                "ema_20":          tech.get("ema20"),
                "sma_20":          tech.get("sma20"),
                "sma_50":          tech.get("sma50"),
                "high_52w":        tech.get("high52w"),
                "low_52w":         tech.get("low52w"),
                "pivot_r1":        tech.get("pivotR1"),
                "pivot_r2":        tech.get("pivotR2"),
                "pivot_s1":        tech.get("pivotS1"),
                "pivot_s2":        tech.get("pivotS2"),
                "earnings_date":   tech.get("earningsDate"),
                "earnings_in_days": tech.get("earningsInDays"),
                "earnings_timing": tech.get("earningsTiming"),
            }
            return {k: v for k, v in metrics.items() if v is not None}, signal.get("ruleNames", [])

    return None, []


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": _RESPONSE_HEADERS,
        "body": json.dumps(body),
    }
