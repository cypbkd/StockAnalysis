# AI Steering — Nightly Stock Analysis

A single reference for understanding and working on this project. Covers architecture, code layout, AWS resources, deployment, and what's still to build.

---

## What This Is

A cloud-based nightly stock and options analysis system. Each US trading day at **8:00 PM PT** it:

1. Screens the S&P 500 + FANG + personal portfolio watchlists against **14 technical rules** in a single deduplicated pass
2. Fetches upcoming earnings dates for every screened ticker
3. Fetches the Yahoo Finance trending ticker list and enriches each with 3-day price/volume data + headlines (`trending.py`)
4. Fetches Yahoo Finance headlines for top high-priority + trending tickers and generates a **6-8 sentence market summary via Gemini**
4. Builds a report JSON and publishes it to a static CloudFront dashboard
5. Automatically invalidates the CloudFront cache so visitors always get the fresh report

The dashboard is a print-journalism Newsprint-themed static site. No backend, no login.

---

## Repo Layout

```
app/                        Python 3.11 — Lambda handlers + domain logic
  stock_analysis/
    __init__.py             Public API re-exports
    cache.py                S3 raw-data cache planning (CacheRequest, S3CachePlanner)
    chunking.py             Splits ticker lists into 50-ticker chunks (TickerChunker)
    data.py                 COMPANY_NAMES (loaded from data/company_names.json), RULE_CONFIGS, load_watchlists(), yfinance fetcher + indicator calc
    data/
      company_names.json    Static ticker→name lookup (~3345 entries); loaded at import time
      nasdaq_tickers.json   Full NASDAQ common-stock list (~3031 tickers); used by seed-watchlists.sh
    earnings.py             Parallel yfinance calendar fetch → {days, date, timing} per ticker
    rules.py                CanonicalRule, RuleCondition, SUPPORTED_FIELDS
    trending.py             Yahoo Finance trending list fetch + 3-day price/volume enrichment (build_trending_tickers)
    news.py                 Yahoo Finance RSS fetch + Gemini summarization (generate_news_summary)
    details.py              Gemini per-ticker trading brief (generate_ticker_analysis) → detailAnalysis JSON
    screening.py            DeterministicScreeningEngine, build_nightly_report
    cli.py                  Local CLI entry point
    handlers/
      coordinator.py        Lambda: chunks watchlists → SQS
      worker.py             Lambda: fetch + screen one chunk → S3
      aggregator.py         Lambda: combine chunks → report → S3 + CloudFront invalidation

infra/                      AWS CDK (TypeScript)
  lib/stock-analysis-infra-stack.ts   Full stack definition
  bin/infra.ts              CDK app entry — passes envName, depsLayerArn

web/                        Static dashboard (vanilla JS, no bundler)
  index.html
  src/
    main.js                 Loads report JSON; ?date=YYYY-MM-DD for history
    report-model.js         Report schema, sampleReport, createEmptyReport, validateReport
    report-renderer.js      Pure function: report JSON → HTML string
    styles.css              Newsprint design system
  reports/
    latest/report.json      Served by CloudFront as the live report

scripts/

tests/                      Python pytest suite
infra/test/                 CDK assertions (Jest)
web/tests/                  JS unit tests (node:test)
```

---

## AWS Architecture

### Resources (all in us-west-2, account 841425310647)

| Resource | Name / ID | Notes |
|---|---|---|
| S3 bucket | `stockanalysisinfradev-marketdatabucket61df0c4c-esoqnk197msd` | Bucket root = web root |
| CloudFront | `E2IOLFNFUVHVKE` | https://d2r08g384yeqpo.cloudfront.net |
| Lambda layer | `dev-stock-analysis-deps:3` | yfinance, pandas, numpy, google-genai for linux/x86_64 |
| SQS queue | `WorkerQueue` | 15-min visibility, DLQ with 3 retries |
| DynamoDB | `dev-watchlists`, `dev-rules`, `dev-runs`, `dev-notifications` | PAY_PER_REQUEST, PITR |
| SNS topic | `dev-stock-analysis-alarms` | `arn:aws:sns:us-west-2:841425310647:dev-stock-analysis-alarms` |
| CloudWatch alarms | `dev-coordinator-errors`, `dev-aggregator-errors`, `dev-worker-dlq-depth` | All → SNS topic |

### Nightly flow

```
5:00 PM PT  EventBridge → CoordinatorFunction
              deduplicates all tickers across watchlists, splits into 50-ticker chunks
              writes manifest to S3, sends all-NNN SQS messages

            WorkerFunction (one per SQS message, parallel)
              yfinance OHLCV download (365 days)
              computes SMA-20/50, EMA-20, RSI-14, high_52w, low_52w, volume_ratio,
              close_to_ath_pct, close_to_support_pct, pivot point levels (P/R1/R2/S1/S2),
              close_to_s1_pct, close_to_r1_pct, td_buy_setup, td_sell_setup, change_percent
              fetches earnings {days, date, timing} per ticker (parallel yfinance calendar calls)
              stores earnings_in_days, earnings_date, earnings_timing in each ticker's metrics
              applies ALL 14 rules to every ticker in one pass → matched_rules[] per ticker
              writes derived/chunks/YYYY-MM-DD/all-{NNN}.json

5:10 PM PT  EventBridge → AggregatorFunction
              reads all chunk files (each ticker appears exactly once)
              sorts signals by match_count desc (more rules matched = higher priority)
              "high priority" = matched ≥ 5 rules; "matched" = 1–4 rules
              builds earnings_watch from symbols with earnings_date in Mon–Fri of current week
                (no cap on count; each entry includes date, weekday, timing fields)
              fetches Yahoo Finance trending list → enriches with 3-day price/volume data + headlines → trendingTickers[]
              merges high-priority screener symbols + trending symbols (deduped, capped 10) for news context
              fetches Yahoo Finance RSS headlines for combined set
              calls Gemini (gemini-2.5-flash, thinking disabled) → 6-8 sentence newsSummary
              each signal now includes technicalData (volumeRatio, rsi14, ema20, sma50,
                high52w, low52w, pivotR1/R2/S1/S2, earningsDate/InDays/Timing) for on-demand analysis
              writes reports/latest/report.json + reports/runs/YYYY-MM-DD/report.json
              triggers CloudFront invalidation on /reports/latest/report.json

On demand   AnalysisFunction (Lambda Function URL — called by the browser)
              triggered when the user opens a ticker detail page (hash routing: #symbol/TICKER)
              main.js reads config.json (written to S3 by deploy script) to get the Function URL
              Lambda checks S3 cache at analyses/{run_date}/{ticker}.json
              on cache miss: reads technicalData from report JSON, calls Gemini (gemini-2.5-flash),
                caches result to S3 so repeat views are free
              returns { summary, rules, priceTargets, verdict } JSON with CORS headers
              frontend replaces the "Generating trading brief…" placeholder with the rendered analysis
```

### S3 layout

```
derived/
  manifests/YYYY-MM-DD/manifest.json
  chunks/YYYY-MM-DD/all-{NNN}.json
reports/
  latest/report.json          ← always-current (CloudFront-invalidated each night)
  runs/YYYY-MM-DD/report.json ← historical archive
index.html                    ← dashboard shell (bucket root = CloudFront default root)
src/                          ← JS/CSS assets
```

---

## Active Rules

All 14 rules run against every deduplicated ticker on each nightly run. A ticker can match multiple rules; signals are ranked by match count.

| ID | Rule Name | Rule logic |
|---|---|---|
| `ma_stack` | Bullish MA Stack | close > EMA-20 AND EMA-20 > SMA-50 AND RSI-14 < 75 |
| `golden_cross` | Golden Cross | SMA-20 > SMA-50 AND prev_sma_20 <= prev_sma_50 (fresh crossover today) AND close > SMA-20 AND RSI-14 < 70 |
| `dead_cross` | Dead Cross | SMA-20 < SMA-50 AND prev_sma_20 >= prev_sma_50 (fresh crossover today) AND close < SMA-20 |
| `ath_breakout` | ATH Breakout | close >= high_52w AND volume_ratio >= 1.5 |
| `near_ath` | Near-ATH Consolidation | close_to_ath_pct <= 3.0 AND volume_ratio < 1.2 AND RSI-14 < 65 |
| `oversold_dip` | Oversold Dip in Uptrend | close > SMA-50 AND RSI-14 < 40 |
| `pre_earnings_momentum` | Pre-Earnings Momentum | earnings_in_days <= 7 AND close > SMA-20 AND RSI-14 >= 55 |
| `high_vol_day` | High-Volume Momentum Day | volume_ratio >= 2.0 AND RSI-14 >= 55 AND close > SMA-20 |
| `strong_trending_day` | Strong Trending Day | change_percent >= 3.0 AND close > SMA-20 AND volume_ratio >= 1.5 |
| `near_52w_support` | Near 52-Week Support (支撑位) | close_to_support_pct <= 5.0 AND RSI-14 < 45 |
| `pivot_s1_bounce` | Pivot S1 Bounce (支撑位) | close_to_s1_pct in [0, 3%] AND RSI-14 < 50 |
| `pivot_r1_breakout` | Pivot R1 Breakout (压力位) | close_to_r1_pct <= 0 AND volume_ratio >= 1.5 |
| `td_buy` | TD Sequential Buy Setup (神奇九转买入) | td_buy_setup >= 9 |
| `td_sell` | TD Sequential Sell Setup (神奇九转卖出) | td_sell_setup >= 9 |

**Signal priority:** `high priority` = ≥ 5 rules matched; `matched` = 1–4 rules.

Rules are hardcoded in `app/stock_analysis/data.py → RULE_CONFIGS`. DynamoDB-backed loading is a future task.

---

## Web Dashboard

- **URL routing**: `/?` loads latest; `/?date=YYYY-MM-DD` loads `reports/runs/YYYY-MM-DD/report.json`; `/#symbol/TICKER` opens the per-symbol detail page (hash routing, no page reload)
- **Per-symbol detail pages**: clicking a ticker in any signal card navigates to `#symbol/TICKER`. The detail page shows: symbol header (price, change %, status, watchlists), parsed trigger-condition chips from `signal.reason`, one rule card per matched rule name, and an **AI Trading Brief** section. The Trading Brief is lazy-loaded: `main.js` reads `config.json` to get the `AnalysisFunction` URL, calls it with `?ticker=TICKER&date=YYYY-MM-DD`, and patches the DOM placeholder once the analysis arrives. A "← Back to Report" link clears the hash.
- **History rail**: aggregator writes `/?date=YYYY-MM-DD` hrefs into `reportHistory` in the report JSON; the renderer renders them as sidebar links
- **Yahoo Finance links**: on the per-symbol detail page a "Yahoo Finance ↗" pill links to `https://finance.yahoo.com/quote/{TICKER}/`; earnings card tickers also link there. Options idea card tickers link to the Yahoo Finance options page with the primary strike pre-selected: `https://finance.yahoo.com/quote/{TICKER}/options/?straddle=true&strike={STRIKE}`. Signal card ticker symbols navigate to the detail page instead.
- **Design**: Newsprint theme — Playfair Display headlines, Lora body, JetBrains Mono metrics, 4×4px SVG dot grain background, collapsed-border grid, red accent `#cc0000`
- **No bundler**: plain ES modules, served directly from S3/CloudFront
- **Page title / H1**: derived dynamically from `reportDate` — format is `"<Month D, YYYY> Analysis Report"`. Do not use the `reportLabel` field for display; it is kept in the JSON but ignored by the renderer.
- **Timezone display**: raw tz-db strings (e.g. `America/Los_Angeles`) are converted to short abbreviations (`PDT`/`PST`) via `Intl.DateTimeFormat` in the renderer. The same helper is used in the masthead topline.
- **ISO timestamp sanitisation**: `generatedAt` from the aggregator sometimes arrives as `"...+00:00Z"` (redundant Z suffix). The renderer strips the trailing `Z` before parsing so `formatDisplayDate` always works.
- **Date-only string timezone fix**: `formatDisplayDate` appends `T12:00:00` to bare `YYYY-MM-DD` strings before parsing so they are treated as local noon, not UTC midnight. Without this, PDT (UTC-7) users see the previous calendar day (e.g. "Apr 29" renders as "Apr 28"). The same fix is applied in `main.js` for the `document.title` date label.
- **Earnings calendar "today" highlighting**: `renderEarningsCalendar` compares each entry's `date` field against `reportDate` to determine "today" (red). Previously it used the `priority` field (`"very high"` = days ≤ 1) which made Mon/Tue/Wed/Thu all red on a Wednesday run. Now only the column matching the report date gets the red `ec-priority-very-high` class.
- **Monday earnings capture**: `earnings.py` `_get_info` filter changed from `days >= -1` to `days >= -7` so companies that reported earlier in the current week (e.g. Monday when run is Wednesday) are included in the earnings watch calendar.
- **Score badge removed**: signals carry a 0–100 `score` field but the renderer does not display it — the pipeline already filters to quality signals so all scores are 100, making it noise.
- **Duplicate company name guard**: if `companyName === symbol` (no name data), the company name span is suppressed so the card doesn't show "AAPL / AAPL".
- **Rule-tag chips**: use `class="pill rule-tag"`. The `rule-tag` CSS overrides the pill's `min-height`/`min-width` (44 px touch targets) with `unset` so the tags render as compact inline chips (`0.65rem`, `2px 6px` padding).
- **Local dev server fixture**: `web/scripts/dev-server.mjs` intercepts `GET /reports/latest/report.json` and serves `web/tests/fixture-report.json` so the dashboard renders locally without S3 data.

---

## Key Design Decisions

- **Deterministic rules at runtime**: natural language is only for authoring; execution uses the structured `CanonicalRule`. AI rule translation is Phase 3 (not yet built).
- **Delayed/EOD data is fine**: yfinance free tier; correctness > speed.
- **Zip deployment, no Docker**: `lambda.Code.fromAsset("../app")` zips the app directory. The Lambda layer holds the heavy deps. CDK publish doesn't need Docker.
- **Cache-first**: the S3 raw-data cache layer (`cache.py`) exists for when a paid provider is added. Currently workers fetch fresh each run.
- **Static report**: one JSON write per night; no per-request compute.

---

## AWS Credentials

Profile: `stock-screener`

```bash
aws sts get-caller-identity --profile stock-screener
# account: 841425310647, user: stock-screener
export AWS_PROFILE=stock-screener
```

---

## Deploy

### One-command deploy (preferred)

```bash
./scripts/test-and-deploy.sh            # full test + deploy
./scripts/test-and-deploy.sh --test-only # tests only, no AWS changes
```

Runs pytest → CDK Jest → web node:test, then CDK build → CDK deploy → S3 sync → CloudFront invalidation. Aborts on any failure. Prints the dashboard URL on success.

### Manual steps (reference)

#### Pre-flight

```bash
python3 -m pytest
cd infra && npm test && npm run build && cd ..
cd web && npm test && cd ..
```

#### CDK (infrastructure + Lambda code)

```bash
cd infra
AWS_PROFILE=stock-screener CDK_DEFAULT_ACCOUNT=841425310647 CDK_DEFAULT_REGION=us-west-2 \
  npx cdk deploy StockAnalysisInfraDev --require-approval never
```

#### Web assets

```bash
AWS_PROFILE=stock-screener aws s3 sync web \
  s3://stockanalysisinfradev-marketdatabucket61df0c4c-esoqnk197msd \
  --exclude 'node_modules/*' --exclude 'tests/*' --exclude 'scripts/*'

AWS_PROFILE=stock-screener aws cloudfront create-invalidation \
  --distribution-id E2IOLFNFUVHVKE --paths '/*'
```

### Add or update a watchlist (no redeploy needed)

Watchlists live in the `dev-watchlists` DynamoDB table (`watchlistId` PK, `version` SK = `"latest"`).
Each item has `name` (display name, e.g. `"Lao Li"`) and `tickers` (string list).

```bash
# Seed all canonical watchlists from scratch
./scripts/seed-watchlists.sh

# Or add/update one watchlist via AWS CLI
aws dynamodb put-item --profile stock-screener --region us-west-2 \
  --table-name dev-watchlists \
  --item '{
    "watchlistId": {"S": "mywatchlist"},
    "version":     {"S": "latest"},
    "name":        {"S": "My Watchlist"},
    "tickers":     {"L": [{"S":"AAPL"},{"S":"MSFT"}]}
  }'
```

The next nightly run will pick it up automatically. No Lambda redeploy required.

### Trigger a manual nightly run

```bash
./scripts/run-analysis.sh                    # today's date, 5-min worker wait
./scripts/run-analysis.sh --date 2026-04-23  # specific date
./scripts/run-analysis.sh --wait 120         # shorter wait (e.g. small watchlist test)
```

Resolves Lambda names from CloudFormation outputs, invokes coordinator, waits for workers, then invokes aggregator. Checks each Lambda response for errors and aborts if one is found. Prints the dashboard URL on completion.

### Regenerate report only (aggregator only)

Use when workers have already run and you only need to rebuild the report (e.g. after a news summary fix or config change):

```bash
./scripts/run-aggregator.sh                    # today's date
./scripts/run-aggregator.sh --date 2026-04-26  # specific date
```

### Rebuild Lambda layer (when deps change)

The zip exceeds 50 MB so it must be uploaded via S3 rather than directly.

```bash
rm -rf /tmp/lambda-layer && mkdir -p /tmp/lambda-layer/python
pip3 install \
  --platform manylinux2014_x86_64 --implementation cp \
  --python-version 3.11 --only-binary=:all: \
  --target /tmp/lambda-layer/python \
  "yfinance>=0.2.50" "pandas>=2.0" "numpy>=1.24" "google-genai>=1.0"
cd /tmp/lambda-layer && zip -r ../layer.zip python -q

# Upload via S3 (direct upload limit is 50 MB; layer zip is ~52 MB)
AWS_PROFILE=stock-screener aws s3 cp /tmp/layer.zip \
  s3://stockanalysisinfradev-marketdatabucket61df0c4c-esoqnk197msd/layers/layer.zip \
  --region us-west-2

AWS_PROFILE=stock-screener aws lambda publish-layer-version \
  --layer-name dev-stock-analysis-deps \
  --description "yfinance + pandas + numpy + google-genai" \
  --compatible-runtimes python3.11 \
  --content S3Bucket=stockanalysisinfradev-marketdatabucket61df0c4c-esoqnk197msd,S3Key=layers/layer.zip \
  --region us-west-2 \
  --query LayerVersionArn --output text
# Update depsLayerArn in infra/bin/infra.ts with the returned ARN, then redeploy
```

### Local dev server

```bash
cd web && node scripts/dev-server.mjs   # falls back to port 4174
# Or: Claude Code launches it via .claude/launch.json
# Test history routing: http://localhost:4174/?date=YYYY-MM-DD
```

---

## Alarm Monitoring

Subscribe an email to receive run-failure alerts:

```bash
AWS_PROFILE=stock-screener aws sns subscribe \
  --topic-arn arn:aws:sns:us-west-2:841425310647:dev-stock-analysis-alarms \
  --protocol email --notification-endpoint you@example.com
```

Three alarms fire into this topic:
- `dev-coordinator-errors` — coordinator Lambda had ≥1 error (chunks may not have been dispatched)
- `dev-aggregator-errors` — aggregator Lambda had ≥1 error (report may not have been published)
- `dev-worker-dlq-depth` — messages are stuck in the dead-letter queue (a chunk failed after 3 retries)

---

## What's Done vs. What's Left

### Done ✅
- CDK infrastructure (S3, CloudFront, Lambda × 3, SQS, DynamoDB, EventBridge, SNS, CloudWatch)
- Nightly pipeline: Coordinator → Workers (parallel) → Aggregator
- Technical indicators: SMA-20/50, EMA-20, RSI-14, `high_52w`, `low_52w`, `volume_ratio`, `close_to_ath_pct`, `close_to_support_pct`, pivot levels (P/R1/R2/S1/S2), `close_to_s1_pct`, `close_to_r1_pct`, `td_buy_setup`, `td_sell_setup`, `change_percent` (365-day OHLCV)
- Earnings calendar fetch (`earnings.py`) — `earnings_in_days` injected into every ticker's metrics
- DeterministicScreeningEngine with AND/OR logic, scoring, per-condition reasons
- Real earnings_watch section (built from live chunk data, not hardcoded)
- CloudFront auto-invalidation after each nightly report publish
- Newsprint static dashboard — live at https://d2r08g384yeqpo.cloudfront.net
- Yahoo Finance links on all ticker symbols (quote page for signal/earnings cards, options page with strike for options cards)
- **14 active rules**: Bullish MA Stack, Golden Cross, Dead Cross, ATH Breakout, Near-ATH Consolidation, Oversold Dip, Pre-Earnings Momentum, High-Volume Day, Strong Trending Day, Near 52-Week Support, Pivot S1 Bounce, Pivot R1 Breakout, TD Sequential Buy (神奇九转), TD Sequential Sell
- Ticker deduplication in coordinator — each ticker fetched and screened exactly once; all rules applied in one pass per ticker
- Signal `ruleNames[]` array — tags show the rule name (e.g. "Bullish MA Stack") not the watchlist display name
- Priority by match count: `high priority` ≥ **5** rules matched; `matched` = 1–4 rules
- `scripts/test-and-deploy.sh` — one command runs all tests then full deploy; `--test-only` flag skips AWS
- `scripts/run-analysis.sh` — manual trigger: coordinator → worker wait → aggregator with retry on throttle
- `scripts/run-aggregator.sh` — invoke aggregator only (skips coordinator + workers); useful after news/config fixes
- Historical report navigation via `/?date=YYYY-MM-DD`
- CloudWatch alarms for coordinator errors, aggregator errors, DLQ depth
- Full test suite: Python pytest (122), CDK Jest (15), JS node:test (48) = **185 tests**
- Dashboard UX pass: date-based title, timezone abbreviation, ISO timestamp fix, score badge removed, duplicate company name guard, compact rule-tag chips, local dev server fixture routing
- **Per-symbol detail pages**: hash-routed (`#symbol/TICKER`); shows price/status header, parsed trigger-condition chips, one rule card per matched rule with description + natural-language statement; Yahoo Finance chart link; back navigation
- `COMPANY_NAMES` expanded to ~300 entries covering full S&P 500 + QQQ + DJIA + all watchlist tickers (was ~70 with duplicate keys)
- `WATCHLISTS` and `_SP500_TICKERS` consolidated into `data.py` — single source of truth for all ticker/watchlist/rule/company-name data; `coordinator.py` imports from there (both subsequently removed in favour of DynamoDB)
- **DynamoDB-backed watchlists** — `WATCHLISTS` constant removed from `data.py`; replaced by `load_watchlists(table_name)` which scans the `{ENV_NAME}-watchlists` table (version="latest" items). Coordinator calls it at runtime. Seed with `scripts/seed-watchlists.sh`. New watchlists no longer need a redeploy.
- **QQQ + DJIA watchlists** added to `seed-watchlists.sh` (`qqq` ≈ 90 Nasdaq-100 tickers; `djia` = 30 DJIA tickers); 17 new company name entries added to `COMPANY_NAMES` in `data.py` (ARM, ASML, AZN, CHKP, CRWD, DDOG, ILMN, MELI, MRVL, MSTR, PDD, TEAM, TTD, WDAY, ZM, ZS, and ABNB)
- **Watchlist reorganization**: watchlists simplified to 3 lists — `spy500` (S&P 500), `nasdaq` (full NASDAQ exchange, ~3031 common stocks), `djia` (30 DJIA). QQQ (Nasdaq-100), FANG+, and Lao Li watchlists removed. Company names moved from a hardcoded dict in `data.py` to a static JSON file at `app/stock_analysis/data/company_names.json` (3345 entries); NASDAQ ticker list stored at `app/stock_analysis/data/nasdaq_tickers.json`. Refresh the ticker list with `scripts/update-nasdaq-tickers.sh` (downloads from nasdaqtrader.com). Both JSON files are bundled with the Lambda zip — no code change needed when NASDAQ composition changes, just re-run the update + seed scripts.
- **Gemini news summary** (`news.py`): fetches Yahoo Finance RSS for up to 10 symbols (high-priority screener picks + trending tickers, deduped), calls `gemini-2.5-flash` (thinking disabled, 800 token budget) → 6-8 sentence plain-English market summary; result in `report.json` as `newsSummary`; fault-tolerant (returns `""` on any failure)
- **Trending Tickers section** (`trending.py`): fetches Yahoo Finance daily trending list (`/v1/finance/trending/US`), enriches each symbol with 3-day return, 1-day return, and volume ratio from yfinance, plus a top headline; stored in `report.json` as `trendingTickers[]`; rendered in the dashboard as a dedicated "Trending Tickers" section (Market Buzz label) above Today's Highlights and Watchlists, always shown regardless of rule matches; rank badge, positive/negative coloring, company name, and headline included per card; trending symbols are also merged into the Gemini news summary prompt so the AI considers market buzz alongside high-priority screener names
- **On-demand ticker analysis** (`details.py` + `handlers/analysis.py`): Lambda Function URL (open CORS) called by the browser when user opens a ticker detail page; checks S3 cache at `analyses/{date}/{ticker}.json`; on miss calls Gemini (`gemini-2.5-flash`, JSON mode, 2000 tokens) → `{ summary, rules, priceTargets, verdict, fundamentals }` and caches to S3; `config.json` (written to S3 by deploy script from CloudFormation output) tells the frontend the Function URL; local dev server serves mock config + mock analysis endpoint; each signal now includes `technicalData` (19 metrics) so the analysis Lambda can build the prompt without reading chunk files
- **Fundamentals on-demand** (`handlers/analysis.py` → `_fetch_fundamentals`): on cache miss (or cache hit without fundamentals), fetches `trailingPE`, `forwardPE`, `trailingEps`, `forwardEps`, `earningsGrowth` from `yfinance.Ticker.info`; computes **Revised Graham fair value** = `EPS × (8.5 + 2g) × 4.4 / Y` where Y is the current 10-year Treasury yield from `yf.Ticker("^TNX")` (falls back to 4.4% if unavailable); growth `g` clamped 0–50%; returns `fairPrice` + `bondYield` in the `fundamentals` dict and displays the formula note in the "Fundamental Snapshot" UI block
- **Long-term (200-day) S/R levels** (`data.py`): `fetch_market_data` now computes `sma_200`, `high_200d`, `low_200d`, and standard pivot-point formula applied to the 200-day H/L range → `lt_pivot_r1/r2/s1/s2` (S2 clamped ≥ 0); also stores full current-session OHLC (`open`, `high`, `low`) and prior-session OHLC (`prev_open`, `prev_high`, `prev_low`); stored in `technicalData` as `sma200`, `high200d`, `low200d`, `ltR1/R2/S1/S2`, `sessionOpen/High/Low`, `prevOpen/Close/High/Low`, `pivotPoint`
- **Split S/R panels on detail page**: two separate sections render below the earnings badge: (1) **Daily Session & Pivot Levels** (`renderStLevels`) — current session OHLC, prior-session reference, daily pivot P/R1/R2/S1/S2; (2) **200-Day S/R Map** (`renderLtLevels`) — 200d High/Low, SMA-200, LT R1/R2/S1/S2; both render immediately without waiting for the AI analysis
- **Earnings badge on detail page**: if `earningsInDays` is in [−7, 7], a badge renders immediately below the header showing the date, days count, and timing (Before Open / After Close / TBD); urgent style (red border) for ≤1 day, soon style (green border) for 2–7 days
- **TradingView candlestick chart**: on detail page, `main.js` dynamically injects the TradingView Advanced Chart widget (`embed-widget-advanced-chart.js`, style: "1" = candles, 6-month range) into the `#tradingview-chart-container` after the innerHTML is set; uses the ticker symbol directly (TradingView auto-resolves US exchange)
- **Earnings `run_date` fix** (`earnings.py`, `worker.py`): `fetch_earnings_dates` now accepts a `run_date` parameter (YYYY-MM-DD) and uses it as the reference date for computing `earnings_in_days`. Workers pass `run_date` from the SQS message body. This prevents a 1-day shift caused by the nightly workers executing after midnight UTC (5 PM PT = midnight UTC), which previously made `date.today()` return the next calendar day, causing Tue/Wed earnings to be mis-classified as "very high" priority in the earnings watch calendar.
- **Real options chain analysis** (`options.py`): replaces the previous naive strategy assignment (day change ≥ 0 → "Bullish call spread") with live yfinance option chain fetches. `build_options_ideas()` now runs against **all matched tickers** (no fixed universe), taking the top `max_candidates=40` by match_count, fetching real chains for each, and returning up to `max_ideas=10`. Picks the nearest ~21 DTE expiration, selects a specific strike (~5% OTM), and returns `OptionIdea` objects with bid/ask mid, IV%, open interest, volume, and breakeven/net-debit info. Bullish signals → cash-secured put; bearish signals → bear put spread. Min OI filter of 50 contracts ensures liquidity. Falls back gracefully if yfinance is unavailable.
- **Composite scoring + Top Pick highlighting**: each `OptionIdea` now carries a `highlighted: bool` field. The composite score = options quality (60%) + screening strength (40%). Options quality factors: IV sweet-spot (25–65% → 25 pts), OI depth log-scale (25 pts), RSI alignment (20 pts), price vs SMA-20 (20 pts), OTM cushion (10 pts). Screening strength = match_count / 14 rules. Top 3 ideas by composite score get `highlighted=True`, which the frontend renders with a red left border + "★ Top Pick" badge (`options-highlight` CSS class, `pill-alert` pill).
- **Gemini API key** in AWS Secrets Manager as `stock-analysis/gemini-api-key`; managed via `scripts/manage-gemini-key.sh`; local dev uses `GEMINI_API_KEY` env var
- **Earnings API key** in AWS Secrets Manager as `stock-analysis/earnings-api-key`; local dev uses `EARNINGS_API_KEY`. Workers use yfinance for dates, then call Earnings API only for the distinct dates yfinance returned. Daily Earnings API responses are cached in S3 at `raw/earnings-api/date=YYYY-MM-DD/calendar.json` to stay within the free-tier limit.
- **Lambda layer `:3`** (`arn:aws:lambda:us-west-2:841425310647:layer:dev-stock-analysis-deps:3`) — swapped `anthropic` for `google-genai>=1.0`; uploaded via S3 (zip ~52 MB)

### Next priorities ⬜
1. **Subscribe alarm email** — manual: `aws sns subscribe` to `dev-stock-analysis-alarms`
2. **SES email** — verify an identity; aggregator sends nightly summary linking to the dashboard
3. **Mobile layout** — current grid is desktop-first
4. **DynamoDB-backed rules** — `RULE_CONFIGS` is hardcoded in `data.py`; load from `dev-rules` table at runtime so rules can be updated without a redeploy (mirrors how watchlists work)
5. **DynamoDB-backed run history** — `dev-runs` table is provisioned but unused; record each nightly run's metadata (date, ticker count, signal count, S3 report key) so run history can be queried without scanning S3

### Out of scope for MVP
- Real-time intraday screening
- Direct broker execution
- AI rule authoring (Phase 3 — translate natural language → CanonicalRule via Gemini API)
- Automatic strategy backtesting
- Options greeks (delta/gamma/theta/vega) — yfinance doesn't expose them; would need Tradier or Schwab API
- IV rank/percentile — requires historical IV data not available from yfinance free tier
