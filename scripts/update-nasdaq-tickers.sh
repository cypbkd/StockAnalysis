#!/usr/bin/env bash
# Periodic refresh script — NOT one-time use.
#
# Downloads the latest NASDAQ-listed stock symbols from nasdaqtrader.com and
# updates app/stock_analysis/data/nasdaq_tickers.json and company_names.json.
# Run quarterly (or whenever you want to pick up new listings / delistings),
# commit the updated JSON files, then re-run seed-watchlists.sh to push the
# changes to DynamoDB.
#
# Usage: ./scripts/update-nasdaq-tickers.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$SCRIPT_DIR/../app/stock_analysis/data"

echo "Fetching NASDAQ listed stocks from nasdaqtrader.com..."
TMP_RAW="$(mktemp)"
curl -s "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt" -o "$TMP_RAW"

echo "Parsing and filtering common stocks..."
python3 - "$TMP_RAW" "$DATA_DIR" << 'PYEOF'
import json, re, sys, os

src_file, data_dir = sys.argv[1], sys.argv[2]

EXCLUDE_KEYWORDS = [
    'warrant', 'right', ' unit', 'note', 'debenture', 'preferred',
    'depositary', 'acquisition', 'spac', 'blank check'
]

with open(src_file, encoding='utf-8') as f:
    content = f.read()

lines = content.strip().replace('\r\n', '\n').split('\n')
pattern = re.compile(r'^[A-Z]{1,5}$')

tickers = []
new_names = {}
for line in lines[1:]:
    if line.startswith('File Creation Time'):
        continue
    parts = line.split('|')
    if len(parts) < 8:
        continue
    symbol, name = parts[0].strip(), parts[1].strip()
    test_issue, is_etf, next_shares = parts[3].strip(), parts[6].strip(), parts[7].strip()

    if test_issue != 'N' or is_etf != 'N' or next_shares != 'N':
        continue
    if not pattern.match(symbol):
        continue
    if any(kw in name.lower() for kw in EXCLUDE_KEYWORDS):
        continue

    tickers.append(symbol)
    short_name = name.split(' - ')[0].split(' Common')[0].strip()
    new_names[symbol] = short_name

tickers.sort()
print(f"  Found {len(tickers)} common stocks")

# Write nasdaq_tickers.json
tickers_path = os.path.join(data_dir, 'nasdaq_tickers.json')
with open(tickers_path, 'w') as f:
    json.dump(tickers, f, indent=2)
print(f"  Wrote {tickers_path}")

# Merge into company_names.json — new names fill gaps, existing curated names are preserved
names_path = os.path.join(data_dir, 'company_names.json')
try:
    with open(names_path) as f:
        existing = json.load(f)
except FileNotFoundError:
    existing = {}

# NASDAQ names provide the base; curated existing names override
merged = {**new_names, **existing}
merged_sorted = dict(sorted(merged.items()))
with open(names_path, 'w') as f:
    json.dump(merged_sorted, f, indent=2)
print(f"  Updated {names_path} ({len(merged_sorted)} entries)")
PYEOF

rm -f "$TMP_RAW"
echo "Done. Re-run ./scripts/seed-watchlists.sh to push updated tickers to DynamoDB."
