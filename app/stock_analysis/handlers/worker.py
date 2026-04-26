import json
import logging
import os
import boto3

from stock_analysis.data import COMPANY_NAMES, RULE_CONFIGS, fetch_market_data
from stock_analysis.earnings import fetch_earnings_dates
from stock_analysis.rules import CanonicalRule
from stock_analysis.screening import DeterministicScreeningEngine, MarketSnapshot

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Pre-compile all rules once at cold-start
_COMPILED_RULES = {
    wl_id: (cfg, CanonicalRule.from_mapping(cfg["rule_def"]))
    for wl_id, cfg in RULE_CONFIGS.items()
}


def handler(event: dict, context: object) -> dict:
    s3 = boto3.client("s3")
    bucket = os.environ["CACHE_BUCKET"]
    engine = DeterministicScreeningEngine()

    for record in event["Records"]:
        body = json.loads(record["body"])
        run_date: str = body["run_date"]
        chunk_id: str = body["chunk_id"]
        tickers: list = body["tickers"]
        ticker_watchlists: dict = body.get("ticker_watchlists", {})

        logger.info("Processing chunk %s (%d tickers) for %s", chunk_id, len(tickers), run_date)

        # Fetch market data once for this chunk
        market_data = fetch_market_data(tickers)
        logger.info("Fetched data for %d/%d tickers", len(market_data), len(tickers))

        earnings = fetch_earnings_dates(list(market_data.keys()))
        for ticker, info in earnings.items():
            if ticker in market_data:
                market_data[ticker]["earnings_in_days"] = info["days"]
                market_data[ticker]["earnings_date"] = info["date"]
                market_data[ticker]["earnings_timing"] = info["timing"]
        logger.info("Earnings dates resolved for %d/%d tickers", len(earnings), len(market_data))

        # Apply every rule to every ticker in a single pass
        stock_results = []
        total_matched = 0
        for ticker, metrics in market_data.items():
            full_metrics = {**metrics, "company_name": COMPANY_NAMES.get(ticker, ticker)}
            snapshot = MarketSnapshot(symbol=ticker, metrics=full_metrics)
            matched_rules = []
            for wl_id, (cfg, rule) in _COMPILED_RULES.items():
                result = engine.evaluate(snapshot, rule)
                if result.matched:
                    matched_rules.append({
                        "watchlist_id": wl_id,
                        "rule_name": cfg["rule_def"]["name"],
                        "score": result.score,
                        "reasons": [e.reason for e in result.matched_conditions],
                    })
            if matched_rules:
                total_matched += 1
            stock_results.append({
                "symbol": ticker,
                "metrics": full_metrics,
                "matched_rules": matched_rules,
                "watchlists": ticker_watchlists.get(ticker, []),
            })

        chunk_result = {
            "run_date": run_date,
            "chunk_id": chunk_id,
            "tickers": tickers,
            "stock_results": stock_results,
        }

        s3.put_object(
            Bucket=bucket,
            Key=f"derived/chunks/{run_date}/{chunk_id}.json",
            Body=json.dumps(chunk_result),
            ContentType="application/json",
        )
        logger.info("Wrote chunk %s: %d tickers matched at least one rule", chunk_id, total_matched)

    return {"processed": len(event["Records"])}
