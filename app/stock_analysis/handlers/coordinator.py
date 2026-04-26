import json
import logging
import os
import boto3
from datetime import date

from stock_analysis.chunking import TickerChunker
from stock_analysis.data import RULE_CONFIGS, WATCHLISTS

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_CHUNK_SIZE = 50


def handler(event: dict, context: object) -> dict:
    run_date = event.get("run_date", date.today().isoformat())
    env_name = os.environ["ENV_NAME"]
    queue_url = os.environ["WORKER_QUEUE_URL"]
    bucket = os.environ["CACHE_BUCKET"]

    logger.info("Coordinator started: run_date=%s env=%s", run_date, env_name)

    sqs = boto3.client("sqs")
    s3 = boto3.client("s3")

    # Build ticker → [watchlist_ids] membership map
    ticker_watchlists: dict = {}
    for wl_id, wl in WATCHLISTS.items():
        for ticker in wl["tickers"]:
            ticker_watchlists.setdefault(ticker, []).append(wl_id)

    all_tickers = sorted(ticker_watchlists.keys())
    logger.info("Universe: %d unique tickers across %d watchlists", len(all_tickers), len(WATCHLISTS))

    chunker = TickerChunker(chunk_size=_CHUNK_SIZE, prefix="all")
    chunks = chunker.chunk(all_tickers)
    logger.info("Split into %d chunks of up to %d tickers each", len(chunks), _CHUNK_SIZE)

    for chunk in chunks:
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                "run_date": run_date,
                "env_name": env_name,
                "chunk_id": chunk.chunk_id,
                "tickers": chunk.tickers,
                "ticker_watchlists": {t: ticker_watchlists[t] for t in chunk.tickers},
            }),
        )
        logger.info("Queued chunk %s (%d tickers)", chunk.chunk_id, len(chunk.tickers))

    manifest = {
        "run_date": run_date,
        "env_name": env_name,
        "total_chunks": len(chunks),
        "total_symbols": len(all_tickers),
        "watchlists": {
            wl_id: {"name": wl["name"], "tickers": wl["tickers"]}
            for wl_id, wl in WATCHLISTS.items()
        },
        "rules": {
            rule_id: {"name": cfg["name"]}
            for rule_id, cfg in RULE_CONFIGS.items()
        },
    }
    s3.put_object(
        Bucket=bucket,
        Key=f"derived/manifests/{run_date}/manifest.json",
        Body=json.dumps(manifest, indent=2),
        ContentType="application/json",
    )
    logger.info("Manifest written to S3 for %s: %d chunks, %d symbols, %d rules",
                run_date, len(chunks), len(all_tickers), len(RULE_CONFIGS))

    return {
        "run_date": run_date,
        "chunks_sent": len(chunks),
        "total_symbols": len(all_tickers),
    }
