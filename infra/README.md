# Infra

AWS CDK app for the stock analysis MVP.

## Scripts

- `npm test` — run synthesis assertions
- `npm run build` — type-check the CDK app
- `npm run synth` — synthesise the CloudFormation templates

## Architecture

```
EventBridge (8:00 PM PT, Mon–Fri)
  └─▶ Coordinator Lambda   [containers/lambda/Dockerfile]
        ├── writes run manifest → S3 derived/manifests/{date}/
        └── sends SQS messages (one per 50-ticker chunk)
                ↓
        Worker Lambda × N   [same image, different CMD]
              ├── fetches yfinance OHLCV (90-day window)
              ├── computes SMA-20, SMA-50, EMA-20, RSI-14
              ├── runs DeterministicScreeningEngine
              └── writes chunk result → S3 derived/chunks/{date}/

EventBridge (8:25 PM PT, Mon–Fri)
  └─▶ Aggregator Lambda   [same image, different CMD]
        ├── reads all chunk results from S3
        ├── deduplicates and ranks signals
        └── writes reports/latest/report.json → S3
                ↓
        CloudFront serves report to dashboard
```

## Key resources provisioned

| Resource | Notes |
|---|---|
| S3 bucket | Raw data cache + static report hosting (bucket root = web root) |
| CloudFront | HTTPS distribution, caching disabled, `index.html` default root |
| Lambda – Coordinator | 5 min timeout, 512 MB |
| Lambda – Worker | 15 min timeout, 1024 MB, SQS event source (batch size 1) |
| Lambda – Aggregator | 5 min timeout, 512 MB |
| Lambda Layer | `dev-stock-analysis-deps:1` — yfinance, pandas, numpy (x86_64, Python 3.11) |
| SQS WorkerQueue | 15-min visibility, DLQ with 3 retries |
| EventBridge schedules | `dev-nightly-coordinator` (8:00 PM) + `dev-nightly-aggregator` (8:25 PM) |
| DynamoDB tables | `dev-watchlists`, `dev-rules`, `dev-runs`, `dev-notifications` |
| SES identity | Optional — set `REPORT_EMAIL_ADDRESS` env var before deploy |

## Active watchlists

| ID | Name | Symbols | Rule logic |
|---|---|---|---|
| `spy500` | SPY 500 | ~484 | AND — price > SMA-20 AND SMA-50, RSI < 70 |
| `fang` | FANG Watch | 8 | AND — price > SMA-20 AND EMA-20, RSI < 75 |
| `portfolio` | My Portfolio | 14 | OR — price > SMA-20 OR EMA-20 (tracks all holdings) |

## Notes

- **No Docker required.** All three Lambda functions are deployed as zip packages.
  Python dependencies live in the `dev-stock-analysis-deps` Lambda Layer.
  The layer ARN is hardcoded in `infra/bin/infra.ts`; update it when deps change.
- S3 web assets must be synced to the **bucket root** (no path prefix).
  See `docs/deployment.md` for the full deploy workflow.
- The SQS `visibilityTimeout` matches the worker Lambda timeout (15 min) to
  prevent duplicate processing.
