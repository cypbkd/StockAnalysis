# Project Instructions
1. Always add tests for what you changed. If the change includes integration with external services, add an integration test and run it locally to ensure it works.
2. This `docs/ai-steering.md` document contains the overall project design and state, read it to understand what you are working with.
3. Always update `docs/ai-steering.md` with what you've done.
4. Always run `./scripts/test-and-deploy.sh` after making changes (including your tests).
5. Update CLAUDE.md so you don't make that mistake again.
6. When you make logic changes, ALWAYS add logs to help with the operations.
7. Company names live in `app/stock_analysis/data/company_names.json` — do NOT add them back as a hardcoded dict in `data.py`. NASDAQ tickers live in `app/stock_analysis/data/nasdaq_tickers.json`. Refresh with `scripts/update-nasdaq-tickers.sh`.
8. Active watchlists are: `spy500` (S&P 500), `nasdaq` (full NASDAQ), `djia` (30 DJIA). Do not re-add QQQ, FANG+, or Lao Li watchlists.