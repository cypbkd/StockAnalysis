# Stock Analysis Screener

Cloud-based nightly stock and options analysis for S&P 500 and custom watchlists.

## Workspace Layout

- `app/`: Python jobs, domain models, and screening engine
- `containers/`: Batch image scaffolds
- `infra/`: AWS CDK infrastructure
- `scripts/`: local run helpers
- `web/`: static report site (Newsprint design theme)
- `docs/`: requirements, architecture, and implementation notes

## Delivery Approach

- test-first across app, infra, and web
- AWS CDK for infrastructure
- S3 cache-first ingestion strategy
- AWS Batch for chunked parallel analysis
- static site report delivery through S3 and CloudFront

## Local Development

Start the web preview server:

```bash
cd web && node scripts/dev-server.mjs
# open http://localhost:4173
```

A `.claude/launch.json` is included so Claude Code can launch and preview the site automatically.

## Local Validation

- Python tests: `python3 -m pytest`
- Infra tests: `cd infra && npm test`
- Web tests: `cd web && npm test`
- Regenerate sample report: `./scripts/run_local_sample_report.sh`

## Deployed Dev URL

- [CloudFront dashboard](https://d2r08g384yeqpo.cloudfront.net)

## Deployment

- [Deployment Guide](/Users/bruce/Documents/Projects/2026.04 StockAnlysis/docs/deployment.md)
